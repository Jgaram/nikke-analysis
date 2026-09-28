"""Tiers at a moment, and one unit's tier history.

    nikke tier                   now: the last finished season, the one in
                                 progress, the next one, and the overall tiers
    nikke tier 2주년             the same, as the data stood at the anniversary
    nikke tier --unit 크라운     one unit, season by season
    nikke tier --exclude NA      the same on another server sample (--server KR,JP
                                 keeps only those); works with the two above

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
    view.overall.head()              # element slots, overall tier, role per unit
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

ROLE_KO = {
    "universal": "범용",
    "hybrid": "하이브리드",
    "specialist": "속성 특화",
    "outside": "비주류",
    "undetermined": "판단 보류",
}
OVERALL_KO = {"mean": "5속성 균등 평균", "frequency": "최근 등장 빈도 가중", "max": "최고 속성"}
CLASS_KO = {"Attacker": "화력형", "Supporter": "지원형", "Defender": "방어형"}
SLOT = {e: e.lower() for e in ELEMENTS}


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


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
    """One season's tiers: measured (a finished or live season) or expected."""

    season: Season | None
    number: int
    kind: str  # "finished", "live", "expected"
    rows: pd.DataFrame  # unit_id, name, value, tier, extra
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
    upcoming: SeasonBlock | None
    overall: pd.DataFrame
    final_seasons: list[int]
    config: tiering.TierConfig
    sample: Sample | None = None

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
                "units": b.rows.to_dict(orient="records"),
            }

        return {
            "moment": self.moment.isoformat(),
            "sample": self.sample.to_dict() if self.sample else None,
            "final_seasons": self.final_seasons,
            "finished": block(self.finished),
            "current": block(self.current),
            "upcoming": block(self.upcoming),
            "overall": self.overall.to_dict(orient="records"),
            "parameters": {
                "half_life_days": self.config.half_life_days,
                "overall": self.config.overall,
                "cuts": dict(self.config.cuts),
            },
        }


@dataclass
class UnitHistory:
    unit_id: str
    info: dict[str, Any]
    rows: pd.DataFrame
    profile: dict[str, Any] | None
    moment: datetime
    sample: Sample | None = None


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

    def _expected(self, season: Season, profiles: pd.DataFrame) -> SeasonBlock:
        slot = SLOT.get(season.weak_element)
        if slot is None or profiles.empty:
            return SeasonBlock(season, season.number, "expected", pd.DataFrame(), "약점 속성 미확인")
        rows = profiles[["unit_id", "name", f"lift_{slot}", f"tier_{slot}", f"n_{slot}", "role"]].rename(
            columns={f"lift_{slot}": "lift", f"tier_{slot}": "tier", f"n_{slot}": "observed"}
        )
        rows = rows.sort_values(["lift", "unit_id"], ascending=[False, True])
        note = f"{ELEMENT_KO.get(season.weak_element, season.weak_element)} 약점 시즌 기록으로 본 예상"
        return SeasonBlock(season, season.number, "expected", rows, note)

    def at(self, moment: datetime | str | None = None) -> TierView:
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        instant = _utc(moment)
        snapshot = self.timeline.at(moment)
        profiles = tiering.element_profiles(self.history, self.seasons, instant, self.config)
        if not profiles.empty:
            names = self.history.drop_duplicates("unit_id").set_index("unit_id")
            profiles = profiles.join(names[["name_ko", "name_en", "element", "unit_class"]], on="unit_id")
            profiles["name"] = [_name(r) for _, r in profiles.iterrows()]
        known = self.seasons[self.seasons["final"] & (self.seasons["end_at"] <= instant)]
        final_seasons = sorted(int(s) for s in known["season"])

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
                current = self._expected(snapshot.season, profiles)
        upcoming = self._expected(snapshot.next_season, profiles) if snapshot.next_season is not None else None
        return TierView(moment, finished, current, upcoming, profiles, final_seasons, self.config, self.sample)

    # ------------------------------------------------------------------

    def find_unit(self, query: str) -> str:
        return find_unit(query, self.history, self.index)

    def unit(self, query: str, moment: datetime | str | None = None) -> UnitHistory:
        unit_id = self.find_unit(query)
        moment = resolve_moment(moment) if moment is not None else datetime.now(tz=_kst())
        rows = self.history[self.history["unit_id"] == unit_id].sort_values("season")
        profiles = tiering.element_profiles(self.history, self.seasons, _utc(moment), self.config)
        match = profiles[profiles["unit_id"] == unit_id]
        info = rows.iloc[-1][["unit_id", "name_ko", "name_en", "element", "burst", "unit_class", "release_date"]].to_dict()
        return UnitHistory(unit_id, info, rows, match.iloc[0].to_dict() if not match.empty else None, moment,
                           self.sample)


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


def render(view: TierView, *, show_all: bool = False) -> str:
    config = view.config
    span = f"완료 시즌 {view.final_seasons[0]}–{view.final_seasons[-1]}" if view.final_seasons else "완료 시즌 없음"
    out = [
        f"{view.moment:%Y-%m-%d %H:%M} KST 기준 티어 · {span} · 최근 가중 반감기 {config.half_life_days:g}일",
        f"  표본: {view.sample or f'서버마다 상위 {config.top_n}위'}",
        "  lift: 표본 랭커의 대미지 중 그 니케 몫, 1.0 = 한 사람이 쓰는 25명의 평균 몫",
    ]
    upcoming = view.upcoming
    same_element = (
        upcoming is not None and view.current is not None and view.current.kind == upcoming.kind == "expected"
        and upcoming.season is not None and view.current.season is not None
        and upcoming.season.weak_element == view.current.season.weak_element
    )
    for block, label in ((view.finished, "직전"), (view.current, "진행 중"), (None if same_element else upcoming, "다음")):
        if block is None:
            continue
        out += ["", _season_head(block, label)]
        if same_element and block is view.current:
            out.append(f"  (다음 시즌 {upcoming.number}도 같은 약점 — 예상은 같다)")
        if block.rows.empty:
            out.append("  (기록 없음)")
            continue
        if block.kind != "expected":
            out += _tier_lines(block.rows, "lift", "tier", config, show_all=show_all)
            continue
        seen = block.rows[block.rows["observed"] > 0]
        out += _tier_lines(seen, "lift", "tier", config, show_all=show_all)
        unseen = block.rows[(block.rows["observed"] == 0) & (block.rows["lift"] >= config.cut("B"))]
        if not unseen.empty:
            weak = _element(block.season.weak_element) if block.season else "?"
            out.append(f"  미관측 {weak} 약점 시즌을 아직 겪지 않음: " + " · ".join(unseen["name"]))

    if not view.overall.empty:
        out += ["", f"■ 종합 티어 ({OVERALL_KO.get(config.overall, config.overall)}) · 괄호 = 역할"]
        overall = view.overall.rename(columns={"overall_tier": "tier_o"})

        def mark(r: pd.Series) -> str:
            role = ROLE_KO.get(r["role"], r["role"])
            return f"*({role})" if bool(r["provisional"]) else f"({role})"

        out += _tier_lines(overall, "overall", "tier_o", config, show_all=show_all, mark=mark)
        out.append(f"  * = 관측한 약점 속성이 {config.min_elements_observed}개 미만이라 잠정")
    return "\n".join(out)


def render_unit(history: UnitHistory, config: tiering.TierConfig | None = None) -> str:
    config = config or tiering.load_tier_config()
    info = history.info
    name = info.get("name_ko") or info.get("name_en")
    out = [
        f"{name} ({info.get('name_en', '')}) · {_element(info.get('element', ''))} "
        f"{CLASS_KO.get(info.get('unit_class', ''), info.get('unit_class', ''))} · "
        f"버스트 {info.get('burst', '')} · 출시 {info.get('release_date', '')}"
    ]
    if history.sample is not None and history.sample.chosen:
        out.append(f"표본: {history.sample}")
    profile = history.profile
    if profile:
        role = ROLE_KO.get(profile["role"], profile["role"])
        provisional = " (잠정)" if bool(profile.get("provisional")) else ""
        out.append(
            f"{history.moment:%Y-%m-%d} 기준: 종합 {profile['overall_tier']} {profile['overall']:.2f}{provisional} · {role} · "
            f"최고 {_element(profile['best_element'])} {profile['best_tier']} {profile['best_lift']:.2f} · "
            f"A 이상 {int(profile['coverage'])}/{int(profile['elements_observed'])} 속성"
        )
        slots = []
        for element in ELEMENTS:
            slot = SLOT[element]
            observed = int(profile[f"n_{slot}"])
            value = f"{profile[f'tier_{slot}']} {profile[f'lift_{slot}']:.2f}" if observed else f"? {profile[f'lift_{slot}']:.2f}"
            slots.append(f"{_element(element)} {value} ({observed})")
        out.append("  속성별  " + " · ".join(slots) + "   (괄호 = 관측 시즌 수, ? = 미관측)")
    out += [
        "",
        f"{rjust('시즌', 4)}  {pad('시작', 10)}  {pad('보스 · 약점', 30)}  {rjust('채용', 5)}  {rjust('덱 몫', 5)}  "
        f"{rjust('메인', 5)}  {rjust('lift', 5)}  {pad('시즌', 4)}  종합",
    ]
    for _, row in history.rows.iterrows():
        used = row["presence"] > 0
        start = pd.Timestamp(row["start_at"]).tz_convert("Asia/Seoul") if isinstance(row["start_at"], str) and row["start_at"] else None
        boss_name = row["boss_en"] if isinstance(row["boss_en"], str) and row["boss_en"] else "?"
        boss = f"{boss_name} · {_element(row['weak_element'] if isinstance(row['weak_element'], str) else '')}"
        deck_share = f"{row['deck_share']:.0%}" if used and pd.notna(row["deck_share"]) else "-"
        main = f"{row['main_deck_rate']:.0%}" if used and pd.notna(row["main_deck_rate"]) else "-"
        overall = f"{row['overall_tier']} {row['overall']:.2f}" if pd.notna(row.get("overall")) else "-"
        live = "" if bool(row.get("final", True)) else " (진행 중)"
        out.append(
            f"{int(row['season']):>4}  {pad(f'{start:%Y-%m-%d}' if start is not None else '', 10)}  {pad(boss, 30)}  "
            f"{row['presence']:>5.0%}  {deck_share:>5}  {main:>5}  {row['lift']:>5.2f}  {pad(str(row['tier']), 4)}  {overall}{live}"
        )
    return "\n".join(out)
