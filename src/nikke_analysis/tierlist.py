"""Tiers at a moment, one element's tiers, and one unit's tier history.

    nikke tier                   now: the last finished season, the one in
                                 progress, and every unit's overall tier
    nikke tier 2주년             the same, as the data stood at the anniversary
    nikke tier --element 작열    the units of one element, by their tier in it
    nikke tier --unit 크라운     one unit: its two tiers, and season by season
    nikke tier --exclude NA      the same on another server sample (--server KR,JP
                                 keeps only those); works with the ones above

Every unit has two tiers: its **element tier** (how it does when the boss is
weak to its own element) and its **overall tier** (over the whole rotation);
see ``analyze.tiers``. The overall table compares every unit, the element
table the units of one element. The numbers are lift, shown as 기여도.

A unit whose treasure (애장품) was out at the moment of a view is tiered on the
seasons it played with it; before, on the seasons without. One unit's record is
still one line, the treasure marked (♥) where it came.

Reads the metric tables (``metrics_unit_season.csv``, ``metrics_seasons.csv``)
and the timeline, so it works offline from committed data. A view of the past
uses only what was known then: seasons that had ended by that moment, and the
season in progress only if its snapshot had been taken by then - it then
counts in the element and overall tiers too, provisionally.

The committed tables pool every server (config/tiers.yaml). Another sample is
computed from ``raid_entries.csv`` on first use (~10 s) and reused after that;
see ``analyze.pipeline.run_servers``.

    from nikke_analysis.tierlist import TierBook

    book = TierBook.load()
    view = book.at("2주년")
    view.overall.head()              # element tier and overall tier per unit
    view.element("Fire")             # the Fire units, best in Fire first
    book.unit("크라운").rows         # the unit's season-by-season record

    TierBook.load(servers=ServerFilter.of(exclude="NA"))   # every server but NA
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .analyze import tiers as tiering
from .analyze.metrics import ELEMENTS, listed_elements
from .paths import processed_dir
from .servers import ServerFilter, describe, ordered
from .timeline import ELEMENT_KO, Season, Timeline, resolve_moment
from .util.names import NameIndex, normalize_name, normalize_unit_id
from .util.text import pad, rjust

TREASURE_MARK = "♥"

OVERALL_KO = {"mean": "보스 약점 다섯 가지 성적의 평균", "frequency": "보스 약점 다섯 가지 성적을 자주 나온 약점일수록 크게 친 평균",
              "max": "보스 약점 다섯 가지 중 가장 잘한 것"}
LIFT_NOTE = ["  숫자 = 기여도. 랭커의 대미지를 덱에 든 니케끼리 나눠 가진 몫이다. 한 사람이 쓰는",
             "  25명(5덱 × 5명)이 똑같이 나누면 모두 1.0 — 1.5 = 그 1.5배, 0 = 아무도 안 씀"]
CLASS_KO = {"Attacker": "화력형", "Supporter": "지원형", "Defender": "방어형"}
GENERALITY_KO = {"specialist": "속성 특화", "element_first": "속성 위주", "generalist": "범용"}


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain dicts, a missing value as None (JSON null) rather than NaN."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def _flag(value: Any) -> bool:
    """A flag cell as a boolean, whether it was computed or read back from a table as text."""
    return str(value).lower() in ("true", "1")


def _read(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"unit_id": str}, **kwargs)


def _name(row: Any) -> str:
    ko = row.get("name_ko") if hasattr(row, "get") else None
    en = row.get("name_en") if hasattr(row, "get") else None
    return str(ko) if isinstance(ko, str) and ko else str(en or row.get("unit_id", ""))


def find_unit(query: str, units: pd.DataFrame, index: NameIndex | None = None) -> str:
    """A unit id from an id (``16``, ``016``, ``c016``), any name the alias table
    knows, or a Korean or English name - exact first, then a unique partial match.

    Only units in ``units`` (a table with ``unit_id``, ``name_ko``, ``name_en``)
    can be answered. A name two units share raises, listing both.
    """
    table = units.drop_duplicates("unit_id")
    present = set(table["unit_id"].astype(str))
    text = query.strip()
    if re.fullmatch(r"[cC]?\d{1,4}", text) and normalize_unit_id(text) in present:
        return normalize_unit_id(text)
    names = {str(r["unit_id"]): _name(r) for _, r in table.iterrows()}
    if index is not None:
        hit = index.resolve(text)
        if hit in present:
            return str(hit)
        shared = sorted(index.candidates(text) & present)
        if len(shared) > 1:
            options = ", ".join(f"{names[u]} ({u})" for u in shared)
            raise LookupError(f"'{query}' 은(는) 여러 니케의 이름이다: {options} — 번호로 지정할 것")
    key = normalize_name(text)
    ko = table["name_ko"].fillna("").astype(str).map(normalize_name)
    en = table["name_en"].fillna("").astype(str).map(normalize_name)
    exact = table[(ko == key) | (en == key)]
    if len(exact) == 1:
        return str(exact["unit_id"].iloc[0])
    partial = table[ko.str.contains(key, regex=False) | en.str.contains(key, regex=False)] if key else table.iloc[0:0]
    if len(exact) == 0 and len(partial) == 1:
        return str(partial["unit_id"].iloc[0])
    options = exact if len(exact) > 1 else partial
    if options.empty:
        raise LookupError(f"'{query}' 에 해당하는 니케가 랭킹 기록에 없다")
    listed = ", ".join(sorted(f"{_name(r)} ({r['unit_id']})" for _, r in options.iterrows()))
    raise LookupError(f"'{query}' 가 여러 니케와 맞는다: {listed}")


def load_index(directory: Path) -> NameIndex | None:
    from .build.roster import load_alias_index

    return load_alias_index(directory / "unit_aliases.csv")


@dataclass
class SeasonBlock:
    """One season's tiers: a finished season, the live one so far, or a live one
    with no snapshot yet (``pending``: no rows)."""

    season: Season | None
    number: int
    kind: str  # "finished", "live", "pending"
    rows: pd.DataFrame  # the season's rows of the history, with a display name
    note: str = ""


@dataclass
class Sample:
    """The rankers the tiers stand on: which servers, and ranks 1..``top_n`` of each."""

    servers: list[str]  # the servers in the tables
    chosen: ServerFilter  # how they were chosen; empty = every server
    top_n: int

    def __str__(self) -> str:
        where = describe(self.chosen, self.servers)
        if self.servers and (not self.chosen or self.chosen.exclude):
            where += f"({'·'.join(self.servers)})"
        return f"{where} × 상위 {self.top_n}위"

    def to_dict(self) -> dict[str, Any]:
        return {"servers": self.servers, **self.chosen.to_dict(), "top_n": self.top_n}


@dataclass
class TierView:
    moment: datetime
    finished: SeasonBlock | None
    current: SeasonBlock | None
    overall: pd.DataFrame  # one row per unit: its overall tier, best first
    elements: pd.DataFrame  # one row per unit and element it counts as: its tier there
    final_seasons: list[int]
    config: tiering.TierConfig
    sample: Sample | None = None
    weak: dict[int, str] | None = None  # counted season -> the element its boss was weak to
    live_seasons: list[int] = field(default_factory=list)  # in progress, counted as far as collected

    def element(self, element: str) -> pd.DataFrame:
        """The units of ``element`` - with those whose skill adds it (``source`` "skill") -
        best in it first; those yet to meet a season of it last."""
        if self.elements.empty:
            return self.elements
        return self.elements[self.elements["element"] == element]

    def element_seasons(self, element: str) -> list[int]:
        """The seasons whose boss was weak to ``element`` - the finished ones and a live one
        that counts: what its element tiers stand on."""
        return [s for s in self.final_seasons + self.live_seasons if (self.weak or {}).get(s) == element]

    def _parameters(self) -> dict[str, Any]:
        return {"trend_slope": list(self.config.trend_slope), "trend_pull": self.config.trend_pull,
                "overall": self.config.overall,
                "include_live": self.config.include_live, "cuts": dict(self.config.cuts),
                "overall_cuts": dict(self.config.overall_cuts)}

    def to_dict(self) -> dict[str, Any]:
        def block(b: SeasonBlock | None) -> dict[str, Any] | None:
            if b is None:
                return None
            return {
                "season": b.number,
                "kind": b.kind,
                "boss": b.season.boss if b.season else "",
                "weak_element": b.season.weak_element if b.season else "",
                "note": b.note,
                "units": _records(b.rows),
            }

        return {
            "moment": self.moment.isoformat(),
            "sample": self.sample.to_dict() if self.sample else None,
            "final_seasons": self.final_seasons,
            "live_seasons": self.live_seasons,
            "finished": block(self.finished),
            "current": block(self.current),
            "overall": _records(self.overall),
            "elements": _records(self.elements),
            "parameters": self._parameters(),
        }

    def element_dict(self, element: str) -> dict[str, Any]:
        return {
            "moment": self.moment.isoformat(),
            "sample": self.sample.to_dict() if self.sample else None,
            "element": element,
            "seasons": self.element_seasons(element),
            "live_seasons": self.live_seasons,
            "units": _records(self.element(element)),
            "parameters": self._parameters(),
        }


@dataclass
class UnitHistory:
    unit_id: str
    info: dict[str, Any]
    rows: pd.DataFrame
    profile: dict[str, Any] | None
    moment: datetime
    sample: Sample | None = None
    elements: tuple[str, ...] = ()  # the elements it counts as at ``moment``: its own, then any its skill adds
    live_seasons: list[int] = field(default_factory=list)  # in progress, counted as far as collected
    treasure_at: datetime | None = None  # when its treasure came out
    treasured: bool = False  # its treasure was out at ``moment``: the profile stands on the seasons with it
    life: dict[str, Any] | None = None  # its lifespan at ``moment`` (analyze.tiers.lifespans), with the run's days
    general: dict[str, Any] | None = None  # its generality at ``moment`` (analyze.tiers.generality)


class TierBook:
    def __init__(
        self,
        history: pd.DataFrame,
        seasons: pd.DataFrame,
        timeline: Timeline,
        config: tiering.TierConfig | None = None,
        index: NameIndex | None = None,
    ):
        self.history = history
        self.seasons = seasons
        self.timeline = timeline
        self.config = config or tiering.load_tier_config()
        self.index = index

    @classmethod
    def load(
        cls,
        data_dir: Path | None = None,
        config: tiering.TierConfig | None = None,
        *,
        servers: ServerFilter | None = None,
        cache_dir: Path | None = None,
    ) -> "TierBook":
        """The committed tables, or with ``servers`` the same tables on that
        server sample (computed once from ``raid_entries.csv``, then reused)."""
        directory = data_dir or processed_dir()
        tables = directory
        if servers:
            from .analyze.pipeline import run_servers

            if not (directory / "raid_entries.csv").is_file():
                raise RuntimeError("서버를 고르려면 raid_entries.csv 가 필요하다: `nikke build raids` (오프라인, 몇 초)")
            config = (config or tiering.load_tier_config()).with_servers(servers)
            tables = Path(run_servers(servers, data_dir=directory, config=config, cache_dir=cache_dir)["out_dir"])
        history = _read(tables / "metrics_unit_season.csv")
        seasons = _read(tables / "metrics_seasons.csv", keep_default_na=False, na_values=[""])  # the NA server
        if history.empty or seasons.empty:
            raise RuntimeError("no metric tables; run `nikke build raids` and `nikke analyze` first")
        for column in ("start_at", "end_at", "collected_on", "collected_until"):
            if column in seasons.columns:
                seasons[column] = pd.to_datetime(seasons[column], errors="coerce", utc=True)
        seasons["final"] = seasons["final"].astype(str).str.lower().isin(("true", "1"))
        history["end_at"] = pd.to_datetime(history["end_at"], errors="coerce", utc=True)
        return cls(history, seasons, Timeline.load(directory), config, load_index(directory))

    @property
    def sample(self) -> Sample:
        """Which servers' rankers the tables stand on (``server_names`` of the season table)."""
        names = self.seasons["server_names"] if "server_names" in self.seasons.columns else pd.Series(dtype=str)
        servers = ordered(n for value in names.dropna().astype(str) for n in value.split(";") if n)
        return Sample(servers, self.config.server_filter, self.config.top_n)

    def treasured(self, instant: pd.Timestamp) -> list[str]:
        """The units whose treasure was out at ``instant``."""
        return [u.unit_id for u in self.timeline.units if u.treasure_at is not None and _utc(u.treasure_at) <= instant]

    # ------------------------------------------------------------------

    def _season_rows(self, number: int) -> pd.DataFrame:
        rows = self.history[self.history["season"] == number].copy()
        rows["name"] = [_name(r) for _, r in rows.iterrows()]
        return rows.sort_values(["lift", "unit_id"], ascending=[False, True])

    def _standings(self, instant: pd.Timestamp) -> tiering.Standings:
        """Where every unit stands at ``instant``, with its names. In ``overall``,
        ``element`` is the unit's own; in ``elements``, the element of the row, and
        ``own_element`` the unit's own."""
        standing = tiering.standings(self.history, self.seasons, instant, self.config,
                                     treasured=self.treasured(instant))
        if standing.overall.empty:
            return standing
        info = self.history.drop_duplicates("unit_id").set_index("unit_id")
        columns = [c for c in ("name_ko", "name_en", "element", "extra_elements", "unit_class") if c in info.columns]
        overall = standing.overall.join(info[columns], on="unit_id")
        overall["name"] = [_name(r) for _, r in overall.iterrows()]
        beside = overall[["unit_id", "name", "name_ko", "name_en", "element", "overall_tier", "overall",
                          "overall_rank", "provisional"]].rename(columns={"element": "own_element"})
        return tiering.Standings(overall, standing.elements.merge(beside, on="unit_id", how="left"), standing.slots, standing.rows)

    def _counted(self, instant: pd.Timestamp) -> tuple[list[int], list[int], dict[int, str]]:
        """The finished and the live seasons the standings at ``instant`` stand on, and each one's weak element."""
        counted = tiering.counted_seasons(self.seasons, instant, self.config)
        final = sorted(int(s) for s in counted.loc[~counted["live"], "season"])
        live = sorted(int(s) for s in counted.loc[counted["live"], "season"])
        return final, live, {int(s): str(e) for s, e in zip(counted["season"], counted["weak_element"])}

    def at(self, moment: datetime | str | None = None) -> TierView:
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        instant = _utc(moment)
        snapshot = self.timeline.at(moment)
        standing = self._standings(instant)
        final_seasons, live_seasons, weak = self._counted(instant)

        finished = None
        if final_seasons:
            last = final_seasons[-1]
            finished = SeasonBlock(self.timeline.season(last), last, "finished", self._season_rows(last))

        current = None
        if snapshot.season is not None:
            number = snapshot.season.number
            row = self.seasons[self.seasons["season"] == number]
            if not row.empty and not bool(row["final"].iloc[0]) and row["collected_on"].iloc[0] <= instant:
                day = row["collected_on"].iloc[0].tz_convert("Asia/Seoul")
                current = SeasonBlock(snapshot.season, number, "live", self._season_rows(number),
                                      f"{day:%m/%d} 수집분 (잠정)")
            elif number not in final_seasons:
                current = SeasonBlock(snapshot.season, number, "pending", pd.DataFrame(), "아직 수집분 없음")
        return TierView(moment, finished, current, standing.overall, standing.elements, final_seasons, self.config,
                        self.sample, weak, live_seasons)

    # ------------------------------------------------------------------

    def find_unit(self, query: str) -> str:
        return find_unit(query, self.history, self.index)

    def unit(self, query: str, moment: datetime | str | None = None) -> UnitHistory:
        """One unit's record. ``profile`` is where it stands at ``moment``: its
        overall tier, with ``units`` (how many its rank is among), under
        ``elements`` its tier in each element it counts as, with ``element_units``,
        and under ``slots`` the five values its overall is made of - on the
        seasons with its treasure once that was out at ``moment``. ``rows`` is its
        whole record, before and after the treasure."""
        unit_id = self.find_unit(query)
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        rows = self.history[self.history["unit_id"] == unit_id].sort_values("season")
        columns = ["unit_id", "name_ko", "name_en", "element", "extra_elements", "treasure_elements", "burst",
                   "unit_class", "release_date"]
        info = _records(rows.iloc[[-1]].reindex(columns=columns))[0]
        instant = _utc(moment)
        standing = self._standings(instant)
        profile = None
        match = standing.overall[standing.overall["unit_id"] == unit_id] if not standing.overall.empty else None
        if match is not None and not match.empty:
            profile = _records(match[tiering.OVERALL_COLUMNS])[0]
            profile["units"] = len(standing.overall)
            listed = standing.elements.groupby("element").size()  # as many as the element's table lists
            mine = standing.elements[standing.elements["unit_id"] == unit_id].sort_values("source", kind="stable")
            profile["elements"] = [
                {**record, "element_units": int(listed.get(record["element"], 0))}
                for record in _records(mine[tiering.ELEMENT_COLUMNS].drop(columns="unit_id"))
            ]
            slots = standing.slots[standing.slots["unit_id"] == unit_id]
            profile["slots"] = _records(slots[tiering.SLOT_COLUMNS].drop(columns="unit_id"))
        _, live, _ = self._counted(instant)
        live = [s for s in live if s in set(rows["season"].astype(int))]  # the live seasons it was out for
        unit = next((u for u in self.timeline.units if u.unit_id == unit_id), None)
        treasure_at = unit.treasure_at if unit is not None else None
        treasured = treasure_at is not None and _utc(treasure_at) <= instant
        added = listed_elements(info.get("extra_elements")) + (
            listed_elements(info.get("treasure_elements")) if treasured else [])
        elements = tuple(dict.fromkeys(e for e in [info.get("element")] + added if isinstance(e, str) and e))
        return UnitHistory(unit_id, info, rows, profile, moment, self.sample, elements, live, treasure_at, treasured,
                           self._life(unit_id, instant), self._general(unit_id, standing, instant))

    def _general(self, unit_id: str, standing: tiering.Standings, instant: pd.Timestamp) -> dict[str, Any] | None:
        """The unit's generality, from ``standing`` (where it stands at the moment), and the
        shape of its career then (``curve``, ``g_peak``, ``g_low``); None when it has no
        place there."""
        general = tiering.generality(standing, self.config)
        general = general[general["unit_id"] == unit_id]
        if general.empty:
            return None
        record = _records(general.drop(columns="unit_id"))[0]
        shapes = tiering.curves(self.history, self.seasons, instant, self.config)
        mine = shapes[shapes["unit_id"] == unit_id]
        if not mine.empty:
            record.update(_records(mine[["curve", "g_peak", "g_low"]])[0])
        return record

    def _life(self, unit_id: str, instant: pd.Timestamp) -> dict[str, Any] | None:
        """The unit's lifespan at ``instant``, with ``run_days``: how long its run in use has
        lasted - to ``instant`` while in use, to the end of its last season once retired - and
        ``recent``: the latest season counted then used it."""
        life = tiering.lifespans(self.history, self.seasons, instant, self.config)
        mine = life[life["unit_id"] == unit_id]
        if mine.empty:
            return None
        record = _records(mine)[0]
        record["run_days"] = None
        if record["run_from"] is not None:
            by_season = self.seasons.set_index("season")
            start = by_season.loc[record["run_from"], "start_at"]
            end = min(by_season.loc[record["last_used"], "end_at"], instant) if record["retired"] else instant
            record["run_days"] = (end - start).total_seconds() / 86400.0 if not pd.isna(start) else None
        final, live, _ = self._counted(instant)
        record["recent"] = record["last_used"] is not None and record["last_used"] == max(final + live, default=None)
        return record


def _kst():
    from .util.kdate import KST

    return KST


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _element(value: str) -> str:
    return ELEMENT_KO.get(value, value) if value else "?"


def _season_head(block: SeasonBlock, label: str) -> str:
    season = block.season
    boss = season.boss if season else "?"
    weak = _element(season.weak_element) if season else "?"
    head = f"■ {label} 시즌 {block.number} · {boss} · 약점 {weak}"
    return head + (f" — {block.note}" if block.note else "")


def _tier_lines(rows: pd.DataFrame, value: str, tier: str, config: tiering.TierConfig, *, show_all: bool,
                mark=None) -> list[str]:
    lines = []
    labels = config.tier_order if show_all else [t for t in config.tier_order if tiering.tier_rank(t, config) <= tiering.tier_rank("B", config)]
    for label in labels:
        subset = rows[rows[tier] == label]
        if label == config.tier_order[-1]:
            subset = subset[subset[value] > 0]
        if subset.empty:
            continue
        items = [f"{r['name']} {r[value]:.2f}{mark(r) if mark else ''}" for _, r in subset.iterrows()]
        lines.append(f"  {label:<3} " + " · ".join(items))
    if not lines:
        lines.append("  (기록 없음)")
    return lines


def _span(final: list[int], live: list[int]) -> str:
    """The seasons a view stands on: ``끝난 시즌 1–40 + 진행 중 시즌 41(잠정)``."""
    if not final:
        parts = ["끝난 시즌 없음"]
    else:
        parts = [f"끝난 시즌 {final[0]}–{final[-1]}" if len(final) > 1 else f"끝난 시즌 {final[0]}"]
    if live:
        parts.append(f"진행 중 시즌 {'·'.join(map(str, live))}(잠정)")
    return " + ".join(parts)


def _cuts(config: tiering.TierConfig, *, overall: bool = False) -> str:
    cuts = config.overall_cuts if overall else config.cuts
    return " · ".join(f"{label} {cut:g}" for label, cut in cuts[:-1])


def _recency(config: tiering.TierConfig) -> str:
    own, other = config.trend_slope
    return ("속성·종합 티어 = 보스 약점마다 시즌 기록의 추세선을 지금 자리에서 읽은 값(보정 기여도, 기록이 적으면 "
            f"기울기를 평균 자기 속성 {own:g} · 다른 속성 {other:g}/년 쪽으로)")


def _header(view: TierView, title: str) -> list[str]:
    config = view.config
    return [
        f"{view.moment:%Y-%m-%d %H:%M} KST 기준 {title} · {_span(view.final_seasons, view.live_seasons)}",
        f"  표본: {view.sample or f'서버마다 상위 {config.top_n}위'}",
        *LIFT_NOTE,
        f"  티어 컷: 시즌·속성 {_cuts(config)} / 종합 {_cuts(config, overall=True)}",
        f"  {_recency(config)}",
    ]


def _provisional_note(config: tiering.TierConfig) -> str:
    return (f"* = 종합이 잠정: 겪은 보스 약점이 {config.min_elements_observed}가지 미만이거나 "
            "자기 속성 시즌을 아직 못 겪음")


CURVE_KO = {"unused": "안 쓰임", "specialist": "처음부터 속성 특화", "narrowed": "범용 → 속성 특화",
            "faded": "범용인 채로 저묾", "general": "아직 범용", "unknown": "아직 모름"}
FILL_NOTE = ("못 겪은 약점 칸: 다른 속성 칸은 겪은 다른 속성의 평균(다른 속성 기록이 없으면 0), "
             "자기 속성 칸은 0")


def _element_marks(elements: pd.DataFrame) -> dict[str, str]:
    """Each unit's element tiers in one phrase, its own element first: ``작열 SS``,
    ``작열 SS · 철갑 SS``; ``?`` for an element it has yet to meet a season of."""
    marks: dict[str, list[str]] = {}
    for _, r in elements.sort_values("source", kind="stable").iterrows():
        tier = r["element_tier"] if isinstance(r["element_tier"], str) and r["element_tier"] else "?"
        marks.setdefault(r["unit_id"], []).append(f"{_element(r['element'])} {tier}")
    return {unit: " · ".join(parts) for unit, parts in marks.items()}


def render(view: TierView, *, show_all: bool = False) -> str:
    """The last finished season, the one in progress, and the overall tier table."""
    config = view.config
    out = _header(view, "티어")
    for block, label in ((view.finished, "직전"), (view.current, "진행 중")):
        if block is None:
            continue
        out += ["", _season_head(block, label)]
        if block.kind == "pending":
            continue
        if block.rows.empty:
            out.append("  (기록 없음)")
            continue
        out += _tier_lines(block.rows, "lift", "tier", config, show_all=show_all)

    if not view.overall.empty:
        out += ["", f"■ 종합 티어 = {OVERALL_KO.get(config.overall, config.overall)} · 괄호 = 속성 티어"]
        marks = _element_marks(view.elements)

        def mark(r: pd.Series) -> str:
            return ("*" if bool(r["provisional"]) else "") + f"({marks.get(r['unit_id'], '?')})"

        out += _tier_lines(view.overall, "overall", "overall_tier", config, show_all=show_all, mark=mark)
        out.append(f"  {_provisional_note(config)} · ? = 그 속성 약점 시즌을 아직 못 겪음")
        out.append(f"  {FILL_NOTE}")
        out.append("  속성별 비교: nikke tier --element 작열 (" + "·".join(ELEMENT_KO[e] for e in ELEMENTS[1:]) + ")"
                   " · 한 니케 자세히: nikke tier --unit 이름")
    return "\n".join(out)


def render_element(view: TierView, element: str, *, show_all: bool = False) -> str:
    """The units of one element, by their tier in it, with their overall tier beside."""
    config = view.config
    name = _element(element)
    seasons = view.element_seasons(element)
    listed = " · ".join(f"{s}(진행 중)" if s in view.live_seasons else str(s) for s in seasons)
    out = _header(view, f"{name} 속성 티어")
    out.append(f"  {name} 속성 티어 = 보스 약점이 {name}이던 시즌" + (f"({listed})" if seasons else "")
               + "의 기여도 추세를 지금 자리에서 읽은 값 · 괄호 = 종합 티어")
    rows = view.element(element)
    out += ["", f"■ {name} 니케 {len(rows)}명"]
    if rows.empty:
        out.append("  (기록 없음)")
        return "\n".join(out)

    def mark(r: pd.Series) -> str:
        guest = f" · 본래 {_element(r['own_element'])}" if r["source"] == "skill" else ""
        return f"({r['overall_tier']}{'*' if bool(r['provisional']) else ''}{guest})"

    out += _tier_lines(rows, "element_lift", "element_tier", config, show_all=show_all, mark=mark)
    unseen = rows[rows["element_lift"].isna()]
    if not unseen.empty:
        since = "출시·애장품" if tiering.played_with_treasure(unseen).any() else "출시"
        out.append(f"  미관측 ({since} 후 {name} 약점 시즌 없음): " + " · ".join(unseen["name"]))
    notes = [_provisional_note(config)]
    if (rows["source"] == "skill").any():
        notes.append(f"본래 X = 스킬로 {name} 우월 코드도 가진 X 속성 니케")
    out.append("  " + " · ".join(notes))
    return "\n".join(out)


def _sides(profile: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """The overall's five slots split into the unit's own elements and the others."""
    own = {e["element"] for e in profile["elements"]}
    slots = profile.get("slots") or []
    return [s for s in slots if s["element"] in own], [s for s in slots if s["element"] not in own]


def _provisional_reason(profile: dict[str, Any], config: tiering.TierConfig) -> str:
    """Why an overall is provisional, in words; empty when it is not."""
    if not profile.get("provisional"):
        return ""
    own, other = _sides(profile)
    reasons = []
    if own and not any(s["seasons"] for s in own):
        reasons.append("자기 속성 시즌을 아직 못 겪음")
    elif not any(s["seasons"] for s in other):
        reasons.append("다른 속성 기록 없음")
    if profile["elements_observed"] < config.min_elements_observed:
        reasons.append(f"겪은 보스 약점 {profile['elements_observed']}가지뿐")
    return " · ".join(reasons)


def _slot_lines(profile: dict[str, Any], config: tiering.TierConfig) -> list[str]:
    """What the overall is made of: the five boss weaknesses, filled-in values in brackets and how."""
    own, other = _sides(profile)
    if not own + other:
        return []
    mine = {s["element"] for s in own}
    parts = [f"{'▶' if s['element'] in mine else ''}{_element(s['element'])} "
             + (f"{s['lift']:.2f}" if s["seasons"] else f"({'~' if s.get('borrowed') else ''}{s['lift']:.2f})")
             for s in sorted(own + other, key=lambda s: ELEMENTS.index(s["element"]))]
    how = {"mean": "의 평균", "frequency": "을 자주 나온 약점일수록 크게 친 평균",
           "max": " 중 괄호 없는 가장 큰 값"}.get(config.overall, "")
    lines = [f"  {pad('', 9)}  = 보스 약점별 {' · '.join(parts)}{how}"]
    filled = []
    if any(not s["seasons"] for s in other):
        filled.append("다른 속성은 겪은 다른 속성의 평균" if any(s["seasons"] for s in other)
                      else "다른 속성은 나중에 겪은 다른 속성 시즌들로(~)" if any(s.get("borrowed") for s in other)
                      else "다른 속성은 기록이 없어 0")
    if any(not s["seasons"] for s in own):
        filled.append("자기 속성은 나중에 겪은 시즌들로(~)" if all(s.get("borrowed") for s in own if not s["seasons"])
                      else "자기 속성은 0")
    if filled:
        lines.append(f"  {pad('', 9)}    괄호 = 아직 못 겪어서 채운 값: {', '.join(filled)} · ▶ = 자기 속성")
    return lines


def _unit_tiers(history: UnitHistory, config: tiering.TierConfig) -> list[str]:
    """The unit's tiers at the moment of the view: one line per element it counts as, then the overall
    and what it is made of."""
    profile = history.profile
    live = (f" · 진행 중 시즌 {'·'.join(map(str, history.live_seasons))}도 지금까지 수집분으로 잠정 반영"
            if history.live_seasons else "")
    if not profile:
        if history.treasured:
            return [f"{history.moment:%Y-%m-%d} 기준  애장품을 낀 시즌 기록이 아직 없음 (애장품 전 기록은 아래 표)"]
        return [f"{history.moment:%Y-%m-%d} 기준{live}  아직 시즌 기록 없음"]
    since = " · 애장품을 낀 시즌만으로" if history.treasured else ""
    lines = [f"{history.moment:%Y-%m-%d} 기준{since}{live}"]
    for i, standing in enumerate(profile["elements"]):
        element = _element(standing["element"])
        label = element + (" (스킬)" if standing["source"] == "skill" else "")
        if standing["element_lift"] is None:
            since = "애장품" if history.treasured else "출시"
            text = f"{label} 미관측 — {since} 후 {element} 약점 시즌이 아직 없음"
        else:
            text = (f"{label} {standing['element_tier']} {standing['element_lift']:.2f} · {element} 니케 "
                    f"{standing['element_units']}명 중 {standing['element_rank']}위 · "
                    f"{element} 약점 시즌 {standing['element_seasons']}번")
        lines.append(f"  {pad('속성 티어' if i == 0 else '', 9)}  {text}")
    reason = _provisional_reason(profile, config)
    lines.append(f"  {pad('종합 티어', 9)}  {profile['overall_tier']} {profile['overall']:.2f} · "
                 f"{profile['units']}명 중 {profile['overall_rank']}위" + (f" · 잠정({reason})" if reason else ""))
    return lines + _slot_lines(profile, config)


def _duration(days: float | None) -> str:
    """``3주``, ``7개월``, ``2년 5개월`` - months of 30.44 days, rounded half up as the page does."""
    if days is None or pd.isna(days):
        return "-"
    months = int(days / 30.44 + 0.5)
    if months < 1:
        return f"{max(1, int(days / 7 + 0.5))}주"
    if months < 12:
        return f"{months}개월"
    years, rest = divmod(months, 12)
    return f"{years}년 {rest}개월" if rest else f"{years}년"


def _retired_rule(config: tiering.TierConfig) -> str:
    """What retired means, with ``config``'s parameters (the site says the same)."""
    days, own = config.retire_after_days, config.retire_after_own_seasons
    if not own:
        return f"마지막으로 쓰인 시즌이 끝나고 {days:g}일 동안 안 쓰임"
    seasons = "자기 속성 약점 시즌" + (f" {own}번" if own > 1 else "")
    since = f"마지막으로 쓰인 시즌이 끝나고 {days:g}일이 지났고 그 사이 온 " if days > 0 else "마지막으로 쓰인 뒤 온 "
    return f"{since}{seasons}에도 안 쓰임 (자기 속성 시즌이 아직 안 왔으면 현역)"


def _life_lines(history: UnitHistory, config: tiering.TierConfig) -> list[str]:
    """The unit's lifespan at the moment of the view: in use or retired, since when, how often."""
    life = history.life
    if not life:
        return []
    usage = f"시즌 티어 {config.min_tier}"
    head = f"  {pad('수명', 9)}  "
    if life["last_used"] is None:
        return [head + f"쓰인 시즌 없음 — {usage} 이상인 시즌이 없음 (출시 뒤 {life['seasons_out']}시즌)"]
    first, last, missed = life["run_from"], life["last_used"], life["missed_own"]
    own = "·".join(_element(e) for e in history.elements)
    if life["retired"]:
        run = f"S{last} 한 시즌" if first == last else f"S{first}–S{last} {_duration(life['run_days'])}"
        text = f"은퇴 · {run} · S{last} 뒤 {_duration(life['idle_days'])}째 안 쓰임"
        if missed:
            text += f" · {own} 약점 시즌 {missed}번 놓침"
    else:
        ago = f"({_duration(life['idle_days'])} 전)" if life["idle_days"] >= 45 else ""
        text = f"현역 · S{first}부터 {_duration(life['run_days'])}째 · 마지막 S{last}{ago}"
        need = config.retire_after_own_seasons
        if need and not life["recent"] and life["idle_days"] >= config.retire_after_days:
            # past the days: in use only because its element has not come round (often enough) since
            text += (f" · {own} 약점 시즌 {missed}번 놓침(은퇴는 {need}번부터)" if missed
                     else f" · 그 뒤 {own} 약점 시즌 아직 없음")
    text += f" · 출시 뒤 {life['seasons_out']}시즌 중 {life['seasons_used']}번 쓰임"
    if life["returns"]:
        again = f"은퇴한 적 {life['returns']}번," if life["returns"] > 1 else "은퇴했다가"
        text += f" · 복귀(S{life['first_used']}부터 쓰이다 {again} S{first}부터 다시)"
    return [head + text, f"  {pad('', 9)}  쓰임 = {usage} 이상인 시즌 · 은퇴 = {_retired_rule(config)}"]


def _general_lines(history: UnitHistory, config: tiering.TierConfig) -> list[str]:
    """How general the unit is (the site's tile says the same)."""
    c = history.general
    if not c:
        return []
    g = c.get("generality")
    general = (f"{GENERALITY_KO[c['generality_band']]} {g:.2f} (최근 한 바퀴: 2 × 다른 속성 평균 {c['other_level']:.2f} ÷ "
               f"(자기 속성 {c['own_level']:.2f} + {c['other_level']:.2f}), 0–2)" if g is not None and g == g
               else "없음 — 최근 한 바퀴에 자기 속성·다른 속성 시즌 중 한쪽이 없거나 거의 안 쓰임")
    low, high = config.generality_bands
    lines = [f"  {pad('범용도', 9)}  {general}",
             f"  {pad('', 9)}  범용도 띠 = 속성 특화 < {low:g} ≤ 속성 위주 < {high:g} ≤ 범용"]
    curve = c.get("curve")
    if curve:
        numbers = (f" (전성기 범용도 {c['g_peak']:.2f} · 내려오며 가장 낮은 {c['g_low']:.2f})"
                   if curve not in ("unused", "unknown") and c.get("g_low") is not None and c["g_low"] == c["g_low"] else "")
        lines.append(f"  {pad('생애 곡선', 9)}  {CURVE_KO[curve]}{numbers} — 로테이션 한 바퀴씩 본 쓰임의 모양, 역할이 아님")
    return lines


def render_unit(history: UnitHistory, config: tiering.TierConfig | None = None) -> str:
    config = config or tiering.TierConfig()
    info = {key: value if value is not None else "" for key, value in history.info.items()}
    name = info.get("name_ko") or info.get("name_en")
    own = info.get("element", "")
    extra = listed_elements(info.get("extra_elements"))
    by_treasure = listed_elements(info.get("treasure_elements"))
    skill = (f" · 스킬로 {'·'.join(_element(e) for e in extra)} 우월 코드" if extra else "") + (
        f" · 애장품 스킬로 {'·'.join(_element(e) for e in by_treasure)} 우월 코드" if by_treasure else "")
    treasure = f" · 애장품 {history.treasure_at:%Y-%m-%d}" if history.treasure_at is not None else ""
    out = [
        f"{name} ({info.get('name_en', '')}) · {_element(own)} "
        f"{CLASS_KO.get(info.get('unit_class', ''), info.get('unit_class', ''))}{skill} · "
        f"버스트 {info.get('burst', '')} · 출시 {info.get('release_date', '')}{treasure}"
    ]
    if history.sample is not None and history.sample.chosen:
        out.append(f"표본: {history.sample}")
    out += _unit_tiers(history, config)
    out += _life_lines(history, config)
    out += _general_lines(history, config)
    out += [
        "",
        f"{rjust('시즌', 4)}  {pad('시작', 10)}  {pad('보스 · 약점', 30)}  {rjust('사용', 5)}  {rjust('덱 몫', 5)}  "
        f"{rjust('1덱', 5)}  {rjust('기여도', 6)}  {pad('시즌', 4)}  {pad('속성', 7)}  종합",
    ]
    marked = False
    for _, row in history.rows.iterrows():
        if not marked and history.treasure_at is not None and _flag(row.get("treasure")):
            out.append(f"{rjust(TREASURE_MARK, 4)}  {history.treasure_at:%Y-%m-%d}  애장품 — 여기부터 속성·종합 티어는 "
                       "애장품을 낀 시즌만으로 매긴다")
            marked = True
        used = row["presence"] > 0
        start = pd.Timestamp(row["start_at"]).tz_convert("Asia/Seoul") if isinstance(row["start_at"], str) and row["start_at"] else None
        boss_name = next((row[c] for c in ("boss_ko", "boss_en") if isinstance(row.get(c), str) and row[c]), "?")
        weak = row["weak_element"] if isinstance(row["weak_element"], str) else ""
        favoured = _flag(row["element_match"]) if "element_match" in row.index else weak in history.elements
        boss = f"{boss_name} · {'▶' if favoured else ''}{_element(weak)}"
        deck_share = f"{row['deck_share']:.0%}" if used and pd.notna(row["deck_share"]) else "-"
        main = f"{row['main_deck_rate']:.0%}" if used and pd.notna(row["main_deck_rate"]) else "-"
        element = f"{row['element_tier']} {row['element_lift']:.2f}" if pd.notna(row.get("element_lift")) else "-"
        overall = f"{row['overall_tier']} {row['overall']:.2f}" if pd.notna(row.get("overall")) else "-"
        live = "" if bool(row.get("final", True)) else " (진행 중)"
        out.append(
            f"{int(row['season']):>4}  {pad(f'{start:%Y-%m-%d}' if start is not None else '', 10)}  {pad(boss, 30)}  "
            f"{row['presence']:>5.0%}  {deck_share:>5}  {main:>5}  {row['lift']:>6.2f}  {pad(str(row['tier']), 4)}  "
            f"{pad(element, 7)}  {overall}{live}"
        )
    elements = "·".join([_element(e) for e in [own] + extra if e]
                        + [f"{_element(e)}(애장품 뒤)" for e in by_treasure]) or "?"
    out += [
        f"▶ = 보스 약점이 이 니케의 속성({elements})인 시즌 · 사용 = 이 니케를 쓴 랭커 비율 · "
        "덱 몫 = 이 니케가 든 덱이 그 랭커 대미지에서 차지한 비율 · 1덱 = 가장 센 덱에 넣은 비율",
        "시즌 = 그 시즌 기여도의 티어 · 속성·종합 = 그 시즌이 끝났을 때의 속성 티어·종합 티어(진행 중 시즌은 지금까지)",
    ]
    if marked:
        out.append(f"{TREASURE_MARK} = 애장품이 나온 때. 애장품 전과 뒤의 속성·종합 티어는 따로 매긴다(애장품이 나오면 모두 끼고 쓰므로)")
    return "\n".join(out)
