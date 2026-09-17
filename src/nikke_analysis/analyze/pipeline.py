"""Wire the metric functions together and write the result tables.

Reads only from ``data/processed`` and writes only to ``data/processed``, so the
whole analysis can be re-run offline and reviewed as a diff.

Outputs:

``metrics_usage.csv``        per season, boss and unit - the base measurements
``metrics_tiers.csv``        per season and unit - composite score and tier
``metrics_tier_changes.csv`` tier movement between consecutive seasons
``metrics_meta_shift.csv``   how far the meta moved each season
``metrics_synergy.csv``      unit pairs that appear together above chance
``metrics_trajectory.csv``   each unit's debut / peak / current standing
``metrics_patch_impact.csv`` season transitions joined to the patches between them
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from ..paths import manual_dir, processed_dir
from . import metrics, tiers

log = logging.getLogger(__name__)

ROSTER_CSV = "roster.csv"
ENTRIES_CSV = "raid_entries.csv"
PATCHES_CSV = "patches.csv"
RELEASES_CSV = "unit_releases.csv"
CALENDAR_CSV = "season_calendar.csv"


def _read(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def load_inputs(data_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    directory = data_dir or processed_dir()
    roster = _read(directory / ROSTER_CSV)
    entries = _read(directory / ENTRIES_CSV)
    if not entries.empty:
        entries["rank"] = pd.to_numeric(entries["rank"], errors="coerce").fillna(0).astype(int)
        entries["slot"] = pd.to_numeric(entries["slot"], errors="coerce").fillna(0).astype(int)
        entries["score"] = pd.to_numeric(entries["score"], errors="coerce").fillna(0.0)

    calendar = _read(directory / CALENDAR_CSV)
    if calendar.empty:
        calendar = _read(manual_dir() / CALENDAR_CSV)

    return {
        "roster": roster,
        "entries": entries,
        "patches": _read(directory / PATCHES_CSV),
        "releases": _read(directory / RELEASES_CSV),
        "calendar": calendar,
    }


def patch_impact(
    shift: pd.DataFrame,
    patches: pd.DataFrame,
    releases: pd.DataFrame,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Attach each season transition to the patches that happened in between.

    This is the join that makes the project's question answerable: a meta shift
    on its own is a number, but "0.24 total variation across a transition that
    contained two banners and one balance patch, and three of the entrants were
    units released in that window" is an explanation.

    Requires a season calendar. Without one there is no way to say which patches
    fall inside a transition, so an empty frame is returned rather than a guess.
    """
    if shift.empty or calendar.empty or patches.empty:
        return pd.DataFrame()
    if not {"season", "start_date"}.issubset(calendar.columns):
        return pd.DataFrame()

    starts = {
        str(row["season"]): pd.to_datetime(row["start_date"], errors="coerce")
        for _, row in calendar.iterrows()
    }
    patch_dates = pd.to_datetime(patches["date"], errors="coerce")
    release_dates = (
        pd.to_datetime(releases["release_date"], errors="coerce") if not releases.empty else None
    )

    rows = []
    for _, transition in shift.iterrows():
        window_start = starts.get(str(transition["season_from"]))
        window_end = starts.get(str(transition["season_to"]))
        if pd.isna(window_start) or pd.isna(window_end):
            continue
        in_window = patches[(patch_dates > window_start) & (patch_dates <= window_end)]
        debut_units = []
        if release_dates is not None:
            mask = (release_dates > window_start) & (release_dates <= window_end)
            debut_units = sorted(releases.loc[mask, "unit_id"])
        rows.append(
            {
                "season_from": transition["season_from"],
                "season_to": transition["season_to"],
                "window_start": window_start.date().isoformat(),
                "window_end": window_end.date().isoformat(),
                "total_variation": transition["total_variation"],
                "jsd": transition["jsd"],
                "top_k_churn": transition["top_k_churn"],
                "newcomer_share": transition["newcomer_share"],
                "patches_in_window": len(in_window),
                "banners": int((in_window["kind"] == "banner").sum()) if "kind" in in_window else 0,
                "balance_patches": int((in_window["kind"] == "patchnote").sum())
                if "kind" in in_window
                else 0,
                "units_released": len(debut_units),
                "released_unit_ids": ", ".join(debut_units),
            }
        )
    return pd.DataFrame(rows)


def run(*, content: str = "soloraid", data_dir: Path | None = None) -> dict[str, Any]:
    directory = data_dir or processed_dir()
    inputs = load_inputs(directory)
    roster, entries = inputs["roster"], inputs["entries"]

    if roster.empty:
        raise RuntimeError("roster.csv is missing or empty; run `nikke build roster` first")
    if entries.empty:
        raise RuntimeError(
            "raid_entries.csv is missing or empty; run `nikke collect enikk` and "
            "`nikke build raids` first (see docs/enikk-setup.md)"
        )

    entries = entries[entries["content"] == content] if "content" in entries else entries
    if entries.empty:
        raise RuntimeError(f"no raid entries for content={content!r}")

    availability = metrics.build_availability(roster, entries, inputs["calendar"])
    usage = metrics.unit_usage(entries, roster, availability=availability)
    config = tiers.load_tier_config()
    scored = tiers.season_unit_scores(usage, roster, availability, config)
    shift = metrics.meta_shift(usage, roster)
    changes = tiers.tier_changes(scored, config)
    pairs = metrics.synergy(entries)
    arcs = metrics.trajectories(usage)
    impact = patch_impact(shift, inputs["patches"], inputs["releases"], inputs["calendar"])

    written: dict[str, str] = {}
    for name, frame in (
        ("metrics_usage.csv", usage),
        ("metrics_tiers.csv", scored),
        ("metrics_tier_changes.csv", changes),
        ("metrics_meta_shift.csv", shift),
        ("metrics_synergy.csv", pairs),
        ("metrics_trajectory.csv", arcs),
        ("metrics_patch_impact.csv", impact),
    ):
        path = directory / name
        frame.to_csv(path, index=False)
        written[name] = str(path)

    summary = {
        "content": content,
        "seasons": metrics.season_order(entries["season"]),
        "teams": int(entries.groupby(metrics.GROUP_KEYS + ["rank"]).ngroups),
        "units_seen": int(entries["unit_id"].nunique()),
        "availability_source": availability.source,
        "tier_counts": tiers.summarise(scored).get("tier_counts", {}),
        "mean_total_variation": float(shift["total_variation"].mean()) if not shift.empty else None,
        "written": written,
    }
    log.info("analysis complete: %s seasons, %s teams", len(summary["seasons"]), summary["teams"])
    return summary
