"""Dates and times as Korean notices write them.

Every schedule in this project comes out of prose like

    2026년 9월 24일 12:00:00 ~ 2026년 10월 1일 4:59:59 (UTC+9)
    2022년 11월 10일(목) 서버 점검 종료 이후 ~ 2022년 11월 24일(목) 4:59:59
    6/24(화) 점검 완료 후 ~ 7/1(화) 4:59
    8/26일(화) 17:00 ~ 21:00
    11/17(일) 5:00까지
    6월 20일(금) 00:00 ~ 추후 안내

so this module turns those into timezone-aware datetimes in KST (the notices
say "UTC+9" and mean it). It is deliberately strict about shape and lenient
about spacing and full-width punctuation, because the notices are typed by hand.

Two things a notice leaves open are recorded rather than guessed:

* ``after_maintenance`` - "서버 점검 종료 이후" gives a day, not a time. The
  stamp is that day at 00:00 with the flag set, so it sorts correctly and
  compares correctly at day resolution, and nothing pretends to know the hour.
* the year - "6/24(화)" has none. It is taken from the notice's publication
  date: whichever year puts the date closest to when the notice was written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")

_WEEKDAY = r"(?:\s*[(（]\s*[월화수목금토일]\s*[)）])?"
_TIME = r"(?:\s*(?P<{p}H>\d{{1,2}})\s*[:：]\s*(?P<{p}M>\d{{2}})(?:\s*[:：]\s*(?P<{p}S>\d{{2}}))?)?"
_MAINT = (
    r"(?P<{p}maint>\s*(?:서버\s*)?(?:점검|업데이트)\s*(?:종료|완료)?\s*(?:이후|후)"
    r"|\s*서버\s*오픈\s*(?:이후|후))?"
)


def _date_pattern(prefix: str) -> str:
    """One date, optionally with a year, weekday, time or maintenance anchor.

    A dotted or dashed date needs its year (``2026.9.3``); without one only
    ``9월 3일`` and ``9/3`` count, so section numbers like ``1.1`` never parse
    as the first of January.
    """
    p = prefix
    return (
        rf"(?:(?P<{p}y>20\d{{2}})\s*(?:년\s*(?P<{p}m1>\d{{1,2}})\s*월\s*(?P<{p}d1>\d{{1,2}})\s*일?"
        rf"|[./-]\s*(?P<{p}m2>\d{{1,2}})\s*[./-]\s*(?P<{p}d2>\d{{1,2}})\s*일?)"
        rf"|(?P<{p}m3>\d{{1,2}})\s*(?:월\s*(?P<{p}d3>\d{{1,2}})\s*일|/\s*(?P<{p}d4>\d{{1,2}})\s*일?))"
        + _WEEKDAY
        + _TIME.format(p=p)
        + _MAINT.format(p=p)
    )


_POINT_RE = re.compile(_date_pattern("a"))
_RANGE_RE = re.compile(
    _date_pattern("a")
    + r"\s*(?:\(UTC\+9\)|（UTC\+9）)?\s*[~～〜]\s*"
    + r"(?:(?P<open_end>추후\s*(?:안내|공지)|미정)|"
    + r"(?:" + _date_pattern("b") + r")|"
    + r"(?P<tH>\d{1,2})\s*[:：]\s*(?P<tM>\d{2})(?:\s*[:：]\s*(?P<tS>\d{2}))?)"
)
_UNTIL_RE = re.compile(_date_pattern("a") + r"\s*까지")


@dataclass(frozen=True)
class Stamp:
    """A point in time read from a notice."""

    at: datetime
    after_maintenance: bool = False
    has_time: bool = True

    def iso(self) -> str:
        return self.at.isoformat()


@dataclass(frozen=True)
class Span:
    """``start ~ end`` as written. ``end`` is None for "추후 안내" (to be announced)."""

    start: Stamp
    end: Stamp | None


def _pick_year(month: int, day: int, reference: date) -> int:
    best_year, best_gap = reference.year, None
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            gap = abs((date(year, month, day) - reference).days)
        except ValueError:
            continue
        if best_gap is None or gap < best_gap:
            best_year, best_gap = year, gap
    return best_year


def _stamp(match: re.Match[str], prefix: str, reference: date, *, is_end: bool) -> Stamp | None:
    g = match.groupdict()
    month_text = g.get(f"{prefix}m1") or g.get(f"{prefix}m2") or g.get(f"{prefix}m3")
    day_text = g.get(f"{prefix}d1") or g.get(f"{prefix}d2") or g.get(f"{prefix}d3") or g.get(f"{prefix}d4")
    if not month_text or not day_text:
        return None
    month, day = int(month_text), int(day_text)
    year = int(g[f"{prefix}y"]) if g.get(f"{prefix}y") else _pick_year(month, day, reference)
    try:
        day_value = date(year, month, day)
    except ValueError:
        return None
    return _with_time(
        day_value,
        g.get(f"{prefix}H"),
        g.get(f"{prefix}M"),
        g.get(f"{prefix}S"),
        after_maintenance=bool(g.get(f"{prefix}maint")),
        is_end=is_end,
    )


def _with_time(
    day_value: date,
    hour: str | None,
    minute: str | None,
    second: str | None,
    *,
    after_maintenance: bool = False,
    is_end: bool,
) -> Stamp | None:
    if hour is None:
        # A bare end date means through that day; a bare start, from its start.
        clock = time(23, 59, 59) if is_end and not after_maintenance else time(0, 0)
        return Stamp(datetime.combine(day_value, clock, KST), after_maintenance, has_time=False)
    h, m = int(hour), int(minute or 0)
    # "4:59" as an end means through the end of that minute - the same instant
    # the precise notices spell as 4:59:59.
    s = int(second) if second is not None else (59 if is_end and m == 59 else 0)
    if h == 24 and m == 0:
        return Stamp(datetime.combine(day_value + timedelta(days=1), time(0, 0), KST), after_maintenance)
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    return Stamp(datetime.combine(day_value, time(h, m, s), KST), after_maintenance)


def find_spans(text: str, reference: date | datetime) -> list[Span]:
    """Every ``start ~ end`` in ``text``, in order of appearance."""
    ref = reference.date() if isinstance(reference, datetime) else reference
    spans: list[Span] = []
    for match in _RANGE_RE.finditer(text):
        start = _stamp(match, "a", ref, is_end=False)
        if start is None:
            continue
        end: Stamp | None
        if match.group("open_end"):
            end = None
        elif match.group("tH") is not None:
            # "17:00 ~ 21:00" - the end shares the start's day.
            end = _with_time(start.at.date(), match.group("tH"), match.group("tM"), match.group("tS"), is_end=True)
            if end is not None and end.at <= start.at:
                end = Stamp(end.at + timedelta(days=1), end.after_maintenance, end.has_time)
        else:
            end = _stamp(match, "b", start.at.date(), is_end=True)
            if end is not None and end.at < start.at:
                # A year-less end that rolled back over New Year.
                try:
                    end = Stamp(end.at.replace(year=end.at.year + 1), end.after_maintenance, end.has_time)
                except ValueError:
                    end = None
        if end is None and not match.group("open_end"):
            continue
        spans.append(Span(start, end))
    return spans


def find_points(text: str, reference: date | datetime) -> list[Stamp]:
    """Every standalone date in ``text`` (ranges included, as their start)."""
    ref = reference.date() if isinstance(reference, datetime) else reference
    out = []
    for match in _POINT_RE.finditer(text):
        stamp = _stamp(match, "a", ref, is_end=False)
        if stamp is not None:
            out.append(stamp)
    return out


def find_until(text: str, reference: date | datetime) -> Stamp | None:
    """The first "... 까지" (until) in ``text``."""
    ref = reference.date() if isinstance(reference, datetime) else reference
    match = _UNTIL_RE.search(text)
    return _stamp(match, "a", ref, is_end=True) if match else None


def parse_moment(value: str) -> datetime:
    """Parse a user-supplied moment: ``2024-11-04``, ``2024-11-04T15:00`` or a full ISO stamp.

    A bare date means noon KST - after the morning maintenance window and the
    usual 12:00 content openings, so "what was live on this day" answers with
    that day's content rather than the previous night's.
    """
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.combine(date.fromisoformat(text), time(12, 0), KST)
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


def to_kst(value: datetime) -> datetime:
    return value.astimezone(KST)


def from_iso(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
