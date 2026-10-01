"""One Solo Raid season's usage: who was fielded, how often, and in which deck.

    nikke raid                     the newest season with rankings
    nikke raid 40                  season 40: units by usage, with the deck split
    nikke raid 2주년               the season open (or last closed) at a moment
    nikke raid 40 크라운           one unit: usage, rank, deck split
    nikke raid 크라운              the same, in the newest season
    nikke raid 40 --server KR      one server (repeat, or comma-separate, for more)
    nikke raid 40 --exclude NA,SEA every server but these
    nikke raid 40 --top 10         ranks 1..10 of each server
    nikke raid 40 --all            also the units available then that nobody fielded

The numbers (docs/metrics.md):

* **usage** - how many ranked players fielded the unit. A unit fits in only one
  of a player's decks, so this is also its number of decks. **Usage rate** is
  that over the players in the sample.
* **deck split** - where those players had it, by deck rank: their decks ordered
  by the damage they dealt, deck 1 the strongest. The five add up to the usage.
  A deck that dealt no damage was not fought and does not count.

This is the raw count behind the tiers (``nikke tier``), which weigh the same
decks by the damage they did.

The whole sample (every server's top 50) reads the committed
``metrics_unit_season.csv``. A narrower one (``--server``, ``--exclude``,
``--top``) is recomputed from ``raid_entries.csv``, which ``nikke build raids``
rebuilds from the committed snapshots in a few seconds. Server names take any
case and Korean (``한국``, ``대만``); see ``servers.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .analyze import metrics, tiers
from .paths import processed_dir
from .servers import ServerError, ServerFilter, describe, ordered
from .tierlist import ELEMENT_KO, find_unit, load_index
from .timeline import Season, Timeline, resolve_moment
from .util.kdate import KST
from .util.names import NameIndex
from .util.text import pad, rjust, width

SPLIT = metrics.DECK_SPLIT


class QueryError(LookupError):
    """A season, server or name that does not pick out one thing; the message says why."""


@dataclass
class SeasonUsage:
    number: int
    season: Season | None
    rows: pd.DataFrame  # every unit available that season, most used first
    rankers: int
    decks: int
    servers: int  # how many servers the sample spans
    server_filter: ServerFilter  # how they were chosen; empty = every server
    top: int | None
    collected_on: str
    final: bool
    server_names: tuple[str, ...] = ()  # the servers in the sample

    @property
    def used(self) -> pd.DataFrame:
        return self.rows[self.rows["rankers"] > 0]

    def to_dict(self, *, include_unused: bool = False) -> dict[str, Any]:
        rows = self.rows if include_unused else self.used
        return {
            "season": self.number,
            "boss_en": self.season.boss_en if self.season else "",
            "boss_ko": self.season.boss_ko if self.season else "",
            "weak_element": self.season.weak_element if self.season else "",
            "servers": self.servers,
            "server_names": list(self.server_names),
            "server_filter": self.server_filter.to_dict(),
            "top": self.top,
            "rankers": self.rankers,
            "decks": self.decks,
            "collected_on": self.collected_on,
            "final": self.final,
            "pool": len(self.rows),
            "units": [unit_record(row) for _, row in rows.iterrows()],
        }


def unit_record(row: pd.Series) -> dict[str, Any]:
    users = int(row["rankers"])
    return {
        "unit_id": row["unit_id"],
        "name_ko": row.get("name_ko", ""),
        "name_en": row.get("name_en", ""),
        "users": users,
        "usage_rate": round(float(row["usage_rate"]), 4),
        "usage_rank": int(row["usage_rank"]),
        "decks": [int(row[c]) for c in SPLIT],
        "deck_shares": [round(int(row[c]) / users, 4) if users else None for c in SPLIT],
        "avg_deck": None if pd.isna(row["avg_deck"]) else round(float(row["avg_deck"]), 2),
        "lift": round(float(row["lift"]), 4),
        "tier": row.get("tier", ""),
    }


def _read(path: Path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"unit_id": str}, keep_default_na=False, na_values=[""])


class RaidBook:
    def __init__(
        self,
        table: pd.DataFrame,
        seasons: pd.DataFrame,
        timeline: Timeline,
        *,
        directory: Path,
        index: NameIndex | None = None,
        config: tiers.TierConfig | None = None,
    ):
        self.table = table
        self.seasons = seasons
        self.timeline = timeline
        self.directory = directory
        self.index = index
        self.config = config or tiers.load_tier_config()
        self._loaded: dict[str, pd.DataFrame] | None = None

    @classmethod
    def load(cls, data_dir: Path | None = None, config: tiers.TierConfig | None = None) -> "RaidBook":
        directory = data_dir or processed_dir()
        table = _read(directory / "metrics_unit_season.csv")
        seasons = _read(directory / "metrics_seasons.csv")
        if table.empty or seasons.empty:
            raise QueryError("no metric tables; run `nikke build raids` and `nikke analyze` first")
        return cls(table, seasons, Timeline.load(directory), directory=directory, index=load_index(directory), config=config)

    # ------------------------------------------------------------------

    def numbers(self) -> list[int]:
        return sorted(int(s) for s in self.seasons["season"])

    @staticmethod
    def names_a_season(text: str) -> bool:
        """Whether ``text`` is a season number or a moment rather than, say, a unit name."""
        if re.fullmatch(r"\d{1,3}", text.strip()):
            return True
        try:
            resolve_moment(text)
        except ValueError:
            return False
        return True

    def season_of(self, query: str | int | None) -> int:
        """``40``, a moment (``2024-11-04``, ``2주년``: the season open then, else
        the last one closed), or nothing (the newest season with rankings)."""
        numbers = self.numbers()
        if query is None or str(query).strip() == "":
            return numbers[-1]
        text = str(query).strip()
        if re.fullmatch(r"\d{1,3}", text):
            number = int(text)
        else:
            view = self.timeline.at(resolve_moment(text))
            season = view.season or view.previous_season
            if season is None:
                raise QueryError(f"{text} 에는 끝났거나 진행 중인 솔로 레이드 시즌이 없다")
            number = season.number
        if number not in numbers:
            raise QueryError(
                f"시즌 {number} 의 랭킹이 없다 (있는 시즌: {numbers[0]}–{numbers[-1]}). "
                "새 시즌은 enikk 가 수집을 시작한 뒤 `nikke collect enikk` 로 들어온다"
            )
        return number

    def parse(self, first: str | None, second: str | None) -> tuple[int, str | None]:
        """``(season, unit)`` from ``nikke raid [season-or-moment] [unit]``, in either
        order, or ``nikke raid [unit]``."""
        if first is not None and not self.names_a_season(first):
            if second is None:
                return self.season_of(None), first
            if not self.names_a_season(second):
                raise QueryError(f"'{first}' 도 '{second}' 도 시즌 번호나 날짜가 아니다 (예: 40, 2024-11-04, 2주년)")
            first, second = second, first
        return self.season_of(first), second

    def _inputs(self) -> dict[str, pd.DataFrame]:
        """raid_entries (Solo Raid only), the roster, the season table and the 체급 the decks are split by
        (measured on every deck, like the committed table's), read once."""
        if self._loaded is None:
            from . import power
            from .analyze.pipeline import load_inputs

            if not (self.directory / "raid_entries.csv").is_file():
                raise QueryError("서버·순위로 좁히려면 raid_entries.csv 가 필요하다: `nikke build raids` (오프라인, 몇 초)")
            inputs = load_inputs(self.directory)
            entries = inputs["entries"]
            if "content" in entries.columns:
                inputs["entries"] = entries[entries["content"] == "soloraid"]
            inputs["split"] = power.split_weights(inputs["entries"], inputs["roster"], inputs["seasons"])
            self._loaded = inputs
        return self._loaded

    def season(
        self,
        number: int,
        *,
        servers: Iterable[str] | str = (),
        exclude: Iterable[str] | str = (),
        top: int | None = None,
    ) -> SeasonUsage:
        """One season's usage; ``servers`` (only these), ``exclude`` (all but
        these) and ``top`` narrow the sample. Server names replace the configured
        server choice; ``top`` alone keeps it."""
        asked = ServerFilter.of(servers, exclude)
        chosen = asked or self.config.server_filter
        summary = self.seasons[self.seasons["season"].astype(int) == number].iloc[0]
        if not asked and not top:
            rows = self.table[self.table["season"].astype(int) == number]
            rankers, decks = int(summary["rankers"]), int(summary["decks"])
            spanned = int(summary["servers"])
            names = summary.get("server_names")
            served = tuple(n for n in names.split(";") if n) if isinstance(names, str) else ()
        else:
            inputs = self._inputs()
            everywhere = inputs["entries"]["server"].unique()
            entries = inputs["entries"][inputs["entries"]["season"] == number]
            here = ordered(entries["server"].unique())
            try:
                chosen.check(everywhere)
            except ServerError as exc:
                raise QueryError(str(exc)) from None
            missing = [s for s in chosen.include if s not in here]
            if missing:
                raise QueryError(f"시즌 {number} 에 없는 서버: {', '.join(missing)} (있는 서버: {', '.join(here)})")
            population = metrics.select_population(
                entries, top_n=top or self.config.top_n, servers=chosen.include, exclude=chosen.exclude
            )
            if population.empty:
                raise QueryError(f"시즌 {number} 에서 그 조건에 맞는 랭커가 없다")
            rows = metrics.unit_season(population, inputs["roster"], inputs["seasons"],
                                       weighting=self.config.rank_weighting, ridge=self.config.deck_effect_ridge,
                                       split=inputs["split"])
            rows = tiers.season_tiers(rows, self.config)
            decks_table = metrics.deck_table(population)
            rankers, decks = decks_table.drop_duplicates(metrics.RANKER_KEYS).shape[0], len(decks_table)
            served = tuple(ordered(population["server"].unique()))
            spanned = len(served)
        rows = rows.sort_values(["usage_rank", "avg_deck", "unit_id"], na_position="last").reset_index(drop=True)
        collected = pd.Timestamp(summary["collected_on"]) if summary.get("collected_on") else None
        final = str(summary["final"]).lower() in ("true", "1")
        return SeasonUsage(
            number=number,
            season=self.timeline.season(number),
            rows=rows,
            rankers=rankers,
            decks=decks,
            servers=spanned,
            server_filter=chosen,
            top=top,
            collected_on=collected.tz_convert("Asia/Seoul").date().isoformat() if collected is not None and collected.tzinfo else (str(summary["collected_on"])[:10]),
            final=final,
            server_names=served,
        )

    def unit(self, usage: SeasonUsage, query: str) -> pd.Series:
        """One unit's row in ``usage``; a unit not yet released then raises, saying when it came."""
        try:
            unit_id = find_unit(query, usage.rows, self.index)
        except LookupError:
            unit_id = find_unit(query, self.table, self.index)  # exists, just not in this season
            release = self.table.loc[self.table["unit_id"] == unit_id, "release_date"].iloc[0]
            name = self.table.loc[self.table["unit_id"] == unit_id, "name_ko"].iloc[0]
            raise QueryError(f"{name} 은(는) 시즌 {usage.number} 당시 아직 출시 전이었다 ({release} 출시)") from None
        return usage.rows[usage.rows["unit_id"] == unit_id].iloc[0]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _element(value: str) -> str:
    return ELEMENT_KO.get(value, value) or "?"


def _percent(value: float | None) -> str:
    return "" if value is None or pd.isna(value) else f"{value * 100:.1f}%"


def _name(row: pd.Series) -> str:
    ko, en = row.get("name_ko"), row.get("name_en")
    return str(ko) if isinstance(ko, str) and ko else str(en or row["unit_id"])


def _header(usage: SeasonUsage) -> list[str]:
    season = usage.season
    head = f"솔로 레이드 시즌 {usage.number}"
    if season is not None:
        head += f" · {season.boss} · 보스 {_element(season.element)} / 약점 {_element(season.weak_element)}"
        if season.start and season.end:
            head += f" · {season.start:%Y-%m-%d} ~ {season.end:%m-%d}"
    where = describe(usage.server_filter, usage.server_names) if usage.server_names else f"{usage.servers}개 서버"
    scope = f"{usage.top}위까지" if usage.top else "상위 50위"
    sample = f"표본  {where} {scope} = {usage.rankers:,}명 · 덱 {usage.decks:,}개 (enikk {usage.collected_on} 수집"
    if usage.final:
        sample += ")"
    elif season is not None and season.end and datetime.now(KST) >= season.end:
        sample += ", 끝났지만 끝난 뒤의 순위를 아직 못 받은 집계 대기라 그때까지의 순위)"
    else:
        sample += ", 진행 중인 시즌이라 그때까지의 순위)"
    return [head, sample]


def _row(rank: str, name: str, users: str, rate: str, shares: list[str], average: str, tier: str, *, names: int) -> str:
    cells = [rjust(rank, 4), pad(name, names), rjust(users, 5), rjust(rate, 7), *(rjust(x, 7) for x in shares)]
    return " ".join(cells) + "  " + rjust(average, 5) + "  " + tier


def render_season(usage: SeasonUsage, *, include_unused: bool = False) -> str:
    rows = usage.rows if include_unused else usage.used
    names = max([width(_name(row)) for _, row in rows.iterrows()] + [4])
    lines = _header(usage)
    lines.append(f"당시 니케 풀 {len(usage.rows)}명 중 {len(usage.used)}명 사용")
    lines += [
        "",
        "덱 순위 = 한 사람의 덱 5개를 딜량 순으로 세운 순서 (1덱 = 딜량 1등 덱)",
        "1덱~5덱 = 그 니케를 쓴 사람 중 그 덱에 넣은 비율 · 평균 = 평균 덱 순위 · 티어 = 이 표본의 시즌 티어와 기여도",
        "기여도 = 랭커 대미지를 덱에 든 니케끼리 나눠 가진 몫 (25명이 똑같이 나누면 1.0, 0 = 아무도 안 씀)",
        "",
        _row("순위", "니케", "사용", "사용률", [f"{d}덱" for d in metrics.DECK_RANKS], "평균", "티어", names=names),
    ]
    for _, row in rows.iterrows():
        users = int(row["rankers"])
        shares = [("-" if int(row[c]) == 0 else _percent(int(row[c]) / users)) if users else "" for c in SPLIT]
        lines.append(
            _row(
                str(int(row["usage_rank"])),
                _name(row),
                str(users),
                _percent(row["usage_rate"]),
                shares,
                "" if pd.isna(row["avg_deck"]) else f"{row['avg_deck']:.2f}",
                f"{row['tier']} {row['lift']:.2f}",
                names=names,
            )
        )
    return "\n".join(lines)


def _bar(share: float, width: int = 20) -> str:
    filled = round(share * width)
    return "█" * filled + "░" * (width - filled)


def render_unit(usage: SeasonUsage, row: pd.Series) -> str:
    lines = _header(usage) + [""]
    name = _name(row)
    english = row.get("name_en") if isinstance(row.get("name_en"), str) else ""
    lines.append(f"{name} ({english})" if english and english != name else name)
    users = int(row["rankers"])
    if users == 0:
        lines.append(f"  시즌 {usage.number} 에 이 표본에서 쓴 사람 없음 (당시 출시돼 있었음)")
        return "\n".join(lines)
    tied = int((usage.rows["usage_rank"] == row["usage_rank"]).sum())
    rank = f"사용률 {int(row['usage_rank'])}위" + (f" (공동 {tied}명)" if tied > 1 else "")
    lines.append(f"  사용       {users:,}명 / {usage.rankers:,}명 ({_percent(row['usage_rate'])}) · {rank}")
    for deck, column in zip(metrics.DECK_RANKS, SPLIT):
        share = int(row[column]) / users
        label = "  덱 순위   " if deck == 1 else "             "
        lines.append(f"{label}{deck}덱 {_bar(share)} {rjust(_percent(share), 6)}  ({int(row[column])}명)")
    lines.append(f"  평균 덱 순위 {row['avg_deck']:.2f}")
    lines.append(f"  시즌 티어  {row['tier']} (기여도 {row['lift']:.2f}) — 시즌별 변화는 `nikke tier --unit {name}`")
    return "\n".join(lines)
