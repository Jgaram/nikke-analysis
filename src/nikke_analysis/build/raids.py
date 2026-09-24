"""Turn ranking-site snapshots into one tidy table of team compositions.

Output (``raid_entries.csv``) is deliberately *long* - one row per unit slot,
not one row per team:

    content, season, boss, rank, score, player, slot, unit_id, unit_name_raw

Every metric downstream is a group-by over this table, which keeps the maths
honest: pick rate is a count of rows, synergy is a self-join, and a team never
has to be re-parsed out of a packed string.

The parser is driven by ``config/enikk.yaml`` rather than hard-coded field names.
Ranking sites restructure their JSON without warning, and the snapshots are
irreplaceable (a rotated-out season is gone for good), so the recovery path has
to be "edit a path in YAML and re-run", not "rewrite the parser".
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from ..config import FieldMapping
from ..paths import processed_dir
from ..util.names import NameIndex
from ..util.snapshot import SnapshotRun, list_runs
from .roster import load_alias_index

log = logging.getLogger(__name__)

ENTRIES_CSV = "raid_entries.csv"
UNRESOLVED_CSV = "raid_unresolved_names.csv"


@dataclass
class RaidEntry:
    content: str
    season: str
    boss: str
    rank: int
    score: float
    player: str
    slot: int
    unit_id: str
    unit_name_raw: str


# --------------------------------------------------------------------------
# dotted-path access
# --------------------------------------------------------------------------

def resolve_path(document: Any, path: str) -> list[Any]:
    """Walk a dotted path, flattening any segment marked ``[]``.

    ``"data.rankers[].team[].name"`` returns every unit name in the payload.
    A missing key yields ``[]`` rather than raising: a partially-populated
    response should cost us one field, not the whole season.
    """
    if not path:
        return []
    nodes: list[Any] = [document]
    for segment in path.split("."):
        iterate = segment.endswith("[]")
        key = segment[:-2] if iterate else segment
        next_nodes: list[Any] = []
        for node in nodes:
            value = node
            if key:
                if isinstance(node, dict):
                    value = node.get(key)
                elif isinstance(node, list) and key.isdigit():
                    index = int(key)
                    value = node[index] if index < len(node) else None
                else:
                    value = None
            if value is None:
                continue
            if iterate:
                if isinstance(value, list):
                    next_nodes.extend(value)
            else:
                next_nodes.append(value)
        nodes = next_nodes
    return nodes


def resolve_one(document: Any, path: str, default: Any = None) -> Any:
    values = resolve_path(document, path)
    return values[0] if values else default


def _as_float(value: Any) -> float:
    """Ranking scores arrive as ``"1,234,567"``, ``"12.3B"`` or plain numbers."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("_", "")
    multiplier = 1.0
    if text and text[-1] in "KkMmBbTt":
        multiplier = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}[text[-1].lower()]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return 0.0


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_document(
    document: Any,
    mapping: FieldMapping,
    index: NameIndex,
    *,
    content: str = "soloraid",
    season_default: str = "",
    boss_default: str = "",
) -> tuple[list[RaidEntry], list[str]]:
    """Extract every (rank, unit) pair from one snapshotted response.

    Returns ``(entries, unresolved_names)``. Unresolved names are returned, never
    dropped silently: an unmatched spelling means a unit is invisible to every
    pick rate, so it has to reach a human.
    """
    entries: list[RaidEntry] = []
    unresolved: list[str] = []

    records = resolve_path(document, mapping.entries)
    for position, record in enumerate(records, start=1):
        rank = _as_int(resolve_one(record, mapping.rank), position)
        score = _as_float(resolve_one(record, mapping.score))
        player = str(resolve_one(record, mapping.player, "") or "")
        season = str(resolve_one(record, mapping.season, "") or season_default)
        boss = str(resolve_one(record, mapping.boss, "") or boss_default)

        team = resolve_path(record, mapping.team)
        for slot, member in enumerate(team):
            unit_id = ""
            if mapping.unit_id:
                raw_id = resolve_one(member, mapping.unit_id)
                if raw_id not in (None, ""):
                    try:
                        from ..util.names import normalize_unit_id

                        unit_id = normalize_unit_id(str(raw_id))
                    except ValueError:
                        unit_id = ""

            raw_name = resolve_one(member, mapping.unit_name) if mapping.unit_name else member
            raw_name = "" if raw_name is None else str(raw_name)
            if not unit_id and raw_name:
                resolved = index.resolve(raw_name)
                if resolved is None:
                    unresolved.append(raw_name)
                    continue
                unit_id = resolved
            if not unit_id:
                continue

            entries.append(
                RaidEntry(
                    content=content,
                    season=season,
                    boss=boss,
                    rank=rank,
                    score=score,
                    player=player,
                    slot=slot,
                    unit_id=unit_id,
                    unit_name_raw=raw_name,
                )
            )
    return entries, unresolved


def parse_run(
    run: SnapshotRun, mapping: FieldMapping, index: NameIndex, *, content: str = "soloraid"
) -> tuple[list[RaidEntry], list[str]]:
    entries: list[RaidEntry] = []
    unresolved: list[str] = []
    meta_by_file = {e["filename"]: e.get("meta", {}) for e in run.entries}

    for filename, payload in run.iter_files(".json"):
        try:
            document = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            log.warning("bad JSON in %s/%s: %s", run.run_id, filename, exc)
            continue
        meta = meta_by_file.get(filename, {})
        file_entries, file_unresolved = parse_document(
            document,
            mapping,
            index,
            content=content,
            season_default=str(meta.get("season", "")),
            boss_default=str(meta.get("boss", "")),
        )
        entries.extend(file_entries)
        unresolved.extend(file_unresolved)
    return entries, unresolved


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build(
    *,
    mapping: FieldMapping,
    source: str = "enikk_soloraid",
    content: str = "soloraid",
    out_dir: Path | None = None,
) -> dict[str, Any]:
    if not mapping.configured:
        raise RuntimeError(
            "config/enikk.yaml has no field mapping yet. Run `nikke probe enikk`, "
            "read data/raw/enikk_probe/*/probe-report.json, then fill in the "
            "`mapping` block. See docs/enikk-setup.md."
        )
    index = load_alias_index()
    if index is None:
        raise RuntimeError("no alias table; run `nikke build roster` first")

    runs = list_runs(source)
    if not runs:
        raise RuntimeError(f"no {source} snapshots found; run `nikke collect enikk` first")

    all_entries: list[RaidEntry] = []
    unresolved: list[str] = []
    for run in runs:
        run_entries, run_unresolved = parse_run(run, mapping, index, content=content)
        all_entries.extend(run_entries)
        unresolved.extend(run_unresolved)

    # Later runs supersede earlier ones for the same (season, boss, rank, slot):
    # a season is re-snapshotted as it progresses and the latest view wins.
    deduped: dict[tuple[str, str, str, int, int], RaidEntry] = {}
    for entry in all_entries:
        deduped[(entry.content, entry.season, entry.boss, entry.rank, entry.slot)] = entry
    entries = sorted(
        deduped.values(), key=lambda e: (e.content, e.season, e.boss, e.rank, e.slot)
    )

    target_dir = out_dir or processed_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    entries_path = target_dir / ENTRIES_CSV
    with entries_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[f.name for f in RaidEntry.__dataclass_fields__.values()])
        writer.writeheader()
        for entry in entries:
            writer.writerow(asdict(entry))

    unresolved_counts = Counter(unresolved)
    unresolved_path = target_dir / UNRESOLVED_CSV
    with unresolved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "occurrences"])
        writer.writeheader()
        for name, count in unresolved_counts.most_common():
            writer.writerow({"name": name, "occurrences": count})

    summary = {
        "runs": len(runs),
        "rows": len(entries),
        "seasons": sorted({e.season for e in entries}),
        "bosses": sorted({e.boss for e in entries}),
        "teams": len({(e.season, e.boss, e.rank) for e in entries}),
        "distinct_units": len({e.unit_id for e in entries}),
        "unresolved_names": len(unresolved_counts),
        "entries_csv": str(entries_path),
    }
    if unresolved_counts:
        log.warning(
            "%s name(s) did not resolve to a unit; see %s",
            len(unresolved_counts),
            unresolved_path,
        )
    log.info("raid entries built: %s rows -> %s", len(entries), entries_path)
    return summary
