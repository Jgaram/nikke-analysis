"""The timeline tables, built in the order they depend on each other.

    roster (names)  ->  notices  ->  releases  ->  roster (dates)  ->  Solo Raid  ->  issues

The roster is built twice on purpose. Finding a unit in a notice needs the
alias table the roster build writes, and the roster's release dates come from
those notices. Two cheap passes beat a circular dependency.

Everything here reads snapshots already on disk; nothing touches the network.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from .. import health
from ..paths import processed_dir
from . import enikk_meta, notices, releases, roster, soloraid

log = logging.getLogger(__name__)


def _roster_rows(directory: Path) -> list[dict[str, str]]:
    path = directory / roster.ROSTER_CSV
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def availability(rows: list[dict[str, str]]) -> dict[str, str]:
    """``{unit_id: ISO instant}`` from which each unit existed in the game."""
    out: dict[str, str] = {}
    for row in rows:
        if row.get("release_at"):
            out[row["unit_id"]] = row["release_at"]
        elif row.get("release_date"):
            out[row["unit_id"]] = f"{row['release_date']}T00:00:00+09:00"
    return out


def build_timeline(*, out_dir: Path | None = None) -> dict[str, Any]:
    directory = out_dir or processed_dir()
    steps: dict[str, Any] = {}

    characters = enikk_meta.load_characters()
    steps["roster(names)"] = roster.build(enikk=characters, out_dir=directory)

    notice_list = notices.load_notices()
    if not notice_list:
        raise RuntimeError("no notice snapshots found; run `nikke collect notices` first")
    steps["notices"] = notices.build(notices=notice_list, out_dir=directory)

    index = roster.load_alias_index(directory / roster.ALIAS_CSV)
    if index is None:
        raise RuntimeError("the roster build wrote no alias table")
    known_since = {row["unit_id"]: row["datafile_added"] for row in _roster_rows(directory) if row["datafile_added"]}
    steps["releases"] = releases.build(notice_list, index, known_since=known_since, out_dir=directory)

    # "Never introduced by a notice" only means "shipped with the game" when the
    # notices reach back past the launch.
    launch = date.fromisoformat(roster.GLOBAL_LAUNCH_DATE)
    launch_covered = any(n.source == "official" and n.published_at.date() <= launch for n in notice_list)
    release_path = directory / releases.RELEASES_CSV
    steps["roster(dates)"] = roster.build(
        enikk=characters,
        patch_releases=releases.load_unit_releases(release_path),
        release_times=releases.load_release_times(release_path),
        launch_covered=launch_covered,
        out_dir=directory,
    )

    steps["soloraid"] = soloraid.build(
        notice_list,
        enikk_meta.load_seasons(),
        releases=availability(_roster_rows(directory)),
        out_dir=directory,
    )

    issues = health.data_issues(directory, steps["soloraid"]["problems"])
    health.write(directory, issues)
    steps["issues"] = {level: sum(1 for i in issues if i.level == level) for level in health.LEVELS}
    return steps
