"""Turning measurements into tiers: per season, in a unit's own element, and overall.

A tier list is an opinion. Deriving one from data does not make it more correct
than a good player's; it makes it *reproducible* - same input, same tiers, with
the reasoning visible as numbers instead of hidden in a judgement call. Every
judgement that remains is a parameter in ``config/tiers.yaml``.

Three tiers answer three different questions:

**Season tier** - how much a unit carried in one season: fixed cuts on its lift.
Fixed cuts, not percentiles, so the number of SS units is itself information: a
season one deck dominates has five, a season with no dominant deck may have none.

**Element tier** - how much a unit is worth in its own element: its recent lift
in the seasons whose boss was weak to the unit's element, the seasons that
element's decks are built for. Solo Raid's meta turns on the boss's weakness,
and more so every year. Recent seasons count more (``half_life_days``). A unit
that has not met such a season since its release has no element tier yet. A
unit whose skill gives it a second element's weakness advantage (우월 코드: the
roster's ``extra_elements``, from data/manual/extra_elements.csv) counts as
both elements and has a tier in each.

**Overall tier** - how much a unit is worth across the whole rotation. Its recent
lift is estimated per boss weakness - five internal slots, Fire, Water, Wind,
Iron and Electric - and the slots are averaged (``overall``), so a unit's
standing does not depend on which elements happened to come up lately. The
slots follow the *boss's* weakness, not the unit's own element, because supports
follow the element of the deck they support: a Water support fielded only in
Wind-weak seasons earns its overall there, while its element tier (Water) stays
low. A slot with no season since the unit's release borrows the unit's level
over all seasons.

The two read together: high in its element and low overall is a specialist,
high in both a unit that goes anywhere, low in its element and high overall a
support that carries other elements' decks.

A unit seen in fewer than ``min_elements_observed`` elements is ``provisional``:
its unobserved slots borrow its level from the elements it was seen in, which
flatters a specialist, so its overall tier is shown but marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ..paths import REPO_ROOT
from ..servers import ServerFilter, split
from .metrics import ELEMENTS, season_order

DEFAULT_TIER_CONFIG = REPO_ROOT / "config" / "tiers.yaml"

# Ordered best -> worst: (label, minimum lift).
DEFAULT_CUTS: list[tuple[str, float]] = [
    ("SS", 1.4),
    ("S", 1.1),
    ("A", 0.8),
    ("B", 0.5),
    ("C", 0.2),
    ("D", 0.0),
]
OVERALL_MODES = ("mean", "max", "frequency")


@dataclass
class TierConfig:
    # population
    top_n: int = 50
    servers: tuple[str, ...] = ()  # () = every server
    exclude_servers: tuple[str, ...] = ()
    rank_weighting: str = "dcg"
    # season tier
    cuts: list[tuple[str, float]] = field(default_factory=lambda: list(DEFAULT_CUTS))
    # element and overall tiers
    half_life_days: float = 180.0
    prior_strength: float = 0.0
    overall: str = "mean"
    min_elements_observed: int = 3
    # diagnostics
    deck_effect_ridge: float = 20.0
    synergy_min_decks: int = 20

    def __post_init__(self) -> None:
        self.cuts = sorted(((str(l), float(v)) for l, v in self.cuts), key=lambda c: c[1], reverse=True)
        if self.overall not in OVERALL_MODES:
            raise ValueError(f"element.overall must be one of {OVERALL_MODES}, not {self.overall!r}")

    @property
    def server_filter(self) -> ServerFilter:
        return ServerFilter(self.servers, self.exclude_servers)

    def with_servers(self, chosen: ServerFilter) -> "TierConfig":
        """The same parameters on another server sample (replacing, not narrowing, this one's)."""
        return replace(self, servers=chosen.include, exclude_servers=chosen.exclude)

    @property
    def tier_order(self) -> list[str]:
        return [label for label, _ in self.cuts]

    def cut(self, label: str) -> float:
        return dict(self.cuts)[label]


def load_tier_config(path: Path | None = None) -> TierConfig:
    target = path or DEFAULT_TIER_CONFIG
    if not target.is_file():
        return TierConfig()
    doc: dict[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    population = doc.get("population") or {}
    element = doc.get("element") or {}
    diagnostics = doc.get("diagnostics") or {}
    defaults = TierConfig()
    cuts = doc.get("cuts")
    return TierConfig(
        top_n=int(population.get("top_n", defaults.top_n)),
        servers=split(population.get("servers") or ()),
        exclude_servers=split(population.get("exclude_servers") or ()),
        rank_weighting=str(population.get("rank_weighting", defaults.rank_weighting)),
        cuts=[(str(c["label"]), float(c["min_lift"])) for c in cuts] if cuts else list(DEFAULT_CUTS),
        half_life_days=float(element.get("half_life_days", defaults.half_life_days)),
        prior_strength=float(element.get("prior_strength", defaults.prior_strength)),
        overall=str(element.get("overall", defaults.overall)),
        min_elements_observed=int(element.get("min_elements_observed", defaults.min_elements_observed)),
        deck_effect_ridge=float(diagnostics.get("deck_effect_ridge", defaults.deck_effect_ridge)),
        synergy_min_decks=int(diagnostics.get("synergy_min_decks", defaults.synergy_min_decks)),
    )


def assign_tier(value: float, config: TierConfig | None = None) -> str:
    config = config or TierConfig()
    if value is None or pd.isna(value):
        return ""
    for label, minimum in config.cuts:
        if value >= minimum:
            return label
    return config.cuts[-1][0]


def tier_rank(label: str, config: TierConfig | None = None) -> int:
    """0 for the best tier; unknown labels sort last."""
    order = (config or TierConfig()).tier_order
    return order.index(label) if label in order else len(order)


# --------------------------------------------------------------------------
# where every unit stands: its element tiers and its overall tier
# --------------------------------------------------------------------------

OVERALL_COLUMNS = ["unit_id", "overall", "overall_tier", "overall_rank", "provisional", "elements_observed",
                   "seasons_observed", "last_season"]
ELEMENT_COLUMNS = ["unit_id", "element", "source", "element_lift", "element_tier", "element_seasons", "element_rank"]


@dataclass
class Standings:
    """Where every unit stands at one moment.

    ``overall``: one row per unit, its overall tier, best first. ``elements``:
    one row per unit and element it counts as - its own (``source`` "own") and
    any its skill adds (``source`` "skill", ``extra_elements``) - with its
    tier in that element, element by element and best first; an element the
    unit has not met since its release has no tier yet (``element_seasons`` 0).
    ``overall_rank`` ranks a unit among all units, ``element_rank`` among the
    units of that element; 1 is the best.
    """

    overall: pd.DataFrame
    elements: pd.DataFrame


def _decay(ages_days: pd.Series, half_life_days: float) -> pd.Series:
    if half_life_days <= 0:
        return pd.Series(1.0, index=ages_days.index)
    return 0.5 ** (ages_days.clip(lower=0) / half_life_days)


def unit_elements(table: pd.DataFrame) -> pd.DataFrame:
    """Every element each unit counts as, one row per unit and element (``unit_id``,
    ``element``, ``source``), from the roster columns of the season table: its
    own ``element``, then the ``extra_elements`` its skill adds ("Iron;Water")."""
    columns = ["unit_id", "element", "source"]
    if table.empty or "element" not in table.columns:
        return pd.DataFrame(columns=columns)
    units = table.drop_duplicates("unit_id")
    own = units[["unit_id", "element"]].assign(source="own")
    frames = [own]
    if "extra_elements" in units.columns:
        extra = units[["unit_id", "extra_elements"]].assign(element=units["extra_elements"].fillna("").astype(str)
                                                            .str.split(";")).explode("element")
        frames.append(extra[["unit_id", "element"]].assign(source="skill"))
    members = pd.concat(frames, ignore_index=True)
    members = members[members["element"].isin(ELEMENTS)]
    return members.drop_duplicates(["unit_id", "element"]).reset_index(drop=True)


def standings(
    table: pd.DataFrame,
    seasons: pd.DataFrame,
    moment: pd.Timestamp,
    config: TierConfig | None = None,
) -> Standings:
    """Every unit's element tiers and overall tier, as known at ``moment``.

    Only seasons that were over by ``moment`` count: the view of the past never
    uses what happened after it. ``table`` is the season x unit table (with each
    unit's own ``element``) and ``seasons`` the season summary (it says which
    seasons are final).
    """
    config = config or TierConfig()
    moment = pd.Timestamp(moment)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    final = seasons.loc[seasons["final"].astype(bool) & (seasons["end_at"] <= moment), ["season", "end_at", "weak_element"]]
    rows = table.loc[table["season"].isin(final["season"]), ["season", "unit_id", "lift"]].merge(final, on="season")
    rows = rows[rows["weak_element"].isin(ELEMENTS)]
    if rows.empty:
        return Standings(pd.DataFrame(columns=OVERALL_COLUMNS), pd.DataFrame(columns=ELEMENT_COLUMNS))

    rows = rows.assign(w=_decay((moment - rows["end_at"]).dt.total_seconds() / 86400.0, config.half_life_days))
    rows["wl"] = rows["w"] * rows["lift"]
    unit = rows.groupby("unit_id").agg(W=("w", "sum"), WL=("wl", "sum"), seasons_observed=("season", "size"),
                                       last_season=("season", "max"))
    prior = unit["WL"] / unit["W"]
    slot = rows.groupby(["unit_id", "weak_element"]).agg(W=("w", "sum"), WL=("wl", "sum"), n=("w", "size"))
    mean = (slot["WL"] / slot["W"]).unstack().reindex(columns=list(ELEMENTS))
    count = slot["n"].unstack().reindex(index=unit.index, columns=list(ELEMENTS)).fillna(0).astype(int)

    # One slot per boss weakness; a slot not observed since release borrows the unit's level.
    k = config.prior_strength
    estimate = pd.DataFrame(index=unit.index)
    for element in ELEMENTS:
        n = count[element]
        m = mean[element].reindex(unit.index)
        shrunk = (n * m.fillna(0) + k * prior) / (n + k) if k > 0 else m
        estimate[element] = np.where(n > 0, shrunk, prior)

    # Element tiers: the slots of the elements a unit counts as, once observed.
    members = unit_elements(table)
    members = members[members["unit_id"].isin(unit.index)].reset_index(drop=True)
    at = (unit.index.get_indexer(members["unit_id"]), [ELEMENTS.index(e) for e in members["element"]])
    seen = count.to_numpy()[at] if len(members) else np.zeros(0, dtype=int)
    lifts = estimate.to_numpy()[at] if len(members) else np.zeros(0)
    elements = members.assign(element_lift=np.where(seen > 0, lifts, np.nan), element_seasons=seen.astype(int))
    elements["element_tier"] = elements["element_lift"].map(lambda v: assign_tier(v, config))
    elements["element_rank"] = (elements.groupby("element")["element_lift"]
                                .rank(method="min", ascending=False).astype("Int64"))
    elements["position"] = elements["element"].map(ELEMENTS.index)
    elements = elements.sort_values(["position", "element_lift", "unit_id"], ascending=[True, False, True],
                                    na_position="last")

    observed = count > 0
    overall = pd.DataFrame(index=unit.index)
    if config.overall == "mean":
        overall["overall"] = estimate.mean(axis=1)
    elif config.overall == "max":
        overall["overall"] = estimate.where(observed).max(axis=1)
    else:  # frequency: weight each element by how often (recently) the boss was weak to it
        ages = (moment - final["end_at"]).dt.total_seconds() / 86400.0
        freq = _decay(ages, config.half_life_days).groupby(final["weak_element"].to_numpy()).sum()
        freq = freq.reindex(list(ELEMENTS)).fillna(0.0)
        freq = freq / freq.sum() if freq.sum() > 0 else pd.Series(1.0 / len(ELEMENTS), index=list(ELEMENTS))
        overall["overall"] = estimate.mul(freq, axis=1).sum(axis=1)
    overall["overall_tier"] = overall["overall"].map(lambda v: assign_tier(v, config))
    overall["overall_rank"] = overall["overall"].rank(method="min", ascending=False).astype("Int64")
    n_obs = observed.sum(axis=1).astype(int)
    overall["provisional"] = n_obs < config.min_elements_observed
    overall["elements_observed"] = n_obs
    overall["seasons_observed"] = unit["seasons_observed"].astype(int)
    overall["last_season"] = unit["last_season"].astype(int)
    overall = overall.reset_index()[OVERALL_COLUMNS]
    overall = overall.sort_values(["overall", "unit_id"], ascending=[False, True]).reset_index(drop=True)
    return Standings(overall, elements[ELEMENT_COLUMNS].reset_index(drop=True))


# --------------------------------------------------------------------------
# season tiers and their history
# --------------------------------------------------------------------------

def season_tiers(table: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    config = config or TierConfig()
    out = table.copy()
    out["tier"] = out["lift"].map(lambda v: assign_tier(v, config))
    return out


def tier_history(table: pd.DataFrame, seasons: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """The season table with where each unit stood once that season was over.

    Row (season s, unit u) carries what u did in s (``lift``, ``tier``) and its
    overall tier once s was over. When s's boss was weak to an element u counts
    as, the row also carries u's tier in that element once s was over
    (``element_lift``, ``element_tier``, ``element_seasons``); in other seasons
    those are empty. For the season still in progress it is where u stood after
    the last finished season: the live season's own numbers are provisional.
    """
    config = config or TierConfig()
    parts = []
    by_season = seasons.set_index("season")
    for season in season_order(table["season"]):
        info = by_season.loc[season]
        moment = info["end_at"] if bool(info["final"]) else info["collected_until"]
        if pd.isna(moment):
            continue
        standing = standings(table, seasons, moment, config)
        overall = standing.overall.drop(columns=["overall_rank", "seasons_observed", "last_season"])
        element = standing.elements.drop(columns=["source", "element_rank"]).rename(columns={"element": "weak_element"})
        rows = table[table["season"] == season].merge(overall, on="unit_id", how="left")
        parts.append(rows.merge(element, on=["unit_id", "weak_element"], how="left"))
    history = pd.concat(parts, ignore_index=True) if parts else table.copy()
    history["final"] = history["season"].map(by_season["final"]).astype(bool)
    return history


def _has_tier(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _steps(before: Any, after: Any, config: TierConfig) -> int:
    """Tiers moved from ``before`` to ``after``, positive for a promotion; 0 when either is missing."""
    if not (_has_tier(before) and _has_tier(after)):
        return 0
    return tier_rank(before, config) - tier_rank(after, config)


def tier_changes(history: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Units whose season, element or overall tier moved between consecutive seasons.

    ``steps`` and ``overall_steps`` compare the two seasons' rows. An element
    tier moves in a season of that element: ``element`` is the season's weak
    element when the unit counts as it, and ``element_steps`` compares the
    unit's tier there once the season was over with where it stood before
    (after the last season of that element). A unit's first season of an
    element gives it a tier there; that is not a move. Steps are positive for a
    promotion. This is the table that answers "what did this season change".
    """
    config = config or TierConfig()
    columns = ["unit_id", "name_ko", "name_en", "weak_element", "lift", "tier", "element_lift", "element_tier",
               "overall", "overall_tier"]
    stood: dict[tuple[str, str], tuple[str, float]] = {}  # (unit, element) -> tier and lift there so far
    rows = []
    before, before_season = None, None
    for season in season_order(history["season"]):
        after = history.loc[history["season"] == season, columns].set_index("unit_id")
        if before is not None:
            both = before.join(after, lsuffix="_from", rsuffix="_to", how="inner")
            for unit_id, row in both.iterrows():
                steps = _steps(row["tier_from"], row["tier_to"], config)
                overall_steps = _steps(row["overall_tier_from"], row["overall_tier_to"], config)
                element = row["weak_element_to"] if _has_tier(row["element_tier_to"]) else ""
                was_tier, was_lift = stood.get((unit_id, element), ("", np.nan))
                element_steps = _steps(was_tier, row["element_tier_to"], config) if element else 0
                if steps == 0 and element_steps == 0 and overall_steps == 0:
                    continue
                rows.append(
                    {
                        "season_from": before_season,
                        "season_to": season,
                        "unit_id": unit_id,
                        "name_ko": row["name_ko_to"],
                        "name_en": row["name_en_to"],
                        "tier_from": row["tier_from"],
                        "tier_to": row["tier_to"],
                        "steps": steps,
                        "lift_from": row["lift_from"],
                        "lift_to": row["lift_to"],
                        "element": element,
                        "element_tier_from": was_tier,
                        "element_tier_to": row["element_tier_to"] if element else "",
                        "element_steps": element_steps,
                        "element_lift_from": was_lift,
                        "element_lift_to": row["element_lift_to"] if element else np.nan,
                        "overall_tier_from": row["overall_tier_from"],
                        "overall_tier_to": row["overall_tier_to"],
                        "overall_steps": overall_steps,
                        "overall_from": row["overall_from"],
                        "overall_to": row["overall_to"],
                    }
                )
        for unit_id, row in after.iterrows():
            if _has_tier(row["element_tier"]):
                stood[(unit_id, row["weak_element"])] = (row["element_tier"], row["element_lift"])
        before, before_season = after, season
    return pd.DataFrame(rows)


def summarise(history: pd.DataFrame, config: TierConfig | None = None) -> dict[str, Any]:
    config = config or TierConfig()
    if history.empty:
        return {}
    latest = max(history["season"])
    counts = history[history["season"] == latest]["tier"].value_counts()
    return {
        "latest_season": int(latest),
        "latest_tier_counts": {label: int(counts.get(label, 0)) for label in config.tier_order},
    }
