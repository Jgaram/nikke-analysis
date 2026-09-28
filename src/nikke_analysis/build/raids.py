"""Turn ranking snapshots into one tidy table of deck compositions.

Output (``raid_entries.csv``) is deliberately *long* - one row per unit slot:

    content, season, server, rank, player, score, deck, deck_score, slot,
    unit_id, unit_name_raw, unit_cp, unit_cores, collected_at

A Solo Raid ranker fields five decks of five units, every unit at most once, and
their score is the sum of the five decks' damage. Keeping the deck and its damage
on every row is what lets the metrics see *which* deck a unit carried - the main
deck or the fifth - which turns out to matter more than whether it was used.

Every metric downstream is a group-by over this table: usage is a count of rows,
synergy is a self-join on the deck, and nothing has to re-parse a packed string.

The layout of the site's response comes from ``config/enikk.yaml``. Ranking sites
restructure their JSON without warning and the snapshots may be irreplaceable, so
the recovery path is "edit a path in YAML and re-run", not "rewrite the parser".

Names are matched to unit ids through the roster's alias table. Two names are
shared by two units each (``Rei``: 라이 and 레이, ``Sakura``: 사쿠라 and the 2025
collaboration SR). The site does not say which, so a shared name is settled from
context, in order: only a unit already released when the season started; then the
burst stage the rest of the deck is missing (a deck needs I, II and III to burst);
then the element the boss is weak to. Anything still undecided is reported, not
guessed: a mis-joined name would corrupt every usage number it touches.

Context is a guess all the same, and for ``Rei`` it guessed wrong: the site's
``Rei`` is 레이 (Ayanami Rei), in Water-weak seasons too. So a name whose meaning
is known is pinned by hand in data/manual/ranking_names.csv. A pin holds from
the pinned unit's release on; before it (``Rei`` before 2024-08-29) the name is
settled from context as above.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ..config import RankingMapping
from ..paths import manual_dir, processed_dir
from ..util.jsonpath import resolve_one, resolve_path
from ..util.names import NameIndex, normalize_name, normalize_unit_id
from ..util.snapshot import SnapshotRun, list_runs
from .roster import load_alias_index

log = logging.getLogger(__name__)

SOURCE = "enikk_soloraid"
ENTRIES_CSV = "raid_entries.csv"
UNRESOLVED_CSV = "raid_unresolved_names.csv"
RANKING_NAMES_CSV = "ranking_names.csv"
BURST_STAGES = ("I", "II", "III")

__all__ = ["RaidEntry", "UnitResolver", "build", "parse_document", "resolve_one", "resolve_path"]


@dataclass
class RaidEntry:
    content: str
    season: int
    server: str
    rank: int
    player: str
    score: float
    deck: int
    deck_score: float
    slot: int
    unit_id: str
    unit_name_raw: str
    unit_cp: float | None
    unit_cores: int | None
    collected_at: str


# --------------------------------------------------------------------------
# value parsing
# --------------------------------------------------------------------------

def _as_float(value: Any) -> float:
    """Scores arrive as numbers, ``"1,234,567"`` or ``"12.3B"``."""
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
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return default


def _slot_value(values: Any, slot: int) -> Any:
    return values[slot] if isinstance(values, list) and slot < len(values) else None


# --------------------------------------------------------------------------
# name resolution
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitFacts:
    release_date: str
    element: str
    burst: str


def load_ranking_names(path: Path | None = None) -> dict[str, str]:
    """Which unit a name in the rankings means, from data/manual/ranking_names.csv
    (``name``, ``unit_id``, ``reason``), keyed by the normalised name. A row naming
    no name or no unit is skipped."""
    target = path or (manual_dir() / RANKING_NAMES_CSV)
    if not target.is_file():
        return {}
    with target.open(encoding="utf-8", newline="") as handle:
        return {
            normalize_name(row["name"]): normalize_unit_id(row["unit_id"])
            for row in csv.DictReader(handle)
            if (row.get("name") or "").strip() and (row.get("unit_id") or "").strip()
        }


class UnitResolver:
    """Name -> unit id, using the deck and the season when a name is shared, and
    the hand-kept ``pins`` (normalised name -> unit id) where context is not enough."""

    def __init__(
        self,
        index: NameIndex,
        units: dict[str, UnitFacts] | None = None,
        seasons: dict[int, dict[str, str]] | None = None,
        pins: dict[str, str] | None = None,
    ):
        self.index = index
        self.units = units or {}
        self.seasons = seasons or {}
        self.pins = pins or {}

    @classmethod
    def load(cls, directory: Path | None = None) -> "UnitResolver":
        directory = directory or processed_dir()
        index = load_alias_index(directory / "unit_aliases.csv")
        if index is None:
            raise RuntimeError("no alias table; run `nikke build timeline` first")
        units = {
            row["unit_id"]: UnitFacts(row.get("release_date", ""), row.get("element", ""), row.get("burst", ""))
            for row in _csv_rows(directory / "roster.csv")
        }
        seasons = {
            int(row["season"]): {"start": (row.get("start_at") or "")[:10], "weak": row.get("weak_element", "")}
            for row in _csv_rows(directory / "soloraid_seasons.csv")
            if row.get("season", "").isdigit()
        }
        return cls(index, units, seasons, load_ranking_names())

    def direct(self, name: str) -> str | None:
        return self.index.resolve(name)

    def pinned(self, name: str, season: int) -> str | None:
        """The unit ``name`` is pinned to, once that unit had been released by the
        season's start; ``None`` before then or for a name with no pin."""
        unit_id = self.pins.get(normalize_name(name))
        if unit_id is None:
            return None
        start = self.seasons.get(season, {}).get("start", "")
        released = self.units[unit_id].release_date if unit_id in self.units else ""
        return unit_id if not start or (released and released <= start) else None

    def candidates(self, name: str) -> set[str]:
        return self.index.candidates(name)

    def settle(self, candidates: set[str], season: int, deck_bursts: Iterable[str]) -> str | None:
        """Pick one of several units sharing a name, or ``None`` if context cannot."""
        context = self.seasons.get(season, {})
        start = context.get("start", "")
        pool = sorted(candidates)
        if start:
            released = [u for u in pool if self.units.get(u) and self.units[u].release_date and self.units[u].release_date <= start]
            pool = released or pool
        if len(pool) > 1:
            covered: set[str] = set()
            for burst in deck_bursts:
                if burst in BURST_STAGES:
                    covered.add(burst)
                elif "-" in burst:  # an all-stage burst ("I-II-III") covers every stage
                    covered.update(BURST_STAGES)
            missing = set(BURST_STAGES) - covered
            if missing:
                fitting = [u for u in pool if self.units.get(u) and self.units[u].burst in missing]
                pool = fitting if len(fitting) == 1 else pool
        if len(pool) > 1 and context.get("weak"):
            matching = [u for u in pool if self.units.get(u) and self.units[u].element == context["weak"]]
            pool = matching if len(matching) == 1 else pool
        return pool[0] if len(pool) == 1 else None

    def burst(self, unit_id: str) -> str:
        facts = self.units.get(unit_id)
        return facts.burst if facts else ""


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_document(
    document: Any,
    mapping: RankingMapping,
    resolver: UnitResolver,
    *,
    season: int,
    content: str = "soloraid",
) -> tuple[list[RaidEntry], list[tuple[str, str]]]:
    """Every (ranker, deck, slot) in one season's response.

    Returns ``(entries, unresolved)`` where ``unresolved`` holds
    ``(name, candidates)`` for each slot that could not be matched. An unmatched
    slot is dropped from the entries - its deck keeps the other four - and
    reported, never silently lost.
    """
    entries: list[RaidEntry] = []
    unresolved: list[tuple[str, str]] = []

    for position, record in enumerate(resolve_path(document, mapping.entries), start=1):
        rank = _as_int(resolve_one(record, mapping.rank), 0)
        if rank <= 0:
            continue  # outside the ranked population (enikk also lists look-ups)
        player = str(resolve_one(record, mapping.player, "") or "")
        server = str(resolve_one(record, mapping.server, "") or "")
        collected_at = str(resolve_one(record, mapping.collected_at, "") or "")
        decks = resolve_path(record, mapping.decks)
        deck_scores = [_as_float(resolve_one(deck, mapping.deck_score)) for deck in decks]
        score = _as_float(resolve_one(record, mapping.score)) or sum(deck_scores)

        for deck_number, (deck, deck_score) in enumerate(zip(decks, deck_scores), start=1):
            names = resolve_one(deck, mapping.deck_units) or []
            if not isinstance(names, list):
                continue
            cps = resolve_one(deck, mapping.deck_unit_cp)
            cores = resolve_one(deck, mapping.deck_unit_cores)
            ids: list[str | None] = [resolver.pinned(str(name), season) or resolver.direct(str(name)) for name in names]
            for slot, name in enumerate(names):
                if ids[slot] is not None:
                    continue
                candidates = resolver.candidates(str(name))
                if len(candidates) > 1:
                    bursts = [resolver.burst(u) for u in ids if u is not None]
                    ids[slot] = resolver.settle(candidates, season, bursts)
                if ids[slot] is None:
                    unresolved.append((str(name), ";".join(sorted(candidates))))
            for slot, (name, unit_id) in enumerate(zip(names, ids)):
                if unit_id is None:
                    continue
                cp = _slot_value(cps, slot)
                core = _slot_value(cores, slot)
                entries.append(
                    RaidEntry(
                        content=content,
                        season=season,
                        server=server,
                        rank=rank,
                        player=player,
                        score=score,
                        deck=deck_number,
                        deck_score=deck_score,
                        slot=slot,
                        unit_id=unit_id,
                        unit_name_raw=str(name),
                        unit_cp=_as_float(cp) if cp is not None else None,
                        unit_cores=_as_int(core) if core is not None else None,
                        collected_at=collected_at,
                    )
                )
    return entries, unresolved


def latest_by_season(runs: Iterable[SnapshotRun]) -> dict[int, tuple[SnapshotRun, str]]:
    """The newest stored response for each season: ``{season: (run, filename)}``.

    A season is re-read while it is being played; the last read is the most
    complete one, and after the season closes it is final.
    """
    latest: dict[int, tuple[SnapshotRun, str]] = {}
    for run in runs:  # oldest first
        for entry in run.entries:
            meta = entry.get("meta") or {}
            if meta.get("kind") == "rankings" and meta.get("raid"):
                latest[int(meta["raid"])] = (run, entry["filename"])
    return latest


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build(
    *,
    mapping: RankingMapping,
    source: str = SOURCE,
    content: str = "soloraid",
    out_dir: Path | None = None,
    resolver: UnitResolver | None = None,
    snapshot_root: Path | None = None,
) -> dict[str, Any]:
    target_dir = out_dir or processed_dir()
    resolver = resolver or UnitResolver.load(target_dir)
    runs = list_runs(source, root=snapshot_root)
    if not runs:
        raise RuntimeError(f"no {source} snapshots found; run `nikke collect enikk` first")

    all_entries: list[RaidEntry] = []
    unresolved: Counter[tuple[str, str]] = Counter()
    unresolved_seasons: dict[tuple[str, str], set[int]] = defaultdict(set)
    for season, (run, filename) in sorted(latest_by_season(runs).items()):
        try:
            document = json.loads(run.read(filename).decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable rankings %s/%s: %s", run.run_id, filename, exc)
            continue
        entries, missing = parse_document(document, mapping, resolver, season=season, content=content)
        all_entries.extend(entries)
        for item in missing:
            unresolved[item] += 1
            unresolved_seasons[item].add(season)

    all_entries.sort(key=lambda e: (e.content, e.season, e.server, e.rank, e.player, e.deck, e.slot))
    target_dir.mkdir(parents=True, exist_ok=True)
    entries_path = target_dir / ENTRIES_CSV
    with entries_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RaidEntry.__dataclass_fields__))
        writer.writeheader()
        for entry in all_entries:
            row = asdict(entry)
            row["unit_cp"] = "" if entry.unit_cp is None else f"{entry.unit_cp:.0f}"
            row["unit_cores"] = "" if entry.unit_cores is None else entry.unit_cores
            row["score"] = f"{entry.score:.0f}"
            row["deck_score"] = f"{entry.deck_score:.0f}"
            writer.writerow(row)

    unresolved_path = target_dir / UNRESOLVED_CSV
    with unresolved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "occurrences", "seasons", "candidates"])
        writer.writeheader()
        for (name, candidates), count in sorted(unresolved.items(), key=lambda kv: (-kv[1], normalize_name(kv[0][0]))):
            writer.writerow(
                {
                    "name": name,
                    "occurrences": count,
                    "seasons": ";".join(str(s) for s in sorted(unresolved_seasons[(name, candidates)])),
                    "candidates": candidates,
                }
            )

    seasons = sorted({e.season for e in all_entries})
    summary = {
        "seasons": len(seasons),
        "season_range": [seasons[0], seasons[-1]] if seasons else [],
        "rows": len(all_entries),
        "rankers": len({(e.season, e.server, e.player) for e in all_entries}),
        "decks": len({(e.season, e.server, e.player, e.deck) for e in all_entries}),
        "distinct_units": len({e.unit_id for e in all_entries}),
        "unresolved_slots": sum(unresolved.values()),
        "unresolved_names": len({name for name, _ in unresolved}),
        "entries_csv": str(entries_path),
    }
    if unresolved:
        log.warning("%s slot(s) did not resolve to a unit; see %s", summary["unresolved_slots"], unresolved_path)
    log.info("raid entries built: %s rows over %s seasons -> %s", len(all_entries), len(seasons), entries_path)
    return summary
