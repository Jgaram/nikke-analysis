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
table the units of one element.

Reads the metric tables (``metrics_unit_season.csv``, ``metrics_seasons.csv``)
and the timeline, so it works offline from committed data. A view of the past
uses only what was known then: seasons that had ended by that moment, and the
season in progress only if its snapshot had been taken by then.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .analyze import tiers as tiering
from .analyze.metrics import ELEMENTS
from .paths import processed_dir
from .servers import ServerFilter, describe, ordered
from .timeline import ELEMENT_KO, Season, Timeline, resolve_moment
from .util.names import NameIndex, normalize_name, normalize_unit_id
from .util.text import pad, rjust

OVERALL_KO = {"mean": "5속성 균등 평균", "frequency": "최근 등장 빈도 가중", "max": "최고 속성"}
CLASS_KO = {"Attacker": "화력형", "Supporter": "지원형", "Defender": "방어형"}


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as plain dicts, a missing value as None (JSON null) rather than NaN."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


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
    weak: dict[int, str] | None = None  # finished season -> the element its boss was weak to

    def element(self, element: str) -> pd.DataFrame:
        """The units of ``element`` - with those whose skill adds it (``source`` "skill") -
        best in it first; those yet to meet a season of it last."""
        if self.elements.empty:
            return self.elements
        return self.elements[self.elements["element"] == element]

    def element_seasons(self, element: str) -> list[int]:
        """The finished seasons whose boss was weak to ``element``: what its element tiers stand on."""
        return [s for s in self.final_seasons if (self.weak or {}).get(s) == element]

    def _parameters(self) -> dict[str, Any]:
        return {"half_life_days": self.config.half_life_days, "overall": self.config.overall,
                "cuts": dict(self.config.cuts)}

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
    elements: tuple[str, ...] = ()  # the elements the unit counts as: its own, then any its skill adds


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

    # ------------------------------------------------------------------

    def _season_rows(self, number: int) -> pd.DataFrame:
        rows = self.history[self.history["season"] == number].copy()
        rows["name"] = [_name(r) for _, r in rows.iterrows()]
        return rows.sort_values(["lift", "unit_id"], ascending=[False, True])

    def _standings(self, instant: pd.Timestamp) -> tiering.Standings:
        """Where every unit stands at ``instant``, with its names. In ``overall``,
        ``element`` is the unit's own; in ``elements``, the element of the row, and
        ``own_element`` the unit's own."""
        standing = tiering.standings(self.history, self.seasons, instant, self.config)
        if standing.overall.empty:
            return standing
        info = self.history.drop_duplicates("unit_id").set_index("unit_id")
        columns = [c for c in ("name_ko", "name_en", "element", "extra_elements", "unit_class") if c in info.columns]
        overall = standing.overall.join(info[columns], on="unit_id")
        overall["name"] = [_name(r) for _, r in overall.iterrows()]
        beside = overall[["unit_id", "name", "name_ko", "name_en", "element", "overall_tier", "overall",
                          "overall_rank", "provisional"]].rename(columns={"element": "own_element"})
        return tiering.Standings(overall, standing.elements.merge(beside, on="unit_id", how="left"))

    def at(self, moment: datetime | str | None = None) -> TierView:
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        instant = _utc(moment)
        snapshot = self.timeline.at(moment)
        standing = self._standings(instant)
        known = self.seasons[self.seasons["final"] & (self.seasons["end_at"] <= instant)]
        final_seasons = sorted(int(s) for s in known["season"])
        weak = {int(s): str(e) for s, e in zip(known["season"], known["weak_element"])} if "weak_element" in known else {}

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
                        self.sample, weak)

    # ------------------------------------------------------------------

    def find_unit(self, query: str) -> str:
        return find_unit(query, self.history, self.index)

    def unit(self, query: str, moment: datetime | str | None = None) -> UnitHistory:
        """One unit's record. ``profile`` is where it stands at ``moment``: its
        overall tier, with ``units`` (how many its rank is among), and under
        ``elements`` its tier in each element it counts as, with ``element_units``."""
        unit_id = self.find_unit(query)
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        rows = self.history[self.history["unit_id"] == unit_id].sort_values("season")
        columns = ["unit_id", "name_ko", "name_en", "element", "extra_elements", "burst", "unit_class", "release_date"]
        info = _records(rows.iloc[[-1]].reindex(columns=columns))[0]
        extra = info.get("extra_elements")
        elements = tuple(e for e in [info.get("element")] + (extra.split(";") if isinstance(extra, str) else [])
                         if isinstance(e, str) and e)
        standing = self._standings(_utc(moment))
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
        return UnitHistory(unit_id, info, rows, profile, moment, self.sample, elements)


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


def _header(view: TierView, title: str) -> list[str]:
    config = view.config
    span = f"완료 시즌 {view.final_seasons[0]}–{view.final_seasons[-1]}" if view.final_seasons else "완료 시즌 없음"
    return [
        f"{view.moment:%Y-%m-%d %H:%M} KST 기준 {title} · {span} · 최근 가중 반감기 {config.half_life_days:g}일",
        f"  표본: {view.sample or f'서버마다 상위 {config.top_n}위'}",
    ]


def _provisional_note(config: tiering.TierConfig) -> str:
    return f"* = 관측한 약점 속성이 {config.min_elements_observed}개 미만이라 종합이 잠정"


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
    out = _header(view, "티어") + ["  lift: 표본 랭커의 대미지 중 그 니케 몫, 1.0 = 한 사람이 쓰는 25명의 평균 몫"]
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
        out += ["", f"■ 종합 티어 ({OVERALL_KO.get(config.overall, config.overall)}) · 괄호 = 속성 티어"]
        marks = _element_marks(view.elements)

        def mark(r: pd.Series) -> str:
            return ("*" if bool(r["provisional"]) else "") + f"({marks.get(r['unit_id'], '?')})"

        out += _tier_lines(view.overall, "overall", "overall_tier", config, show_all=show_all, mark=mark)
        out.append(f"  {_provisional_note(config)} · ? = 그 속성 약점 시즌을 아직 겪지 않음")
        out.append("  속성별 비교: nikke tier --element 작열 (" + "·".join(ELEMENT_KO[e] for e in ELEMENTS[1:]) + ")")
    return "\n".join(out)


def render_element(view: TierView, element: str, *, show_all: bool = False) -> str:
    """The units of one element, by their tier in it, with their overall tier beside."""
    config = view.config
    name = _element(element)
    seasons = view.element_seasons(element)
    out = _header(view, f"{name} 속성 티어")
    out.append(f"  {name} 속성 티어: 보스 약점이 {name}이던 시즌"
               + (f"({' · '.join(map(str, seasons))})" if seasons else "")
               + "에서 낸 lift · 괄호 = 종합 티어")
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
        out.append(f"  미관측 (출시 후 {name} 약점 시즌 없음): " + " · ".join(unseen["name"]))
    notes = [_provisional_note(config)]
    if (rows["source"] == "skill").any():
        notes.append(f"본래 X = 스킬로 {name} 우월 코드도 가진 X 속성 니케")
    out.append("  " + " · ".join(notes))
    return "\n".join(out)


def _unit_tiers(history: UnitHistory) -> list[str]:
    """The unit's tiers at the moment of the view: one line per element it counts as, then the overall."""
    profile = history.profile
    if not profile:
        return [f"{history.moment:%Y-%m-%d} 기준  아직 끝난 시즌 기록 없음"]
    lines = [f"{history.moment:%Y-%m-%d} 기준"]
    for i, standing in enumerate(profile["elements"]):
        element = _element(standing["element"])
        label = element + (" (스킬)" if standing["source"] == "skill" else "")
        if standing["element_lift"] is None:
            text = f"{label} 미관측 — 출시 후 {element} 약점 시즌이 아직 없음"
        else:
            text = (f"{label} {standing['element_tier']} {standing['element_lift']:.2f} · {element} 니케 "
                    f"{standing['element_units']}명 중 {standing['element_rank']}위 · "
                    f"{element} 약점 시즌 {standing['element_seasons']}번")
        lines.append(f"  {pad('속성 티어' if i == 0 else '', 9)}  {text}")
    provisional = (f" (잠정 — 관측한 약점 속성 {profile['elements_observed']}개)"
                   if profile.get("provisional") else "")
    lines.append(f"  {pad('종합 티어', 9)}  {profile['overall_tier']} {profile['overall']:.2f}{provisional} · "
                 f"{profile['units']}명 중 {profile['overall_rank']}위")
    return lines


def render_unit(history: UnitHistory, config: tiering.TierConfig | None = None) -> str:
    info = {key: value if value is not None else "" for key, value in history.info.items()}
    name = info.get("name_ko") or info.get("name_en")
    own = info.get("element", "")
    extra = [e for e in history.elements if e != own]
    skill = f" · 스킬로 {'·'.join(_element(e) for e in extra)} 우월 코드" if extra else ""
    out = [
        f"{name} ({info.get('name_en', '')}) · {_element(own)} "
        f"{CLASS_KO.get(info.get('unit_class', ''), info.get('unit_class', ''))}{skill} · "
        f"버스트 {info.get('burst', '')} · 출시 {info.get('release_date', '')}"
    ]
    if history.sample is not None and history.sample.chosen:
        out.append(f"표본: {history.sample}")
    out += _unit_tiers(history)
    out += [
        "",
        f"{rjust('시즌', 4)}  {pad('시작', 10)}  {pad('보스 · 약점', 30)}  {rjust('채용', 5)}  {rjust('덱 몫', 5)}  "
        f"{rjust('메인', 5)}  {rjust('lift', 5)}  {pad('시즌', 4)}  {pad('속성', 7)}  종합",
    ]
    for _, row in history.rows.iterrows():
        used = row["presence"] > 0
        start = pd.Timestamp(row["start_at"]).tz_convert("Asia/Seoul") if isinstance(row["start_at"], str) and row["start_at"] else None
        boss_name = row["boss_en"] if isinstance(row["boss_en"], str) and row["boss_en"] else "?"
        weak = row["weak_element"] if isinstance(row["weak_element"], str) else ""
        boss = f"{boss_name} · {'▶' if weak in history.elements else ''}{_element(weak)}"
        deck_share = f"{row['deck_share']:.0%}" if used and pd.notna(row["deck_share"]) else "-"
        main = f"{row['main_deck_rate']:.0%}" if used and pd.notna(row["main_deck_rate"]) else "-"
        element = f"{row['element_tier']} {row['element_lift']:.2f}" if pd.notna(row.get("element_lift")) else "-"
        overall = f"{row['overall_tier']} {row['overall']:.2f}" if pd.notna(row.get("overall")) else "-"
        live = "" if bool(row.get("final", True)) else " (진행 중)"
        out.append(
            f"{int(row['season']):>4}  {pad(f'{start:%Y-%m-%d}' if start is not None else '', 10)}  {pad(boss, 30)}  "
            f"{row['presence']:>5.0%}  {deck_share:>5}  {main:>5}  {row['lift']:>5.2f}  {pad(str(row['tier']), 4)}  "
            f"{pad(element, 7)}  {overall}{live}"
        )
    elements = "·".join(_element(e) for e in history.elements) or "?"
    out.append(f"▶ = 보스 약점이 이 니케의 속성({elements})인 시즌 · 속성 = 그 시즌 약점 속성에서의 티어, "
               "종합 = 종합 티어 (둘 다 그 시즌이 끝난 시점)")
    return "\n".join(out)
