"""Treasure (애장품) releases, read out of update notices.

A treasure upgrades one unit's skills for good - enough that the unit plays like
a different one, and every ranked player fields it with the treasure once it is
out. So a unit's tiers are reckoned apart before and after its treasure: a view
of a moment after it stands on the seasons since (analyze/tiers.py), while the
unit's history stays one line with the treasure marked on it. ``roster.csv``
carries the moment as ``treasure_at``.

The update that brings treasures lists the units on one line, in a shape that
has held since the first batch (2024-05):

    애장품이 추가되는 니케 : 라플라스, 엑시아, 프림, 디젤
    6.1 신규 애장품 니케: 바이퍼가 추가됩니다..
    ① 애장품 추가 니케 : [헬름], [미란다], [드레이크], [밀크]
    ▶ 애장품 추가 니케 : [팬텀], [슈가], [로산나], [플로라]

Reading rules, all deterministic:

* Only update notices count. A developer note that previews next year's
  treasures is a plan, not a release.
* A line reading "…애장품… 니케 :" names the units: the bracketed names, or the
  comma-separated list, less a closing "…가 추가됩니다".
* The treasure comes out with the update: the day in the notice's title ("7월
  23일 업데이트 공지"), after the maintenance - the day at 00:00, flagged, like a
  recruitment that opens "서버 점검 종료 이후".
* A unit named in several notices (a notice and its correction) takes the
  earliest update.
* Names go through the roster's alias table and are never guessed; a name that
  does not resolve is kept with an empty ``unit_id`` and reported by
  ``nikke check``.

Output: ``treasures.csv``, one row per unit (plus one per unresolved name).
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ..paths import processed_dir
from ..util.names import normalize_name
from .notices import Notice
from .releases import BRACKET_RE, UnitMatcher, update_day

TREASURES_CSV = "treasures.csv"

# "애장품이 추가되는 니케 :", "신규 애장품 니케:", "애장품 추가 니케 :".
LINE_RE = re.compile(r"애장품\s*(?:이\s*)?(?:추가되는\s*|추가\s*)?니케\s*[:：]\s*(?P<names>.+)")
# "바이퍼가 추가됩니다.." - the sentence the names end in, when they are not a list.
_TAIL_RE = re.compile(r"\s*(?:추가|출시)\s*(?:됩니다|되었습니다|돼요|합니다)\s*\.*\s*$")
_SPLIT_RE = re.compile(r"\s*(?:[,，、/]|\s및\s|\s그리고\s)\s*")
_PARTICLES = ("이", "가")


@dataclass
class Treasure:
    unit_id: str  # the base unit; empty when the name did not resolve
    name: str  # as the notice writes it
    treasure_at: str
    treasure_date: str
    after_maintenance: int
    notice_id: str
    notice_title: str
    notice_published_at: str
    evidence: str


def listed_names(text: str) -> list[str]:
    """The unit names a treasure line lists, as written."""
    bracketed = BRACKET_RE.findall(text)
    if bracketed:
        return [name.strip() for name in bracketed if name.strip()]
    text = _TAIL_RE.sub("", text.strip())
    return [name for name in (part.strip(" .·*") for part in _SPLIT_RE.split(text)) if name]


def _resolve(name: str, matcher: UnitMatcher, notice: Notice) -> tuple[str | None, str]:
    """The unit a listed name means, and the name without a closing particle
    ("바이퍼가" -> "바이퍼") when that is what resolved."""
    when = notice.published_at.date()
    unit = matcher.resolve(name, when)
    if unit is None and name.endswith(_PARTICLES) and len(name) > 1:
        unit = matcher.resolve(name[:-1], when)
        if unit is not None:
            return unit, name[:-1]
    return unit, name


def extract(notice: Notice, matcher: UnitMatcher) -> list[Treasure]:
    """The treasures an update notice brings; nothing for any other notice."""
    if notice.kind != "update":
        return []
    day = update_day(notice)
    found: list[Treasure] = []
    for line in notice.lines:
        match = LINE_RE.search(line)
        if not match:
            continue
        for listed in listed_names(match.group("names")):
            unit, name = _resolve(listed, matcher, notice)
            found.append(
                Treasure(
                    unit_id=unit or "",
                    name=name,
                    treasure_at=day.iso(),
                    treasure_date=day.at.date().isoformat(),
                    after_maintenance=int(day.after_maintenance),
                    notice_id=notice.notice_id,
                    notice_title=notice.title,
                    notice_published_at=notice.published_at.isoformat(),
                    evidence=line[:200],
                )
            )
    return found


def first_treasures(found: Iterable[Treasure]) -> list[Treasure]:
    """Each unit's earliest treasure, and each unresolved name once."""
    best: dict[str, Treasure] = {}
    for treasure in found:
        key = treasure.unit_id or f"?{normalize_name(treasure.name)}"
        kept = best.get(key)
        if kept is None or (treasure.treasure_at, treasure.notice_published_at) < (kept.treasure_at, kept.notice_published_at):
            best[key] = treasure
    return sorted(best.values(), key=lambda t: (t.treasure_at, t.unit_id == "", t.unit_id, t.name))


def load_treasures(path: Path | None = None) -> dict[str, dict[str, str]]:
    """``{base unit id: row}`` for every resolved treasure in ``treasures.csv``."""
    target = path or (processed_dir() / TREASURES_CSV)
    if not target.is_file() or target.stat().st_size == 0:
        return {}
    with target.open(encoding="utf-8", newline="") as handle:
        return {row["unit_id"]: row for row in csv.DictReader(handle) if row.get("unit_id") and row.get("treasure_at")}


def build(notices: list[Notice], matcher: UnitMatcher, *, out_dir: Path | None = None) -> dict[str, Any]:
    found: list[Treasure] = []
    for notice in notices:
        found.extend(extract(notice, matcher))
    treasures = first_treasures(found)

    target = out_dir or processed_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / TREASURES_CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Treasure.__dataclass_fields__))
        writer.writeheader()
        for treasure in treasures:
            writer.writerow(asdict(treasure))
    resolved = [t for t in treasures if t.unit_id]
    return {
        "treasures": len(resolved),
        "updates": len({t.notice_id for t in resolved}),
        "unresolved_names": [t.name for t in treasures if not t.unit_id],
        "first": resolved[0].treasure_date if resolved else "",
        "last": resolved[-1].treasure_date if resolved else "",
        "treasures_csv": str(path),
    }
