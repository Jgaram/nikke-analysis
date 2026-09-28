"""Wire the metric functions together and write the result tables.

Reads only from ``data/processed`` and writes only to ``data/processed``, so the
whole analysis can be re-run offline and reviewed as a diff. Nothing reads the
clock: "current" means "as of the newest ranking snapshot", so the same inputs
give byte-identical outputs.

The committed tables are computed on the server sample config/tiers.yaml names
(every server by default). ``run_servers`` computes the same tables on another
sample (``--server``/``--exclude``) into ``data/interim/servers/<choice>/``,
which is not committed, and reuses them while their inputs stay the same.

Outputs:

``metrics_seasons.csv``        per season: players, decks, whether it is final
``metrics_unit_season.csv``    per season and unit: every measurement, the season
                               tier, and the overall tier - and in a season of the
                               unit's element, its element tier - as of the
                               season's end
``metrics_overall_tiers.csv``  per unit, as of the newest data: the overall tier
                               and rank - the overall comparison table
``metrics_element_tiers.csv``  per element and unit of it, as of the newest data:
                               the tier and rank in that element, with the overall
                               tier beside - the element comparison tables. A unit
                               whose skill adds an element is listed under both
``metrics_tier_changes.csv``   units whose season, element or overall tier moved
``metrics_meta_shift.csv``     how far the meta moved each season
``metrics_synergy.csv``        unit pairs sharing a deck above chance, per season
``metrics_trajectory.csv``     each unit's debut / peak / current standing
``metrics_patch_impact.csv``   season transitions joined to the patches between them
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .. import servers as server_names
from ..paths import interim_dir, processed_dir
from ..servers import ServerFilter
from . import metrics, tiers

log = logging.getLogger(__name__)

ROSTER_CSV = "roster.csv"
ENTRIES_CSV = "raid_entries.csv"
SEASONS_CSV = "soloraid_seasons.csv"
NOTICES_CSV = "notices.csv"
BANNERS_CSV = "banners.csv"
RELEASES_CSV = "unit_releases.csv"

INPUTS = (ENTRIES_CSV, ROSTER_CSV, SEASONS_CSV, NOTICES_CSV, BANNERS_CSV, RELEASES_CSV)
STAMP = "stamp.json"

OUTPUTS = (
    "metrics_seasons.csv",
    "metrics_unit_season.csv",
    "metrics_overall_tiers.csv",
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


def comparison_tables(standing: tiers.Standings, info: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two comparison tables: every unit by overall tier, and each element's
    units by their tier in it (with the overall tier beside). ``info`` is the
    roster's unit columns, by unit id."""
    names = [c for c in ("name_ko", "name_en") if c in info.columns]
    overall = standing.overall.join(info, on="unit_id")
    first = ["overall_rank", "unit_id"] + names + [c for c in ("element", "extra_elements") if c in overall.columns]
    overall = overall[first + [c for c in overall.columns if c not in first]]
    beside = overall[["unit_id"] + names + ["overall_tier", "overall", "overall_rank", "provisional"]]
    elements = standing.elements.merge(beside, on="unit_id", how="left")
    first = ["element", "element_rank", "unit_id"] + names + ["source"]
    return overall, elements[first + [c for c in elements.columns if c not in first]]


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
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Every metric table from the processed tables in ``data_dir``, written to
    ``out_dir`` (default: ``data_dir`` itself)."""
    directory = data_dir or processed_dir()
    target = out_dir or directory
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
    chosen = config.server_filter
    if chosen:
        chosen.check(entries["server"].unique())  # a misspelt server must not pass as "every server"
    entries = metrics.select_population(
        entries, top_n=config.top_n, servers=config.servers, exclude=config.exclude_servers
    )
    if entries.empty:
        raise RuntimeError(f"no raid entries for content={content!r} in the configured population")

    summary_table = metrics.season_summary(entries, seasons, weighting=config.rank_weighting)
    table = metrics.unit_season(entries, roster, seasons, weighting=config.rank_weighting, ridge=config.deck_effect_ridge)
    table = tiers.season_tiers(table, config)
    history = tiers.tier_history(table, summary_table, config)
    newest = summary_table["collected_until"].max()
    info = roster.drop_duplicates("unit_id").set_index("unit_id")
    info = info[[c for c in metrics.UNIT_INFO if c in info.columns]]
    overall, elements = comparison_tables(tiers.standings(table, summary_table, newest, config), info)
    changes = tiers.tier_changes(history, config)
    shift = metrics.meta_shift(table)
    pairs = metrics.synergy(entries, min_decks=config.synergy_min_decks)
    if not pairs.empty:
        names = info["name_ko"].where(info["name_ko"] != "", info["name_en"])
        pairs.insert(3, "name_x", pairs["unit_id_x"].map(names))
        pairs.insert(4, "name_y", pairs["unit_id_y"].map(names))
    arcs = metrics.trajectories(table)
    impact = patch_impact(shift, inputs["patches"], inputs["releases"], seasons)

    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    frames = (summary_table, history, overall, elements, changes, shift, pairs, arcs, impact)
    for name, frame in zip(OUTPUTS, frames):
        path = target / name
        _write(frame, path)
        written[name] = str(path)

    final = summary_table[summary_table["final"]]
    live = summary_table[~summary_table["final"]]
    summary = {
        "content": content,
        "servers": server_names.ordered(entries["server"].unique()),
        "server_filter": chosen.to_dict(),
        "seasons": len(summary_table),
        "final_seasons": len(final),
        "live_season": int(live["season"].max()) if not live.empty else None,
        "rankers": int(summary_table["rankers"].sum()),
        "units_fielded": int(entries["unit_id"].nunique()),
        "as_of": newest.tz_convert("Asia/Seoul").isoformat() if not pd.isna(newest) else None,
        **tiers.summarise(history, config),
        "written": written,
    }
    log.info("analysis complete: %s seasons, %s players", summary["seasons"], summary["rankers"])
    return summary


# --------------------------------------------------------------------------
# another server sample
# --------------------------------------------------------------------------

def server_dir(chosen: ServerFilter, cache_dir: Path | None = None) -> Path:
    """Where the tables for a server choice live: ``data/interim/servers/<choice>/``."""
    return (cache_dir or interim_dir() / "servers") / chosen.slug


def _plain(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else str(value)


def _fingerprint(directory: Path, config: tiers.TierConfig, content: str) -> dict[str, Any]:
    """Everything the tables depend on: the input tables (size and mtime), the
    parameters, and the analysis code itself."""
    inputs = {}
    for name in INPUTS:
        path = directory / name
        if path.is_file():
            stat = path.stat()
            inputs[name] = [stat.st_size, stat.st_mtime_ns]
    code = hashlib.sha256()
    for module in (metrics.__file__, tiers.__file__, __file__, server_names.__file__):
        code.update(Path(module).read_bytes())
    stamp = {
        "data_dir": str(directory.resolve()),
        "content": content,
        "config": asdict(config),
        "inputs": inputs,
        "code": code.hexdigest(),
    }
    return json.loads(json.dumps(stamp, default=_plain))


def run_servers(
    chosen: ServerFilter,
    *,
    content: str = "soloraid",
    data_dir: Path | None = None,
    config: tiers.TierConfig | None = None,
    cache_dir: Path | None = None,
    reuse: bool = True,
) -> dict[str, Any]:
    """The metric tables on the servers ``chosen`` picks, in ``server_dir(chosen)``.

    ``chosen`` replaces the configured server sample; every other parameter
    stays. The tables are reused while the inputs, the parameters and the code
    are unchanged (``reused`` in the result says which happened), so a second
    look at the same sample is instant. The committed tables are not touched.
    """
    directory = data_dir or processed_dir()
    config = (config or tiers.load_tier_config()).with_servers(chosen)
    target = server_dir(chosen, cache_dir)
    fingerprint = _fingerprint(directory, config, content)
    stamp = target / STAMP
    if reuse and stamp.is_file() and all((target / name).is_file() for name in OUTPUTS):
        try:
            saved = json.loads(stamp.read_text(encoding="utf-8"))
        except ValueError:
            saved = {}
        if saved.get("fingerprint") == fingerprint:
            return {**saved["summary"], "out_dir": str(target), "reused": True}
    summary = run(content=content, data_dir=directory, config=config, out_dir=target)
    summary = json.loads(json.dumps(summary, default=_plain))
    stamp.write_text(json.dumps({"fingerprint": fingerprint, "summary": summary}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return {**summary, "out_dir": str(target), "reused": False}
