"""What the game looked like at a given moment.

    from nikke_analysis.timeline import Timeline

    timeline = Timeline.load()
    view = timeline.at("2024-11-04")          # the 2nd anniversary, noon KST
    view.season.number, view.season.status_at(view.moment)   # 19, "suspended"
    len(view.units)                            # every unit that existed then
    timeline.season(19).periods                # when season 19 was actually open

Everything here reads the processed tables (roster.csv, banners.csv,
unit_releases.csv, soloraid_seasons.csv, soloraid_periods.csv, notices.csv), so a
question about the past is answered from committed data, offline, the same way
every time. Times are KST, as the notices state them; a bare date means noon,
after the morning maintenance and the usual 12:00 openings.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from .paths import processed_dir
from .util.kdate import KST, parse_moment
from .util.names import TREASURE_MARK, treasure_id
from .util.text import pad as _pad

LAUNCH = date(2022, 11, 4)

ELEMENT_KO = {"Fire": "작열", "Water": "수냉", "Wind": "풍압", "Iron": "철갑", "Electric": "전격"}
RARITY_ORDER = ("SSR", "SR", "R")


def parse_element(text: Any) -> str:
    """An element from its Korean or English name, in any case: ``작열``, ``fire`` -> ``Fire``."""
    key = str(text).strip().lower()
    for element, korean in ELEMENT_KO.items():
        if key in (element.lower(), korean):
            return element
    options = ", ".join(f"{korean}({element})" for element, korean in ELEMENT_KO.items())
    raise LookupError(f"'{text}' 은(는) 속성 이름이 아니다: {options}")


@dataclass(frozen=True)
class Unit:
    unit_id: str
    name_ko: str
    name_en: str
    rarity: str
    element: str
    burst: str
    unit_class: str
    manufacturer: str
    weapon: str
    available_from: datetime
    release_source: str
    confidence: str
    available_until: datetime | None = None  # its treasure came out: it left the pool for the unit it became
    treasure_of: str = ""  # a unit with its treasure (``221♥``): the base it came from

    @property
    def name(self) -> str:
        return self.name_ko or self.name_en or self.unit_id

    def available_at(self, moment: datetime) -> bool:
        return self.available_from <= moment and (self.available_until is None or moment < self.available_until)


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime | None
    end_reason: str
    start_after_maintenance: bool = False

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment and (self.end is None or moment <= self.end)


@dataclass(frozen=True)
class Season:
    number: int
    boss_en: str
    boss_ko: str
    element: str
    weak_element: str
    periods: tuple[Period, ...]
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    disrupted: bool
    record_reset: bool
    checks: tuple[str, ...]

    @property
    def boss(self) -> str:
        if self.boss_ko and self.boss_en:
            return f"{self.boss_ko} ({self.boss_en})"
        return self.boss_ko or self.boss_en or "?"

    @property
    def start(self) -> datetime | None:
        return self.periods[0].start if self.periods else None

    @property
    def end(self) -> datetime | None:
        return self.periods[-1].end if self.periods else None

    def status_at(self, moment: datetime) -> str:
        """``unscheduled`` (no notice yet), ``upcoming``, ``open``, ``suspended`` or ``closed``."""
        if not self.periods:
            return "unscheduled"
        if moment < self.periods[0].start:
            return "upcoming"
        if any(p.contains(moment) for p in self.periods):
            return "open"
        end = self.periods[-1].end
        if end is not None and moment > end:
            return "closed"
        return "suspended"


@dataclass(frozen=True)
class Banner:
    unit_id: str
    kind: str
    debut: bool
    start: datetime
    end: datetime | None
    notice_title: str

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment and (self.end is None or moment <= self.end)


@dataclass
class Snapshot:
    moment: datetime
    units: list[Unit]
    announced_units: list[Unit]
    season: Season | None
    previous_season: Season | None
    next_season: Season | None
    banners: list[Banner]
    latest_update: dict[str, str] | None
    unit_names: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def days_since_launch(self) -> int:
        return (self.moment.date() - LAUNCH).days

    def released_within(self, days: int) -> list[Unit]:
        """New units in the last ``days`` - not the ones a treasure made (``treasured_within``)."""
        cutoff = self.moment - timedelta(days=days)
        return [u for u in self.units if u.available_from > cutoff and not u.treasure_of]

    def treasured_within(self, days: int) -> list[Unit]:
        """Units whose treasure came out in the last ``days``, as the units they became."""
        cutoff = self.moment - timedelta(days=days)
        return [u for u in self.units if u.available_from > cutoff and u.treasure_of]

    def count_by(self, attribute: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for unit in self.units:
            key = getattr(unit, attribute) or "?"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        def season(s: Season | None) -> dict[str, Any] | None:
            if s is None:
                return None
            return {
                "season": s.number,
                "status": s.status_at(self.moment),
                "boss_en": s.boss_en,
                "boss_ko": s.boss_ko,
                "element": s.element,
                "weak_element": s.weak_element,
                "periods": [
                    {"start": p.start.isoformat(), "end": p.end.isoformat() if p.end else None, "end_reason": p.end_reason}
                    for p in s.periods
                ],
                "disrupted": s.disrupted,
                "record_reset": s.record_reset,
                "checks": list(s.checks),
            }

        def unit(u: Unit) -> dict[str, Any]:
            return {
                "unit_id": u.unit_id,
                "name_ko": u.name_ko,
                "name_en": u.name_en,
                "rarity": u.rarity,
                "element": u.element,
                "burst": u.burst,
                "class": u.unit_class,
                "available_from": u.available_from.isoformat(),
                "release_source": u.release_source,
                "treasure_of": u.treasure_of or None,
            }

        return {
            "moment": self.moment.isoformat(),
            "days_since_launch": self.days_since_launch,
            "soloraid": {
                "current": season(self.season),
                "previous": season(self.previous_season),
                "next": season(self.next_season),
            },
            "units": {
                "count": len(self.units),
                "by_rarity": self.count_by("rarity"),
                "by_element": self.count_by("element"),
                "released_last_30_days": [unit(u) for u in self.released_within(30)],
                "treasures_last_30_days": [unit(u) for u in self.treasured_within(30)],
                "announced_not_released": [unit(u) for u in self.announced_units],
                "all": [unit(u) for u in self.units],
            },
            "banners": [
                {
                    "unit_id": b.unit_id,
                    "name": self.unit_names.get(b.unit_id, b.unit_id),
                    "kind": b.kind,
                    "debut": b.debut,
                    "start": b.start.isoformat(),
                    "end": b.end.isoformat() if b.end else None,
                }
                for b in self.banners
            ],
            "latest_update": self.latest_update,
        }


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _instant(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _unit_from(row: dict[str, str]) -> Unit | None:
    if row.get("release_at"):
        available = datetime.fromisoformat(row["release_at"])
    elif row.get("release_date"):
        available = datetime.combine(date.fromisoformat(row["release_date"]), time(0, 0), KST)
    else:
        return None
    return Unit(
        unit_id=row["unit_id"],
        name_ko=row.get("name_ko", ""),
        name_en=row.get("name_en", ""),
        rarity=row.get("rarity", ""),
        element=row.get("element", ""),
        burst=row.get("burst", ""),
        unit_class=row.get("unit_class", ""),
        manufacturer=row.get("manufacturer", ""),
        weapon=row.get("weapon", ""),
        available_from=available,
        release_source=row.get("release_date_source", ""),
        confidence=row.get("release_date_confidence", ""),
        available_until=_instant(row.get("treasure_at", "")),
        treasure_of=row.get("treasure_of", ""),
    )


class Timeline:
    def __init__(
        self,
        units: Iterable[Unit],
        seasons: Iterable[Season],
        banners: Iterable[Banner] = (),
        notices: Iterable[dict[str, str]] = (),
        announced: dict[str, datetime] | None = None,
    ):
        self.units = sorted(units, key=lambda u: (u.available_from, u.unit_id))
        self._seasons = {s.number: s for s in seasons}
        self.banners = sorted(banners, key=lambda b: (b.start, b.unit_id))
        self.update_notices = sorted(
            (n for n in notices if n.get("kind") == "update"), key=lambda n: n["published_at"]
        )
        self.announced = announced or {}

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Timeline":
        directory = data_dir or processed_dir()
        roster = _rows(directory / "roster.csv")
        if not roster:
            raise RuntimeError("roster.csv is missing; run `nikke build timeline` first")
        units = [u for u in (_unit_from(row) for row in roster) if u is not None]

        periods: dict[int, list[Period]] = {}
        for row in _rows(directory / "soloraid_periods.csv"):
            periods.setdefault(int(row["season"]), []).append(
                Period(
                    start=datetime.fromisoformat(row["start_at"]),
                    end=_instant(row["end_at"]),
                    end_reason=row["end_reason"],
                    start_after_maintenance=row.get("start_after_maintenance") == "1",
                )
            )
        seasons = [
            Season(
                number=int(row["season"]),
                boss_en=row["boss_en"],
                boss_ko=row["boss_ko"],
                element=row["element"],
                weak_element=row["weak_element"],
                periods=tuple(sorted(periods.get(int(row["season"]), []), key=lambda p: p.start)),
                scheduled_start=_instant(row["scheduled_start"]),
                scheduled_end=_instant(row["scheduled_end"]),
                disrupted=row["disrupted"] == "1",
                record_reset=row["record_reset"] == "1",
                checks=tuple(c for c in row["checks"].split(";") if c),
            )
            for row in _rows(directory / "soloraid_seasons.csv")
        ]
        banners = [
            Banner(
                unit_id=row["unit_id"],
                kind=row["kind"],
                debut=row["debut"] == "1",
                start=datetime.fromisoformat(row["start_at"]),
                end=_instant(row["end_at"]),
                notice_title=row["notice_title"],
            )
            for row in _rows(directory / "banners.csv")
            if row.get("kind") != "introduced"
        ]
        announced = {
            row["unit_id"]: datetime.fromisoformat(row["notice_published_at"])
            for row in _rows(directory / "unit_releases.csv")
            if row.get("notice_published_at")
        }
        announced.update(
            (treasure_id(row["unit_id"]), datetime.fromisoformat(row["notice_published_at"]))
            for row in _rows(directory / "treasures.csv")
            if row.get("unit_id") and row.get("notice_published_at")
        )
        return cls(units, seasons, banners, _rows(directory / "notices.csv"), announced)

    # ----------------------------------------------------------------------

    def seasons(self) -> list[Season]:
        return [self._seasons[n] for n in sorted(self._seasons)]

    def season(self, number: int) -> Season | None:
        return self._seasons.get(number)

    def units_at(self, moment: datetime | str) -> list[Unit]:
        """The pool at ``moment``: released by then, and - for a unit whose treasure
        came out - the unit it became in its place."""
        moment = resolve_moment(moment)
        return [u for u in self.units if u.available_at(moment)]

    def at(self, moment: datetime | str) -> Snapshot:
        moment = resolve_moment(moment)
        units = self.units_at(moment)
        announced = [
            u for u in self.units
            if u.available_from > moment and self.announced.get(u.unit_id) is not None
            and self.announced[u.unit_id] <= moment
        ]

        scheduled = [s for s in self.seasons() if s.periods]
        current = next((s for s in scheduled if s.status_at(moment) in ("open", "suspended")), None)
        closed = [s for s in scheduled if s.status_at(moment) == "closed"]
        upcoming = [s for s in scheduled if s.status_at(moment) == "upcoming"]
        if not upcoming:
            # A season enikk already knows about but no notice has scheduled yet.
            after = [s for s in self.seasons() if not s.periods and (not closed or s.number > closed[-1].number)]
            upcoming = after[:1]

        latest = next((n for n in reversed(self.update_notices) if datetime.fromisoformat(n["published_at"]) <= moment), None)
        names = {u.unit_id: u.name for u in self.units}
        return Snapshot(
            moment=moment,
            units=units,
            announced_units=announced,
            season=current,
            previous_season=closed[-1] if closed else None,
            next_season=upcoming[0] if upcoming else None,
            banners=[b for b in self.banners if b.contains(moment)],
            latest_update=(
                {"title": latest["title"], "published_at": latest["published_at"], "url": latest["url"]} if latest else None
            ),
            unit_names=names,
        )


_ANNIVERSARY_RE = re.compile(r"^(\d{1,2})\s*주년$")


def resolve_moment(value: datetime | str) -> datetime:
    """A datetime, an ISO date/time, or "2주년" (the Nth launch anniversary, noon KST)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=KST)
    text = value.strip()
    anniversary = _ANNIVERSARY_RE.match(text)
    if anniversary:
        day = LAUNCH.replace(year=LAUNCH.year + int(anniversary.group(1)))
        return datetime.combine(day, time(12, 0), KST)
    return parse_moment(text)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

STATUS_KO = {
    "open": "진행 중",
    "suspended": "일시 중단 중",
    "upcoming": "오픈 예정",
    "closed": "종료",
    "unscheduled": "일정 미공지",
}
END_REASON_KO = {
    "scheduled": "",
    "suspended": " (중단)",
    "extended": " (연장)",
    "superseded": " (일정 변경)",
}


def _hm(moment: datetime | None, *, year: bool = False) -> str:
    if moment is None:
        return "추후 안내"
    return moment.strftime("%Y-%m-%d %H:%M" if year else "%m/%d %H:%M")


def _element(value: str) -> str:
    return f"{ELEMENT_KO.get(value, value)}({value})" if value else "?"


def _season_line(season: Season, moment: datetime, label: str) -> list[str]:
    status = STATUS_KO[season.status_at(moment)]
    head = (
        f"  {label} 시즌 {season.number} · {season.boss} · "
        f"보스 {_element(season.element)} / 약점 {_element(season.weak_element)} · {status}"
    )
    lines = [head]
    for index, period in enumerate(season.periods):
        prefix = "    운영 구간  " if index == 0 else "               "
        start = _hm(period.start, year=index == 0)
        if period.start_after_maintenance:
            start = start.split(" ")[0] + " 점검 후"
        lines.append(f"{prefix}{start} ~ {_hm(period.end)}{END_REASON_KO.get(period.end_reason, '')}")
    if season.scheduled_start and season.periods and (
        season.scheduled_start != season.start or season.scheduled_end != season.end
    ):
        lines.append(
            f"    처음 공지된 일정  {_hm(season.scheduled_start, year=True)} ~ {_hm(season.scheduled_end)} (이후 변경)"
        )
    notes = []
    if season.record_reset:
        notes.append("챌린지 기록 초기화 있음")
    # A season no notice has scheduled yet is not a problem, just not announced.
    checks = [c for c in season.checks if not (c == "no_notice" and not season.periods)]
    if checks:
        notes.append("확인 필요: " + ", ".join(checks))
    if notes:
        lines.append("    " + " · ".join(notes))
    return lines


def render(view: Snapshot, *, list_units: bool = False) -> str:
    out = [
        f"{view.moment.strftime('%Y-%m-%d %H:%M')} KST 기준 · 글로벌 출시 {view.days_since_launch:+d}일",
        "",
        "솔로 레이드",
    ]
    weak = ""
    if view.season is not None:
        out += _season_line(view.season, view.moment, "현재")
        weak = view.season.weak_element
    else:
        out.append("  현재 진행 중인 시즌 없음")
    if view.previous_season is not None:
        out += _season_line(view.previous_season, view.moment, "직전")
    if view.next_season is not None:
        out += _season_line(view.next_season, view.moment, "다음")
        weak = weak or view.next_season.weak_element

    rarity = view.count_by("rarity")
    rarity_text = " · ".join(f"{r} {rarity[r]}" for r in RARITY_ORDER if r in rarity)
    out += ["", f"니케 풀  {len(view.units)}명 ({rarity_text})"]
    by_element = view.count_by("element")
    element_text = " · ".join(
        f"{'▶' if e == weak else ''}{ELEMENT_KO.get(e, e)} {by_element.get(e, 0)}" for e in ELEMENT_KO
    )
    out.append(f"  속성별  {element_text}" + ("   (▶ = 솔로 레이드 약점 속성)" if weak else ""))
    recent = view.released_within(30)
    if recent:
        out.append("  최근 30일 출시  " + " · ".join(f"{u.name} ({u.available_from:%m/%d})" for u in recent))
    treasured = view.treasured_within(30)
    if treasured:
        out.append("  최근 30일 애장품  " + " · ".join(f"{u.name} ({u.available_from:%m/%d})" for u in treasured))
    if view.announced_units:
        out.append(
            "  공지됐지만 미출시  " + " · ".join(f"{u.name} ({u.available_from:%m/%d %H:%M})" for u in view.announced_units)
        )
    if any(u.treasure_of for u in view.units + view.announced_units):
        out.append(f"  {TREASURE_MARK} = 애장품을 받은 니케. 애장품이 나온 뒤로는 원래 니케 대신 다른 니케로 센다")
    low = [u for u in view.units if u.confidence == "low"]
    if low:
        out.append(f"  출시일 신뢰도 낮음 {len(low)}명: " + " · ".join(u.name for u in low))

    if view.banners:
        out += ["", "진행 중 모집"]
        kinds = {"special": "특수 모집", "limited": "기간 한정", "limited_selection": "한정 선택", "collab": "콜라보",
                 "event_reward": "이벤트 획득", "recruit": "모집"}
        for banner in view.banners:
            name = view.unit_names.get(banner.unit_id, banner.unit_id)
            tag = "[신규]" if banner.debut else "[재모집]"
            out.append(
                f"  {_pad(kinds.get(banner.kind, banner.kind), 11)} {_pad(name, 26)} {_pad(tag, 9)} {_hm(banner.start)} ~ {_hm(banner.end)}"
            )

    if view.latest_update:
        out += ["", f"최근 업데이트 공지  {view.latest_update['title']} ({view.latest_update['published_at'][:10]} 공개)"]

    if list_units:
        out += ["", "보유 가능 니케 전체 (출시 순)"]
        for unit in view.units:
            out.append(
                f"  {unit.available_from:%Y-%m-%d}  {unit.unit_id}  {_pad(unit.name, 28)} {unit.rarity:<3} "
                f"{ELEMENT_KO.get(unit.element, unit.element)} {unit.burst:<8} {unit.unit_class}"
            )
    return "\n".join(out)


def render_seasons(timeline: Timeline) -> str:
    out = [f"{'시즌':>4}  {_pad('보스', 36)}  {_pad('속성/약점', 10)}  {_pad('기간', 25)}  비고"]
    for season in timeline.seasons():
        span = (
            f"{_hm(season.start, year=True)[:10]} ~ {_hm(season.end, year=True)[:10]}"
            if season.periods else "일정 미공지"
        )
        flags = []
        if len(season.periods) > 1:
            flags.append(f"{len(season.periods)}구간")
        if season.disrupted:
            flags.append("중단/연기")
        if season.record_reset:
            flags.append("기록 초기화")
        flags += list(season.checks)
        elements = f"{ELEMENT_KO.get(season.element, season.element)}/{ELEMENT_KO.get(season.weak_element, season.weak_element)}"
        out.append(f"{season.number:>4}  {_pad(season.boss, 36)}  {_pad(elements, 10)}  {_pad(span, 25)}  {', '.join(flags)}")
    return "\n".join(out)
