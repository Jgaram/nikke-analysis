"""Wire the metric functions together and write the result tables.

Reads only from ``data/processed`` and writes only to ``data/processed``, so the
whole analysis can be re-run offline and reviewed as a diff. Nothing reads the
clock: "current" means "as of the newest ranking snapshot", so the same inputs
give byte-identical outputs.

Outputs:

``metrics_seasons.csv``        per season: players, decks, whether it is final
``metrics_unit_season.csv``    per season and unit: every measurement, the season
                               tier, and the element profile as of that season's end
``metrics_element_tiers.csv``  per unit, as of the newest data: five element
                               slots, overall tier, best element, coverage, role
``metrics_tier_changes.csv``   units whose season or overall tier moved
``metrics_meta_shift.csv``     how far the meta moved each season
``metrics_synergy.csv``        unit pairs sharing a deck above chance, per season
``metrics_trajectory.csv``     each unit's debut / peak / current standing
``metrics_patch_impact.csv``   season transitions joined to the patches between them
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..paths import processed_dir
from . import metrics, tiers

log = logging.getLogger(__name__)

ROSTER_CSV = "roster.csv"
ENTRIES_CSV = "raid_entries.csv"
SEASONS_CSV = "soloraid_seasons.csv"
NOTICES_CSV = "notices.csv"
BANNERS_CSV = "banners.csv"
RELEASES_CSV = "unit_releases.csv"

OUTPUTS = (
    "metrics_seasons.csv",
    "metrics_unit_season.csv",
    "metrics_element_tiers.csv",
    "metrics_tier_changes.csv",
    "metrics_meta_shift.csv",
    "metrics_synergy.csv",
    "metrics_trajectory.csv",
    "metrics_patch_impact.csv",
)


def _read(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def load_inputs(data_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    directory = data_dir or processed_dir()
    entries = _read(directory / ENTRIES_CSV)
    if not entries.empty:
        entries["season"] = pd.to_numeric(entries["season"], errors="coerce").astype("Int64")
        for column in ("rank", "deck", "slot"):
            entries[column] = pd.to_numeric(entries[column], errors="coerce").fillna(0).astype(int)
        for column in ("score", "deck_score", "unit_cp"):
            entries[column] = pd.to_numeric(entries[column], errors="coerce")
        entries = entries.dropna(subset=["season"])
        entries["season"] = entries["season"].astype(int)
    return {
        "roster": _read(directory / ROSTER_CSV),
        "entries": entries,
        "seasons": metrics.season_frame(_read(directory / SEASONS_CSV)),
        "patches": patch_events(_read(directory / NOTICES_CSV), _read(directory / BANNERS_CSV)),
        "releases": _read(directory / RELEASES_CSV),
    }


def patch_events(notices: pd.DataFrame, banners: pd.DataFrame) -> pd.DataFrame:
    """Update notices and debut banners as one dated list (``date``, ``kind``).

    ``kind`` is ``patchnote`` for an update notice and ``banner`` for a unit's
    debut recruitment window - the two things a season transition is attributed to.
    """
    frames = []
    if not notices.empty and {"published_at", "kind"}.issubset(notices.columns):
        updates = notices[notices["kind"] == "update"]
        frames.append(pd.DataFrame({"date": updates["published_at"].str[:10], "kind": "patchnote", "title": updates["title"]}))
    if not banners.empty and {"start_at", "debut"}.issubset(banners.columns):
        debuts = banners[banners["debut"] == "1"]
        frames.append(pd.DataFrame({"date": debuts["start_at"].str[:10], "kind": "banner", "title": debuts["unit_id"]}))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["date", "kind"]).reset_index(drop=True)


def patch_impact(
    shift: pd.DataFrame,
    patches: pd.DataFrame,
    releases: pd.DataFrame,
    seasons: pd.DataFrame,
) -> pd.DataFrame:
    """Attach each season transition to the patches that happened in between.

    This is the join that makes the project's question answerable: a meta shift
    on its own is a number, but "0.24 total variation across a transition that
    contained two banners and one balance patch, and three of the entrants were
    units released in that window" is an explanation.
    """
    if shift.empty or seasons.empty or patches.empty:
        return pd.DataFrame()
    starts = seasons.set_index("season")["start_at"]
    patch_dates = pd.to_datetime(patches["date"], errors="coerce").dt.tz_localize("Asia/Seoul").dt.tz_convert("UTC")
    release_dates = (
        pd.to_datetime(releases["release_date"], errors="coerce").dt.tz_localize("Asia/Seoul").dt.tz_convert("UTC")
        if not releases.empty and "release_date" in releases.columns
        else None
    )
    rows = []
    for _, transition in shift.iterrows():
        window_start = starts.get(int(transition["season_from"]))
        window_end = starts.get(int(transition["season_to"]))
        if window_start is None or window_end is None or pd.isna(window_start) or pd.isna(window_end):
            continue
        in_window = patches[(patch_dates > window_start) & (patch_dates <= window_end)]
        debut_units: list[str] = []
        if release_dates is not None:
            mask = (release_dates > window_start) & (release_dates <= window_end)
            debut_units = sorted(releases.loc[mask, "unit_id"])
        rows.append(
            {
                "season_from": int(transition["season_from"]),
                "season_to": int(transition["season_to"]),
                "window_start": window_start.tz_convert("Asia/Seoul").date().isoformat(),
                "window_end": window_end.tz_convert("Asia/Seoul").date().isoformat(),
                "total_variation": transition["total_variation"],
                "jsd": transition["jsd"],
                "top_k_churn": transition["top_k_churn"],
                "newcomer_share": transition["newcomer_share"],
                "patches_in_window": len(in_window),
                "banners": int((in_window["kind"] == "banner").sum()),
                "balance_patches": int((in_window["kind"] == "patchnote").sum()),
                "units_released": len(debut_units),
                "released_unit_ids": ";".join(debut_units),
            }
        )
    return pd.DataFrame(rows)


def _instant_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Timestamps written as KST ISO strings, like every other table here."""
    out = frame.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.tz_convert("Asia/Seoul").map(lambda t: t.isoformat() if not pd.isna(t) else "")
    return out


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame = _instant_columns(frame)
    float_columns = frame.select_dtypes(include=[np.floating]).columns
    frame[float_columns] = frame[float_columns].round(6)
    frame.to_csv(path, index=False)


def run(
    *,
    content: str = "soloraid",
    data_dir: Path | None = None,
    config: tiers.TierConfig | None = None,
) -> dict[str, Any]:
    directory = data_dir or processed_dir()
    config = config or tiers.load_tier_config()
    inputs = load_inputs(directory)
    roster, entries, seasons = inputs["roster"], inputs["entries"], inputs["seasons"]

    if roster.empty:
        raise RuntimeError("roster.csv is missing or empty; run `nikke build timeline` first")
    if entries.empty:
        raise RuntimeError(
            "raid_entries.csv is missing or empty; run `nikke collect enikk` and `nikke build raids` first"
        )
    if seasons.empty:
        raise RuntimeError("soloraid_seasons.csv is missing; run `nikke build timeline` first")

    if "content" in entries.columns:
        entries = entries[entries["content"] == content]
    entries = metrics.select_population(entries, top_n=config.top_n, servers=config.servers)
    if entries.empty:
        raise RuntimeError(f"no raid entries for content={content!r} in the configured population")

    summary_table = metrics.season_summary(entries, seasons, weighting=config.rank_weighting)
    table = metrics.unit_season(entries, roster, seasons, weighting=config.rank_weighting, ridge=config.deck_effect_ridge)
    table = tiers.season_tiers(table, config)
    history = tiers.tier_history(table, summary_table, config)
    newest = summary_table["collected_until"].max()
    current = tiers.element_profiles(table, summary_table, newest, config)
    info = roster.drop_duplicates("unit_id").set_index("unit_id")
    info = info[[c for c in metrics.UNIT_INFO if c in info.columns]]
    current = current.join(info, on="unit_id")
    changes = tiers.tier_changes(history, config)
    shift = metrics.meta_shift(table)
    pairs = metrics.synergy(entries, min_decks=config.synergy_min_decks)
    if not pairs.empty:
        names = info["name_ko"].where(info["name_ko"] != "", info["name_en"])
        pairs.insert(3, "name_x", pairs["unit_id_x"].map(names))
        pairs.insert(4, "name_y", pairs["unit_id_y"].map(names))
    arcs = metrics.trajectories(table)
    impact = patch_impact(shift, inputs["patches"], inputs["releases"], seasons)

    written: dict[str, str] = {}
    for name, frame in zip(OUTPUTS, (summary_table, history, current, changes, shift, pairs, arcs, impact)):
        path = directory / name
        _write(frame, path)
        written[name] = str(path)

    final = summary_table[summary_table["final"]]
    live = summary_table[~summary_table["final"]]
    summary = {
        "content": content,
        "seasons": len(summary_table),
        "final_seasons": len(final),
        "live_season": int(live["season"].max()) if not live.empty else None,
        "rankers": int(summary_table["rankers"].sum()),
        "units_fielded": int(entries["unit_id"].nunique()),
        "as_of": newest.tz_convert("Asia/Seoul").isoformat() if not pd.isna(newest) else None,
        "roles": current["role"].value_counts().to_dict() if not current.empty else {},
        **tiers.summarise(history, config),
        "written": written,
    }
    log.info("analysis complete: %s seasons, %s players", summary["seasons"], summary["rankers"])
    return summary
