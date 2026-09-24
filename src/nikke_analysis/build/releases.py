"""Unit debuts and recruitment windows, read out of update notices.

Every unit since launch arrived through an update notice that introduces it and
states its recruitment window, in a shape that has barely changed since 2022:

    1. 신규 니케
    1.1 SSR 니케 [길티 : 마이티 바니]
    괴력에 첨단 슈트를 더한 ..., SSR 니케 [길티 : 마이티 바니]가 특수 모집에 합류합니다.
    ...
    *특수 모집 기간: 2026년 9월 17일 서버 점검 종료 이후 ~ 2026년 10월 8일 4:59:59 (UTC+9)

A unit's release is the start of its first *debut* window - not the date of the
notice (published days earlier) and not the maintenance day (the second unit of
a patch usually opens a week later: [신 : 스위프트 바니] above starts 9/24).

Reading rules, all deterministic:

* Numbered headings (``1.``, ``1.1``, ``2-1.``) open a new subject. The subject is
  the unit named in the heading or, failing that, in the first introduction
  line after it ("SSR 니케 X가 ... 합류합니다"). A heading that names no unit
  clears the subject, so a New Year step-up recruit in its own section never
  inherits the previous unit.
* A line labelled "…모집 기간:", "…픽업 기간:" or "…획득 기간:" with a date
  range is a window for the subject.
* It is a debut when its section is a new-unit section ("신규 니케", "신규 캐릭터",
  "신규 한정 캐릭터") or the introduction says the unit joins (합류/참전) rather
  than rejoins (재합류); selection reruns ("선택 모집") never are.
* A unit introduced as new with no window at all is a free unit (an event,
  login or liberation reward); it arrives on the update's day, taken from the
  notice title ("4월 25일 업데이트 공지").
* Names are resolved through the roster's alias table and never guessed. A name
  two units share is settled only by which of them existed when the notice was
  written; a heading or introduction whose name still does not resolve is
  reported in ``release_unresolved.csv``.

Outputs:

``banners.csv``        every recruitment window found, debut or rerun
``unit_releases.csv``  one row per unit: its first debut window
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from ..paths import processed_dir
from ..util.kdate import KST, Stamp, find_points, find_spans
from ..util.names import NameIndex, normalize_name
from .notices import HEADING_RE, Notice

log = logging.getLogger(__name__)

RELEASES_CSV = "unit_releases.csv"
BANNERS_CSV = "banners.csv"
UNRESOLVED_CSV = "release_unresolved.csv"

WINDOW_RE = re.compile(r"(?P<label>[^:：\n]{0,30}(?:모집|획득|픽업)[^:：\n]{0,12}기간)\s*[:：]\s*(?P<value>.+)")
BRACKET_RE = re.compile(r"\[([^\[\]]{1,40})\]")
# "SSR 니케 X", "SR 캐릭터 [X]", "SSR 필그림 [X]" - the name follows the marker.
MARKER_RE = re.compile(r"(?:SSR|SR|R)\s*(?:니케|캐릭터|필그림)\s*\[?")
UNBRACKETED_MARKER_RE = re.compile(r"(?:SSR|SR|R)\s*(?:니케|캐릭터|필그림)\s*(?!\[)")
JOIN_WORDS = ("합류", "참전")
REJOIN_WORDS = ("재합류", "재모집", "복각", "다시 합류")
NOT_DEBUT_SECTION_WORDS = ("코스튬", "패키지", "상품")

BANNER_KINDS: tuple[tuple[str, str], ...] = (
    ("선택 모집", "limited_selection"),
    ("한정", "limited"),
    ("콜라보", "collab"),
    ("특수 모집", "special"),
    ("픽업", "special"),
    ("획득", "event_reward"),
)
# How far ahead of its data-file date a notice may name a unit. Used only to
# tell apart units that share a name (two 사쿠라s, 2023 and 2025).
DATAFILE_LEAD_DAYS = 21


@dataclass
class Banner:
    unit_id: str
    kind: str
    debut: int
    start_at: str
    end_at: str
    start_after_maintenance: int
    notice_id: str
    notice_title: str
    notice_published_at: str
    label: str
    evidence: str


@dataclass
class UnitRelease:
    unit_id: str
    release_at: str
    release_date: str
    release_after_maintenance: int
    banner_kind: str
    notice_id: str
    notice_title: str
    notice_published_at: str
    evidence: str


@dataclass
class Unresolved:
    notice_id: str
    notice_title: str
    name: str
    line: str


# --------------------------------------------------------------------------
# name resolution
# --------------------------------------------------------------------------

class UnitMatcher:
    """Finds the unit a heading or introduction line is about.

    ``known_since`` (unit id -> the date the unit entered the game's data) is
    what settles a name two units share: a notice can only mean a unit that
    already existed when it was written.
    """

    def __init__(self, index: NameIndex, known_since: dict[str, str] | None = None):
        self.index = index
        self.known_since = known_since or {}
        keys = {**index.secondary, **index.primary}
        # Longest first, so "홍련 : 흑영" wins over "홍련".
        self._by_length = sorted(keys.items(), key=lambda kv: len(kv[0]), reverse=True)

    def resolve(self, name: str, when: date | None = None) -> str | None:
        unit = self.index.resolve(name)
        if unit is not None or when is None:
            return unit
        candidates = self.index.candidates(name)
        if len(candidates) < 2:
            return None
        horizon = (when + timedelta(days=DATAFILE_LEAD_DAYS)).isoformat()
        existing = [u for u in candidates if self.known_since.get(u, "9999") <= horizon]
        return existing[0] if len(existing) == 1 else None

    def bracketed(self, line: str, when: date | None = None) -> tuple[list[str], list[str]]:
        """Units named in ``[...]`` and the bracketed names that did not resolve."""
        found: list[str] = []
        missing: list[str] = []
        for raw in BRACKET_RE.findall(line):
            unit = self.resolve(raw, when)
            if unit is not None:
                if unit not in found:
                    found.append(unit)
            else:
                missing.append(raw)
        return found, missing

    def after_marker(self, line: str) -> str | None:
        """The unit whose name directly follows an "SSR 니케" style marker."""
        for match in UNBRACKETED_MARKER_RE.finditer(line):
            tail = normalize_name(line[match.end():match.end() + 40])
            for key, unit in self._by_length:
                if key and tail.startswith(key):
                    return unit
        return None

    def subject(self, line: str, when: date | None = None) -> tuple[str | None, list[str]]:
        units, missing = self.bracketed(line, when)
        if units:
            return units[0], []
        unit = self.after_marker(line)
        if unit is not None:
            return unit, []
        # A bracketed name right after a marker that did not resolve is a unit
        # we do not know yet - worth reporting. Other brackets (costumes,
        # bosses, menu paths) are not.
        reported = [name for name in missing if MARKER_RE.search(line.split(f"[{name}]")[0][-12:] + "[")]
        return None, reported


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def _banner_kind(label: str) -> str:
    for marker, kind in BANNER_KINDS:
        if marker in label:
            return kind
    return "recruit"


def _is_join_line(line: str) -> bool:
    return any(word in line for word in JOIN_WORDS)


def is_debut_section(title: str) -> bool:
    """"1. 신규 니케", "1. 신규 캐릭터", "1. 신규 한정 캐릭터" - not "신규 캐릭터 패키지"."""
    return (
        "신규" in title
        and ("니케" in title or "캐릭터" in title)
        and not any(word in title for word in NOT_DEBUT_SECTION_WORDS)
    )


def update_day(notice: Notice) -> Stamp:
    """The day an update notice's update went live, from its title ("4월 25일 업데이트 공지")."""
    points = find_points(notice.title, notice.published_at)
    day = points[0].at.date() if points else notice.published_at.date()
    return Stamp(datetime.combine(day, time(0, 0), KST), after_maintenance=True, has_time=False)


def extract_banners(notice: Notice, matcher: UnitMatcher) -> tuple[list[Banner], list[Unresolved]]:
    banners: list[Banner] = []
    unresolved: list[Unresolved] = []
    when = notice.published_at.date()
    state = {"subject": None, "intro": "", "section": "", "windows": 0, "evidence": ""}

    def banner(unit: str, kind: str, debut: bool, start: Stamp, end: Stamp | None, label: str, evidence: str) -> Banner:
        return Banner(
            unit_id=unit,
            kind=kind,
            debut=int(debut),
            start_at=start.iso(),
            end_at=end.iso() if end else "",
            start_after_maintenance=int(start.after_maintenance),
            notice_id=notice.notice_id,
            notice_title=notice.title,
            notice_published_at=notice.published_at.isoformat(),
            label=label,
            evidence=evidence[:200],
        )

    def debut_context() -> bool:
        intro = state["intro"]
        if any(word in intro for word in REJOIN_WORDS):
            return False
        return is_debut_section(state["section"]) or _is_join_line(intro)

    def close_subject() -> None:
        # A unit introduced as new with no window of its own is a free unit -
        # an event, login or liberation reward. It arrived with the update.
        if state["subject"] is not None and state["windows"] == 0 and debut_context():
            banners.append(
                banner(state["subject"], "introduced", True, update_day(notice), None, "", state["evidence"])
            )

    def open_subject(unit: str | None, intro: str, evidence: str) -> None:
        state.update(subject=unit, intro=intro if unit else "", windows=0, evidence=evidence)

    for line in notice.lines:
        heading = HEADING_RE.match(line)
        if heading:
            close_subject()
            if "." not in heading.group("num") and "-" not in heading.group("num"):
                state["section"] = heading.group("rest")
            unit, missing = matcher.subject(heading.group("rest"), when)
            open_subject(unit, heading.group("rest"), line)
            unresolved.extend(Unresolved(notice.notice_id, notice.title, name, line) for name in missing)
            continue

        if state["subject"] is None and _is_join_line(line):
            unit, missing = matcher.subject(line, when)
            open_subject(unit, line, line)
            unresolved.extend(Unresolved(notice.notice_id, notice.title, name, line) for name in missing)
        elif state["subject"] is not None and _is_join_line(line) and not _is_join_line(state["intro"]):
            state["intro"] = line

        window = WINDOW_RE.search(line)
        if not window or state["subject"] is None:
            continue
        label = window.group("label").strip(" *＊-·•")
        spans = find_spans(window.group("value"), notice.published_at)
        if not spans or spans[0].end is None:
            continue
        kind = _banner_kind(label)
        debut = kind != "limited_selection" and debut_context()
        banners.append(banner(state["subject"], kind, debut, spans[0].start, spans[0].end, label, line))
        state["windows"] += 1

    close_subject()
    once: dict[str, Unresolved] = {}
    for item in unresolved:
        once.setdefault(normalize_name(item.name), item)
    return banners, list(once.values())


def _debut_key(banner: Banner) -> tuple[str, bool, str]:
    # On a tie a real recruitment window beats the update-day fallback.
    return (banner.start_at, banner.kind == "introduced", banner.notice_published_at)


def first_debuts(banners: Iterable[Banner]) -> list[UnitRelease]:
    """Each unit's earliest debut window. Reruns never set a release."""
    best: dict[str, Banner] = {}
    for banner in banners:
        if not banner.debut:
            continue
        current = best.get(banner.unit_id)
        if current is None or _debut_key(banner) < _debut_key(current):
            best[banner.unit_id] = banner
    releases = [
        UnitRelease(
            unit_id=b.unit_id,
            release_at=b.start_at,
            release_date=b.start_at[:10],
            release_after_maintenance=b.start_after_maintenance,
            banner_kind=b.kind,
            notice_id=b.notice_id,
            notice_title=b.notice_title,
            notice_published_at=b.notice_published_at,
            evidence=b.evidence,
        )
        for b in best.values()
    ]
    return sorted(releases, key=lambda r: (r.release_at, r.unit_id))


def _read_releases(path: Path | None) -> list[dict[str, str]]:
    target = path or (processed_dir() / RELEASES_CSV)
    if not target.is_file() or target.stat().st_size == 0:
        return []
    with target.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_unit_releases(path: Path | None = None) -> dict[str, str]:
    """``{unit_id: release_date}``, for the roster build."""
    return {row["unit_id"]: row["release_date"] for row in _read_releases(path) if row.get("release_date")}


def load_release_times(path: Path | None = None) -> dict[str, str]:
    """``{unit_id: release_at}`` - the instant, where the date alone is too coarse."""
    return {row["unit_id"]: row["release_at"] for row in _read_releases(path) if row.get("release_at")}


def _write(path: Path, rows: list[Any], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def build(
    notices: list[Notice],
    index: NameIndex,
    *,
    known_since: dict[str, str] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    matcher = UnitMatcher(index, known_since)
    banners: list[Banner] = []
    unresolved: list[Unresolved] = []
    for notice in notices:
        found, missing = extract_banners(notice, matcher)
        banners.extend(found)
        unresolved.extend(missing)

    # The same window is often restated - a notice and its correction, or an
    # extension notice quoting the old end next to the new one. One row per
    # window, and an extension only ever moves the end later.
    unique: dict[tuple[str, str, str, int], Banner] = {}
    for banner in sorted(banners, key=lambda b: b.notice_published_at):
        key = (banner.unit_id, banner.start_at, banner.kind, banner.debut)
        kept = unique.get(key)
        if kept is None or banner.end_at > kept.end_at:
            unique[key] = banner
    banners = sorted(unique.values(), key=lambda b: (b.start_at, b.unit_id, -b.debut))
    releases = first_debuts(banners)

    seen_names: set[tuple[str, str]] = set()
    unique_unresolved = []
    for item in unresolved:
        key = (item.notice_id, normalize_name(item.name))
        if key not in seen_names:
            seen_names.add(key)
            unique_unresolved.append(item)

    target = out_dir or processed_dir()
    target.mkdir(parents=True, exist_ok=True)
    _write(target / BANNERS_CSV, banners, list(Banner.__dataclass_fields__))
    _write(target / RELEASES_CSV, releases, list(UnitRelease.__dataclass_fields__))
    _write(target / UNRESOLVED_CSV, unique_unresolved, list(Unresolved.__dataclass_fields__))
    return {
        "banners": len(banners),
        "debut_banners": sum(b.debut for b in banners),
        "units_released": len(releases),
        "unresolved_names": len(unique_unresolved),
        "first_release": releases[0].release_date if releases else "",
        "last_release": releases[-1].release_date if releases else "",
    }
