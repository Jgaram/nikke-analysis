"""The Solo Raid calendar: which season ran when, reconstructed from notices.

An update notice schedules a season ("솔로 레이드 시즌 41이 2026년 9월 24일
12:00:00에 오픈됩니다", followed by "*오픈 시간: A ~ B"). That schedule is not
always what happened. Seasons have been postponed before opening (8), suspended
and reopened on other dates (19, 26, 38), suspended for hours and extended (28),
and the lounge notices that say so are the only record. Reading the patch note
alone gets those seasons wrong, and so does reading enikk alone - it only knows
when it happened to collect rankings.

So the calendar is rebuilt in four steps, each deterministic:

1. **Events.** Every notice is read for Solo Raid statements: an opening with
   its window, a reopening, a rescheduling, a suspension (with its resume time
   when one is given), an extension, a postponement, a challenge-record reset,
   or - for a raid notice that changes nothing - an issue.
2. **Seasons.** Openings are grouped into seasons in time order. A later
   opening joins the previous season when it says so (same season number, or
   "재오픈"), when it overlaps the previous window (a correction), or when a
   suspension or postponement sits between them and it follows within
   ``REOPEN_GAP``. Early seasons carry no number in the notices; they are
   numbered by matching their play periods to enikk's collection windows, and
   by counting from numbered neighbours where enikk has nothing.
3. **Periods.** A season's events are replayed in time order to produce the
   intervals it was actually open.
4. **Checks.** Each season is compared with enikk: boss element, and whether
   enikk collected rankings outside the reconstructed periods. Disagreements
   are listed in the ``checks`` column, never resolved silently.

Outputs: ``soloraid_seasons.csv`` (one row per season), ``soloraid_periods.csv``
(one row per open interval), ``soloraid_events.csv`` (the evidence, one row per
statement) and ``season_calendar.csv`` (season, start_date, end_date - the shape
the analysis stage reads).
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from ..paths import processed_dir
from ..util.kdate import Stamp, find_points, find_spans, find_until
from .enikk_meta import EnikkSeason
from .notices import HEADING_RE, Notice

log = logging.getLogger(__name__)

SEASONS_CSV = "soloraid_seasons.csv"
PERIODS_CSV = "soloraid_periods.csv"
EVENTS_CSV = "soloraid_events.csv"
CALENDAR_CSV = "season_calendar.csv"

ELEMENTS_KO = {"작열": "Fire", "수냉": "Water", "풍압": "Wind", "철갑": "Iron", "전격": "Electric"}
LAUNCH_DATE = "2022-11-04"

OPENERS = ("open", "reopen", "reschedule")
# A reopening or a rescheduled window follows the original schedule's end by
# days, not weeks; consecutive seasons are two weeks or more apart.
REOPEN_GAP = timedelta(days=10)
# How far outside a season's window a suspension or extension notice can land
# and still be about it.
EVENT_SLACK = timedelta(days=3)
# How soon after a postponement notice the cancelled opening was due.
POSTPONE_REACH = timedelta(days=3)
# enikk keeps collecting for a few days after a season closes.
ENIKK_LAG = timedelta(days=5)

RAID_RE = re.compile(r"솔로\s*레이드")
SEASON_RE = re.compile(r"솔로\s*레이드\s*(?:-\s*)?시즌\s*(\d{1,3})")
OPEN_RE = re.compile(
    r"솔로\s*레이드(?:\s*시즌\s*(?P<season>\d{1,3}))?\s*(?:이|가|는|은)?\s+"
    r"(?P<when>[^.。]{4,70}?)\s*에?\s*(?P<re>재)?오픈(?:됩니다|될 예정|합니다|예정)"
)
RESCHEDULE_RE = re.compile(r"솔로\s*레이드\s*(?:시즌\s*(?P<season>\d{1,3}))?\s*의?\s*(?:진행|오픈)\s*(?:기간|일정)이[^.]*변경")
WINDOW_FIELD_RE = re.compile(r"(?:오픈|진행)\s*(?:시간|기간)\s*[:：]|^\s*[└ㄴ]")
ELEMENT_RE = re.compile(
    r"보스\s*속성\s*[:：]\s*(?P<element>작열|수냉|풍압|철갑|전격)\s*코드\s*[(（]\s*약점\s*[:：]?\s*(?P<weak>작열|수냉|풍압|철갑|전격)"
)
BOSS_BRACKET_RE = re.compile(r"보스\s*\[(?P<boss>[^\]\[]+)\]")
BOSS_TITLE_RE = re.compile(r"솔로\s*레이드\s*-\s*(?P<boss>[^\s(（][^(（]*?)\s*(?:관련|비정상|이슈|재오픈|중단|$)")
# "라벨: 값" - the colon must follow a non-digit, or "00:00" would read as a label.
FIELD_RE = re.compile(r"^(?P<label>.{1,60}?[^\d\s])\s*[:：]\s+(?P<value>.+)$")
BOSS_INLINE_RE = re.compile(r"솔로\s*레이드\s*(?:시즌\s*\d{1,3}\s*)?-\s*(?P<boss>[^\s,.()（）]+(?:\s[^\s,.()（）0-9]+){0,2})")
BOSS_PARTICLES = ("에서", "와", "과", "가", "이", "을", "를", "은", "는", "의", "에", "로")
# Words that follow a boss name without a particle: "애니힐리오 재오픈 기간은".
BOSS_STOP_WORDS = ("관련", "이슈", "재오픈", "오픈", "중단", "비정상", "진행", "전투", "기간", "안내", "결과", "시즌")
SUSPEND_WORDS = (
    "중단될 예정", "중단됩니다", "중단할 예정", "중단 일시", "중단 기간", "중단되었습니다",
    "정지될 예정", "정지됩니다", "정지 일시", "정지 기간",
)
FIELD_MARKS = ("✔", "✅", "☑")


@dataclass
class RaidEvent:
    kind: str
    notice: Notice
    evidence: str
    season: int | None = None
    start: Stamp | None = None
    end: Stamp | None = None
    boss_ko: str = ""
    element: str = ""
    weak_element: str = ""

    @property
    def effect_time(self) -> datetime:
        if self.kind in OPENERS or self.kind == "suspend":
            return self.start.at if self.start else self.notice.published_at
        if self.kind == "extend" and self.start is not None:
            return self.start.at
        return self.notice.published_at

    def key(self) -> tuple[Any, ...]:
        return (
            self.kind,
            self.start.iso() if self.start else "",
            self.end.iso() if self.end else "",
            self.season,
        )


@dataclass
class Period:
    start: Stamp
    end: Stamp | None
    end_reason: str


@dataclass
class Season:
    events: list[RaidEvent] = field(default_factory=list)
    number: int | None = None
    number_source: str = ""
    periods: list[Period] = field(default_factory=list)

    @property
    def openings(self) -> list[RaidEvent]:
        return [e for e in self.events if e.kind in OPENERS and e.start is not None]

    @property
    def explicit(self) -> set[int]:
        return {e.season for e in self.openings if e.season is not None}

    @property
    def first_start(self) -> datetime:
        return min(e.start.at for e in self.openings)

    @property
    def last_end(self) -> datetime:
        ends = [e.end.at for e in self.events if e.kind in (*OPENERS, "extend") and e.end is not None]
        return max(ends) if ends else self.first_start


# --------------------------------------------------------------------------
# 1. events
# --------------------------------------------------------------------------

def merge_fields(lines: list[str]) -> list[str]:
    """Lounge notices put a field's label and value on separate lines:

        ✔️ 중단 일시
        - 6/23(화) 4:59:59

    Joining them ("중단 일시: 6/23(화) 4:59:59") lets one line carry both.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(FIELD_MARKS):
            label = line.lstrip("".join(FIELD_MARKS) + "️ ").strip()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt and not nxt.startswith((*FIELD_MARKS, "📢", "🎁", "·", "※")):
                out.append(f"{label}: {nxt.lstrip('-└ㄴ ').strip()}")
                i += 2
                continue
            out.append(label)
            i += 1
            continue
        out.append(line)
        i += 1
    return out


def _season_of(text: str) -> int | None:
    match = SEASON_RE.search(text)
    return int(match.group(1)) if match else None


def _boss_from_title(title: str) -> str:
    match = BOSS_TITLE_RE.search(title)
    return match.group("boss").strip() if match else ""


def _bracket_boss(line: str) -> str:
    match = BOSS_BRACKET_RE.search(line)
    return match.group("boss").strip() if match else ""


def _boss_inline(line: str) -> str:
    """"솔로 레이드 - 애니힐리오를 ..." -> "애니힐리오"."""
    match = BOSS_INLINE_RE.search(line)
    if not match:
        return ""
    words = match.group("boss").split()
    # The name ends before a stop word, or where a particle attaches to a word.
    for index, word in enumerate(words):
        if any(word.startswith(stop) for stop in BOSS_STOP_WORDS):
            return " ".join(words[:index])
        for particle in BOSS_PARTICLES:
            if word.endswith(particle) and len(word) > len(particle):
                return " ".join(words[:index] + [word[: -len(particle)]])
    return " ".join(words)


def extract_events(notice: Notice) -> list[RaidEvent]:
    """Every Solo Raid statement in one notice."""
    title = notice.title
    raid_notice = bool(RAID_RE.search(title)) and "뮤지엄" not in title
    if not raid_notice and not RAID_RE.search(notice.text):
        return []

    notice_season = _season_of(title) if raid_notice else None
    if raid_notice and notice_season is None:
        notice_season = _season_of(notice.text)
    title_boss = _boss_from_title(title) if raid_notice else ""
    lines = merge_fields(notice.lines) if raid_notice else notice.lines
    published = notice.published_at

    events: list[RaidEvent] = []
    current: RaidEvent | None = None  # the opening the following window lines belong to
    in_raid_section = raid_notice

    for raw in lines:
        line = raw
        heading = HEADING_RE.match(raw) if not raid_notice else None
        if heading:
            rest = heading.group("rest")
            in_raid_section = bool(RAID_RE.search(rest)) and "뮤지엄" not in rest
            current = None
            line = rest

        opened = OPEN_RE.search(line)
        if opened:
            points = find_points(opened.group("when"), published)
            if points:
                season = opened.group("season")
                current = RaidEvent(
                    kind="reopen" if opened.group("re") else "open",
                    notice=notice,
                    evidence=line[:200],
                    season=int(season) if season else notice_season,
                    start=points[0],
                    boss_ko=_bracket_boss(line) or _boss_inline(line) or title_boss,
                )
                events.append(current)
                continue

        rescheduled = RESCHEDULE_RE.search(line)
        if rescheduled:
            season = rescheduled.group("season")
            current = RaidEvent(
                kind="reschedule",
                notice=notice,
                evidence=line[:200],
                season=int(season) if season else notice_season,
            )
            spans = find_spans(line, published)
            if spans:
                current.start, current.end = spans[0].start, spans[0].end
            events.append(current)
            continue

        if current is not None and (in_raid_section or raid_notice):
            if current.end is None and WINDOW_FIELD_RE.search(line):
                spans = find_spans(line, published)
                if spans and spans[0].end is not None:
                    # The window is the precise statement: "서버 점검 종료 이후
                    # 오픈" in the sentence is often "12:00:00" in the window.
                    current.start, current.end = spans[0].start, spans[0].end
                    current.evidence = f"{current.evidence} / {line[:120]}"
                    continue
            element = ELEMENT_RE.search(line)
            if element:
                current.element = ELEMENTS_KO[element.group("element")]
                current.weak_element = ELEMENTS_KO[element.group("weak")]
                continue

        if raid_notice:
            events.extend(_operational(line, notice, notice_season, title_boss))

    if raid_notice:
        events = _drop_vague_suspensions(events)
        schedule_changes = [e for e in events if e.kind != "reset"]
        if not schedule_changes:
            events.append(
                RaidEvent(kind="issue", notice=notice, evidence=title[:200], season=notice_season, boss_ko=title_boss)
            )
    # A reschedule without a window is a heading whose window never came.
    return [e for e in events if not (e.kind in OPENERS and e.start is None)]


def _operational(line: str, notice: Notice, season: int | None, boss: str) -> list[RaidEvent]:
    """Suspensions, reopenings, extensions, postponements and resets in a lounge notice."""
    published = notice.published_at
    title = notice.title
    field = FIELD_RE.match(line)
    label, value = (field.group("label"), field.group("value")) if field else ("", "")
    has_label = field is not None
    line_season = _season_of(line) or season
    boss = _boss_inline(line) or boss
    out: list[RaidEvent] = []

    def event(kind: str, start: Stamp | None = None, end: Stamp | None = None) -> RaidEvent:
        return RaidEvent(kind=kind, notice=notice, evidence=line[:200], season=line_season, start=start, end=end, boss_ko=boss)

    if "기록" in line and "초기화" in line:
        out.append(event("reset"))

    spans = find_spans(line, published)
    if "연장" in (label if has_label else line) and "모집" not in line:
        if spans and spans[0].end is not None:
            out.append(event("extend", spans[0].start, spans[0].end))
        else:
            until = find_until(line, published)
            if until is not None:
                out.append(event("extend", None, until))
        return out

    reopen_field = has_label and "재오픈" in label
    reopen_notice_window = has_label and "재오픈" in title and re.search(r"(?:진행|오픈)\s*(?:기간|시간)", label)
    if (reopen_field or reopen_notice_window) and spans and spans[0].end is not None:
        out.append(event("reopen", spans[0].start, spans[0].end))
        return out

    if "연기" in line and RAID_RE.search(line) and re.search(r"연기(?:될|됩니다|되었습니다|합니다)", line):
        out.append(event("postpone"))
        return out

    if "연결이 중단" in line:
        return out
    suspend_line = any(word in line for word in SUSPEND_WORDS) or (
        has_label and label.strip() == "일시" and "중단" in title
    )
    if suspend_line:
        if spans:
            out.append(event("suspend", spans[0].start, spans[0].end))
        else:
            points = find_points(value if has_label else line, published)
            if points:
                out.append(event("suspend", points[0], None))
    return out


def _drop_vague_suspensions(events: list[RaidEvent]) -> list[RaidEvent]:
    """A date-only "일시" field repeats a suspension stated to the minute elsewhere."""
    timed_days = {e.start.at.date() for e in events if e.kind == "suspend" and e.start and e.start.has_time}
    return [
        e for e in events
        if not (e.kind == "suspend" and e.start and not e.start.has_time and e.start.at.date() in timed_days)
    ]


# --------------------------------------------------------------------------
# 2. seasons
# --------------------------------------------------------------------------

def _joins(event: RaidEvent, season: Season, disruptions: list[RaidEvent]) -> bool:
    explicit = season.explicit
    if event.season is not None and explicit:
        return event.season in explicit
    if event.kind in ("reopen", "reschedule"):
        return True
    if event.start.at < season.last_end:
        return True
    if event.start.at - season.last_end > REOPEN_GAP:
        return False
    window_start = season.first_start - timedelta(days=1)
    return any(window_start <= d.effect_time <= event.start.at for d in disruptions)


def group_seasons(events: list[RaidEvent]) -> list[Season]:
    openings = sorted(
        (e for e in events if e.kind in OPENERS and e.start is not None),
        key=lambda e: (e.start.at, e.notice.published_at),
    )
    disruptions = [e for e in events if e.kind in ("suspend", "postpone")]
    seasons: list[Season] = []
    for event in openings:
        if seasons and _joins(event, seasons[-1], disruptions):
            seasons[-1].events.append(event)
        else:
            seasons.append(Season(events=[event]))

    for event in events:
        if event.kind in OPENERS:
            continue
        target = _season_for(event, seasons)
        if target is not None:
            target.events.append(event)
    return seasons


def _season_for(event: RaidEvent, seasons: list[Season]) -> Season | None:
    if event.season is not None:
        for season in seasons:
            if event.season in season.explicit:
                return season
    moment = event.effect_time
    containing = [
        s for s in seasons if s.first_start - EVENT_SLACK <= moment <= s.last_end + EVENT_SLACK
    ]
    if containing:
        return max(containing, key=lambda s: s.first_start if s.first_start <= moment else datetime.min.replace(tzinfo=moment.tzinfo))
    if event.boss_ko:
        # A result notice a week after the close names the boss, not the dates.
        named = [
            s for s in seasons
            if s.first_start <= moment and any(e.boss_ko == event.boss_ko for e in s.events if e is not event)
        ]
        if named:
            return max(named, key=lambda s: s.first_start)
    return None


# --------------------------------------------------------------------------
# 3. periods
# --------------------------------------------------------------------------

def replay(events: Iterable[RaidEvent]) -> list[Period]:
    """The intervals a season was open, from its events in time order."""
    periods: list[Period] = []
    current: dict[str, Any] | None = None

    def close(end: Stamp | None, reason: str) -> None:
        periods.append(Period(current["start"], end, reason))

    events = list(events)
    # A postponement cancels the openings announced before it that had not
    # started yet; the new date arrives as an opening of its own.
    postponed = {
        id(o)
        for p in events if p.kind == "postpone"
        for o in events
        if o.kind in OPENERS and o.start is not None
        and o.notice.published_at <= p.notice.published_at < o.start.at <= p.notice.published_at + POSTPONE_REACH
    }
    # One suspension is often stated twice - in a sentence ("18:00에 일시
    # 중단됩니다") and in a field that also gives the resume time. Keep the
    # statement that says when it resumes.
    suspensions: dict[datetime, RaidEvent] = {}
    for event in events:
        if event.kind == "suspend" and event.start is not None:
            kept = suspensions.get(event.start.at)
            if kept is None or (kept.end is None and event.end is not None):
                suspensions[event.start.at] = event
    order = {"open": 0, "reopen": 0, "reschedule": 0, "extend": 1, "suspend": 2}
    timeline = sorted(
        (
            e for e in events
            if e.kind in order and id(e) not in postponed
            and (e.kind != "suspend" or suspensions.get(e.start.at if e.start else None) is e)
        ),
        key=lambda e: (e.effect_time, order[e.kind], e.notice.published_at),
    )
    for event in timeline:
        if event.kind in OPENERS:
            if current is not None and abs(event.start.at - current["start"].at) <= timedelta(days=1):
                # The same window stated again, or corrected before it opened.
                start = event.start if event.start.has_time or not current["start"].has_time else current["start"]
                current = {"start": start, "end": event.end or current["end"], "reason": current["reason"]}
                continue
            if current is not None:
                if current["end"] is not None and event.start.at < current["end"].at:
                    close(event.start, "superseded")
                else:
                    close(current["end"], current["reason"])
            current = {"start": event.start, "end": event.end, "reason": "scheduled"}
        elif event.kind == "extend":
            if current is not None and event.end is not None:
                current["end"], current["reason"] = event.end, "extended"
            elif current is None and event.start is not None and event.end is not None:
                current = {"start": event.start, "end": event.end, "reason": "extended"}
        elif event.kind == "suspend":
            if current is None or event.start is None:
                continue
            at = event.start.at
            if current["end"] is not None and at >= current["end"].at:
                continue
            if at <= current["start"].at:
                # Stopped before it began: a postponement in all but name.
                if event.end is not None and (current["end"] is None or event.end.at < current["end"].at):
                    current["start"] = event.end
                else:
                    current = None
                continue
            close(event.start, "suspended")
            if event.end is not None and (current["end"] is None or event.end.at < current["end"].at):
                current = {"start": event.end, "end": current["end"], "reason": current["reason"]}
            else:
                current = None
    if current is not None:
        close(current["end"], current["reason"])
    return periods


# --------------------------------------------------------------------------
# numbering and checks
# --------------------------------------------------------------------------

def number_seasons(seasons: list[Season], enikk: dict[int, EnikkSeason]) -> list[str]:
    """Give every season its number; returns problems found on the way."""
    problems: list[str] = []
    observed = {
        n: datetime.fromisoformat(s.observed_last) for n, s in enikk.items() if s.observed_last
    }
    for season in seasons:
        explicit = season.explicit
        if len(explicit) == 1:
            season.number, season.number_source = next(iter(explicit)), "notice"
        elif len(explicit) > 1:
            problems.append(f"one season carries several numbers {sorted(explicit)}")
            season.number, season.number_source = min(explicit), "notice"
        if not season.periods:
            continue
        first = season.periods[0].start.at
        last = max((p.end.at for p in season.periods if p.end), default=first)
        matches = [n for n, t in observed.items() if first <= t <= last + ENIKK_LAG]
        if season.number is None and len(matches) == 1:
            season.number, season.number_source = matches[0], "enikk"
        elif season.number is not None and matches and season.number not in matches:
            problems.append(f"season {season.number}: enikk collected season(s) {matches} in its window")

    # Whatever is left is counted from numbered neighbours.
    for i, season in enumerate(seasons):
        if season.number is not None:
            continue
        before = next((s.number - (i - j) for j, s in reversed(list(enumerate(seasons[:i]))) if s.number is not None), None)
        after = next((s.number - (j - i) for j, s in enumerate(seasons[i + 1:], start=i + 1) if s.number is not None), None)
        guess = before if before is not None else after
        if before is not None and after is not None and before != after:
            problems.append(f"cannot number the season opening {season.first_start.date()}: neighbours disagree")
            continue
        if guess is not None and guess > 0:
            season.number, season.number_source = guess, "sequence"

    numbers = [s.number for s in seasons if s.number is not None]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        problems.append(f"season numbers claimed twice: {duplicates}")
    if numbers != sorted(numbers):
        problems.append("season numbers are not in time order")
    return problems


def season_checks(season: Season | None, meta: EnikkSeason | None) -> list[str]:
    checks: list[str] = []
    if season is None:
        checks.append("no_notice")
        return checks
    if meta is None or (not meta.boss_element and not meta.observed_last):
        checks.append("no_enikk")
    elif not meta.boss_en:
        checks.append("boss_unnamed")
    notice_element = next((e.element for e in season.events if e.element), "")
    notice_weak = next((e.weak_element for e in season.events if e.weak_element), "")
    if meta is not None and notice_element and meta.boss_element and notice_element != meta.boss_element:
        checks.append(f"element_mismatch:notice={notice_element},enikk={meta.boss_element}")
    if meta is not None and notice_weak and meta.weak_element and notice_weak != meta.weak_element:
        checks.append(f"weakness_mismatch:notice={notice_weak},enikk={meta.weak_element}")
    if meta is not None and meta.observed_last and season.periods:
        first = datetime.fromisoformat(meta.observed_first)
        last = datetime.fromisoformat(meta.observed_last)
        start = season.periods[0].start.at
        ends = [p.end.at for p in season.periods if p.end]
        if ends and last > max(ends) + ENIKK_LAG:
            checks.append("enikk_after_periods")
        if first < start - timedelta(days=1):
            checks.append("enikk_before_periods")
        if not any(p.start.at - timedelta(days=1) <= last and (p.end is None or last <= p.end.at + ENIKK_LAG) for p in season.periods):
            checks.append("enikk_outside_periods")
    return checks


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def extract_all(notices: Iterable[Notice]) -> list[RaidEvent]:
    unique: dict[tuple[Any, ...], RaidEvent] = {}
    for notice in notices:
        for event in extract_events(notice):
            unique.setdefault(event.key() + ((event.notice.notice_id,) if event.kind in ("issue", "reset", "postpone") else ()), event)
    return sorted(unique.values(), key=lambda e: (e.effect_time, e.notice.published_at))


def _iso(stamp: Stamp | None) -> str:
    return stamp.iso() if stamp else ""


def build(
    notices: list[Notice],
    enikk: dict[int, EnikkSeason],
    *,
    releases: dict[str, str] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Write the season tables. ``releases`` maps unit id -> release instant (ISO)."""
    events = extract_all(notices)
    seasons = group_seasons(events)
    for season in seasons:
        season.periods = replay(season.events)
    problems = number_seasons(seasons, enikk)

    by_number = {s.number: s for s in seasons if s.number is not None}
    numbers = sorted(set(by_number) | {n for n, m in enikk.items() if m.boss_en or m.boss_element or m.observed_last})
    release_times = sorted(
        (datetime.fromisoformat(at), unit) for unit, at in (releases or {}).items() if at
    )

    target = out_dir or processed_dir()
    target.mkdir(parents=True, exist_ok=True)
    season_rows, period_rows, calendar_rows = [], [], []
    # "New" for the first season means new since the game launched.
    previous_end: datetime = datetime.fromisoformat(f"{LAUNCH_DATE}T00:00:00+09:00")
    for number in numbers:
        season = by_number.get(number)
        meta = enikk.get(number)
        checks = season_checks(season, meta)
        row: dict[str, Any] = {
            "season": number,
            "boss_en": meta.boss_en if meta else "",
            "boss_ko": "",
            "element": meta.boss_element if meta else "",
            "weak_element": meta.weak_element if meta else "",
            "scheduled_start": "",
            "scheduled_end": "",
            "start_at": "",
            "end_at": "",
            "periods": 0,
            "disrupted": 0,
            "record_reset": 0,
            "numbered_by": "",
            "enikk_first_seen": meta.observed_first if meta else "",
            "enikk_last_seen": meta.observed_last if meta else "",
            "enikk_collections": meta.collections if meta else 0,
            "units_available": "",
            "new_units": "",
            "checks": ";".join(checks),
            "notice_ids": "",
        }
        if season is not None:
            original = min(season.openings, key=lambda e: (e.notice.published_at, e.start.at))
            row.update(
                boss_ko=next((e.boss_ko for e in season.events if e.boss_ko), ""),
                scheduled_start=_iso(original.start),
                scheduled_end=_iso(original.end),
                periods=len(season.periods),
                disrupted=int(len(season.periods) > 1 or any(e.kind in ("suspend", "postpone") for e in season.events)),
                record_reset=int(any(e.kind == "reset" for e in season.events)),
                numbered_by=season.number_source,
                notice_ids=";".join(sorted({e.notice.notice_id for e in season.events})),
            )
            if not row["element"]:
                row["element"] = next((e.element for e in season.events if e.element), "")
                row["weak_element"] = next((e.weak_element for e in season.events if e.weak_element), "")
            if season.periods:
                start = season.periods[0].start
                end = season.periods[-1].end
                row["start_at"], row["end_at"] = _iso(start), _iso(end)
                calendar_rows.append(
                    {"season": number, "start_date": start.at.date().isoformat(), "end_date": end.at.date().isoformat() if end else ""}
                )
                if end is not None and release_times:
                    available = [u for t, u in release_times if t <= end.at]
                    fresh = [u for t, u in release_times if previous_end < t <= end.at]
                    row["units_available"] = len(available)
                    row["new_units"] = ";".join(fresh)
                    previous_end = end.at
            for index, period in enumerate(season.periods, start=1):
                period_rows.append(
                    {
                        "season": number,
                        "period": index,
                        "start_at": _iso(period.start),
                        "end_at": _iso(period.end),
                        "start_after_maintenance": int(period.start.after_maintenance),
                        "end_reason": period.end_reason,
                    }
                )
        season_rows.append(row)

    event_rows = []
    number_of = {id(e): s.number for s in seasons for e in s.events}
    for event in events:
        event_rows.append(
            {
                "season": number_of.get(id(event), ""),
                "kind": event.kind,
                "start_at": _iso(event.start),
                "end_at": _iso(event.end),
                "stated_season": event.season if event.season is not None else "",
                "element": event.element,
                "weak_element": event.weak_element,
                "boss_ko": event.boss_ko,
                "notice_id": event.notice.notice_id,
                "notice_published_at": event.notice.published_at.isoformat(),
                "notice_title": event.notice.title,
                "evidence": event.evidence,
            }
        )

    _write(target / SEASONS_CSV, season_rows)
    _write(target / PERIODS_CSV, period_rows)
    _write(target / EVENTS_CSV, event_rows)
    _write(target / CALENDAR_CSV, calendar_rows, fields=["season", "start_date", "end_date"])
    unassigned = sum(1 for e in events if id(e) not in number_of)
    return {
        "events": len(events),
        "seasons": len(season_rows),
        "from_notices": len(by_number),
        "disrupted": [r["season"] for r in season_rows if r["disrupted"]],
        "with_checks": {r["season"]: r["checks"] for r in season_rows if r["checks"]},
        "unassigned_events": unassigned,
        "problems": problems,
    }


def _write(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        names = fields or (list(rows[0].keys()) if rows else [])
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
