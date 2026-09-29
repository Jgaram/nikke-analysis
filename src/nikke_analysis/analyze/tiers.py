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
both elements and has a tier in each. One whose treasure's skill gave it the
second element (``treasure_elements``) counts as both on the treasure side only.

**Overall tier** - how much a unit is worth across the whole rotation. Its recent
lift is estimated per boss weakness - five internal slots, Fire, Water, Wind,
Iron and Electric - and the slots are averaged (``overall``), so a unit's
standing does not depend on which elements happened to come up lately. The
slots follow the *boss's* weakness, not the unit's own element, because supports
follow the element of the deck they support: a Water support fielded only in
Wind-weak seasons earns its overall there, while its element tier (Water) stays
low. The overall tier has cuts of its own (``overall_cuts``), the same labels
set lower: a unit carrying one element and sitting out the rest scores a fifth
of its element lift, so on the element tier's cuts an element-SS specialist
would stand at C. The cuts give each overall tier about as many units as the
element tiers hold; the order within stays the score's.

A slot with no season since the unit's release is filled from its own side
only. Its own elements and the other elements are two sides, and what a unit
does in its own element says little about the others: a specialist that
carries its element's decks sits out the rest. So an unobserved other-element
slot takes the mean of the other-element slots the unit was seen in, and 0
while it has been seen in no other element at all - a unit fielded only in
its own element's seasons so far is taken for a specialist until it shows
otherwise (tried on seasons 1-41: of the units once seen in their own element
only, the other elements they met later came to a median 2% of their own
level). An unobserved own-element slot is never guessed either: it counts 0
until the unit meets a season of that element, also when the unit has a
second own element it was seen in (Sugar's Iron is not guessed from the
Water it played with its treasure).

The two read together: high in its element and low overall is a specialist,
high in both a unit that goes anywhere, low in its element and high overall a
support that carries other elements' decks.

A unit seen in fewer than ``min_elements_observed`` elements, or not yet in
its own, is ``provisional``: its unobserved slots are stand-ins, so its overall
tier is shown but marked.

The season in progress counts too (``include_live``) once a snapshot of it was
taken by the moment of the view: its rankings so far stand in for the season,
and they change with every snapshot until it is over.

Beside the tiers, and not part of them, each unit's **lifespan**: since when
top rankers have used it, in how many seasons, and whether they still do. A
season *fields* a unit when its season tier there is ``min_tier`` (D) or better;
a unit fielded in no season for three months (``retire_after_days``) that also
sat out a season of its own element's weakness (``retire_after_own_seasons``)
is retired, and one fielded again after that came back (``lifespans``). The
own-element season is what keeps the window short without retiring a
specialist whose element has not come round: an element can take a year to.

And how **general** it is - from 0, fielded only in its own element's seasons,
through 1, fielded whatever the weakness, to 2, fielded only when the weakness
is another element's: ``2X / (O + X)`` from its element tier's slot O and the
mean X of its other-element slots (``generality``).

A treasure (애장품) changes a unit for good, so its element and overall tiers are
reckoned on one side of it only: a view of a moment when the unit had its
treasure stands on the seasons played with it (the season rows' ``treasure``
flag), a view of a moment before on the seasons before. Right after the
treasure, before a season has been played with it, the unit has no tier yet -
like a new release. Season tiers and the unit's history are not split: it is
the same unit, one line, with the treasure marked where it came. An element the
treasure's skill adds is the unit's from the treasure on: Sugar (Iron) counts
as Water too on the seasons with its treasure, and as Iron only before.
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
from .metrics import ELEMENTS, listed_elements, season_order

DEFAULT_TIER_CONFIG = REPO_ROOT / "config" / "tiers.yaml"

# Ordered best -> worst: (label, minimum lift).
DEFAULT_CUTS: list[tuple[str, float]] = [
    ("SS", 1.4),
    ("S", 1.1),
    ("A", 0.8),
    ("B", 0.5),
    ("C", 0.2),
    ("D", 0.03),
    ("F", 0.0),
]
# The overall tier's cuts: the same labels, lower. An overall is the mean of five slots, so a unit
# that carries one element and sits out the rest scores a fifth of its element lift there; these
# cuts put about as many units in each overall tier as the element tiers hold (seasons 16-41).
DEFAULT_OVERALL_CUTS: list[tuple[str, float]] = [
    ("SS", 0.9),
    ("S", 0.65),
    ("A", 0.3),
    ("B", 0.18),
    ("C", 0.07),
    ("D", 0.015),
    ("F", 0.0),
]
OVERALL_MODES = ("mean", "max", "frequency")
GENERALITY_MAX = 2.0  # generality of a unit fielded only when the weakness is another element's


@dataclass
class TierConfig:
    # population
    top_n: int = 50
    servers: tuple[str, ...] = ()  # () = every server
    exclude_servers: tuple[str, ...] = ()
    rank_weighting: str = "dcg"
    # season tier
    cuts: list[tuple[str, float]] = field(default_factory=lambda: list(DEFAULT_CUTS))
    # overall tier (element tiers take ``cuts``). None: the default overall cuts when ``cuts``
    # has the default labels, otherwise ``cuts`` itself.
    overall_cuts: list[tuple[str, float]] | None = None
    # element and overall tiers
    half_life_days: float = 180.0
    prior_strength: float = 0.0
    overall: str = "mean"
    min_elements_observed: int = 3
    include_live: bool = True
    # lifespan: a season fields a unit when its season tier there is ``min_tier`` or better.
    # None: D - or, with cuts of other labels, the lowest tier above the bottom one.
    min_tier: str | None = None
    retire_after_days: float = 90.0
    retire_after_own_seasons: int = 1
    # generality bands, low to high (0-2)
    generality_bands: tuple[float, float] = (0.3, 0.7)
    # career curves: a turn of the rotation is in use when its own-element or other-element
    # lift is at this season tier or better; a career that was this general at its peak or more
    # started out general
    curve_min_tier: str | None = None
    curve_wide: float = 0.5
    # the meta: how far back each season looks to band the units in use by their generality
    meta_window_days: int = 365
    # diagnostics
    deck_effect_ridge: float = 20.0
    synergy_min_decks: int = 20

    def __post_init__(self) -> None:
        self.cuts = sorted(((str(l), float(v)) for l, v in self.cuts), key=lambda c: c[1], reverse=True)
        labels = [l for l, _ in self.cuts]
        if self.overall_cuts is None:
            same = labels == [l for l, _ in DEFAULT_OVERALL_CUTS]
            self.overall_cuts = list(DEFAULT_OVERALL_CUTS) if same else list(self.cuts)
        self.overall_cuts = sorted(((str(l), float(v)) for l, v in self.overall_cuts), key=lambda c: c[1],
                                   reverse=True)
        if [l for l, _ in self.overall_cuts] != labels:
            raise ValueError("overall_cuts must have the same labels, in the same order, as cuts")
        if self.overall not in OVERALL_MODES:
            raise ValueError(f"element.overall must be one of {OVERALL_MODES}, not {self.overall!r}")
        if self.min_tier is None:
            self.min_tier = "D" if "D" in labels else labels[max(0, len(labels) - 2)]
        if self.min_tier not in labels:
            raise ValueError(f"lifespan.min_tier must be one of the cuts' labels {labels}, not {self.min_tier!r}")
        low, high = (float(v) for v in self.generality_bands)
        if not 0 <= low <= high <= GENERALITY_MAX:
            raise ValueError(f"career.generality_bands must be two values 0 <= low <= high <= {GENERALITY_MAX:g}, "
                             f"not {self.generality_bands}")
        self.generality_bands = (low, high)
        if self.curve_min_tier is None:
            self.curve_min_tier = "C" if "C" in labels else self.min_tier
        if self.curve_min_tier not in labels:
            raise ValueError(f"career.curve_min_tier must be one of the cuts' labels {labels}, not {self.curve_min_tier!r}")
        if not 0 <= float(self.curve_wide) <= GENERALITY_MAX:
            raise ValueError(f"career.curve_wide must be 0 - {GENERALITY_MAX:g}, not {self.curve_wide}")
        self.curve_wide = float(self.curve_wide)
        if int(self.meta_window_days) < 1:
            raise ValueError(f"meta.window_days must be at least 1, not {self.meta_window_days}")
        self.meta_window_days = int(self.meta_window_days)

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

    def overall_cut(self, label: str) -> float:
        return dict(self.overall_cuts)[label]


def load_tier_config(path: Path | None = None) -> TierConfig:
    target = path or DEFAULT_TIER_CONFIG
    if not target.is_file():
        return TierConfig()
    doc: dict[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    population = doc.get("population") or {}
    element = doc.get("element") or {}
    lifespan = doc.get("lifespan") or {}
    career = doc.get("career") or {}
    meta = doc.get("meta") or {}
    diagnostics = doc.get("diagnostics") or {}
    defaults = TierConfig()
    cuts = doc.get("cuts")
    overall_cuts = doc.get("overall_cuts")
    return TierConfig(
        top_n=int(population.get("top_n", defaults.top_n)),
        servers=split(population.get("servers") or ()),
        exclude_servers=split(population.get("exclude_servers") or ()),
        rank_weighting=str(population.get("rank_weighting", defaults.rank_weighting)),
        cuts=[(str(c["label"]), float(c["min_lift"])) for c in cuts] if cuts else list(DEFAULT_CUTS),
        overall_cuts=[(str(c["label"]), float(c["min_lift"])) for c in overall_cuts] if overall_cuts else None,
        half_life_days=float(element.get("half_life_days", defaults.half_life_days)),
        prior_strength=float(element.get("prior_strength", defaults.prior_strength)),
        overall=str(element.get("overall", defaults.overall)),
        min_elements_observed=int(element.get("min_elements_observed", defaults.min_elements_observed)),
        include_live=bool(element.get("include_live", defaults.include_live)),
        min_tier=str(lifespan["min_tier"]) if lifespan.get("min_tier") else None,
        retire_after_days=float(lifespan.get("retire_after_days", defaults.retire_after_days)),
        retire_after_own_seasons=int(lifespan.get("retire_after_own_seasons", defaults.retire_after_own_seasons)),
        generality_bands=tuple(float(v) for v in career.get("generality_bands", defaults.generality_bands)),
        curve_min_tier=str(career["curve_min_tier"]) if career.get("curve_min_tier") else None,
        curve_wide=float(career.get("curve_wide", defaults.curve_wide)),
        meta_window_days=int(meta.get("window_days", defaults.meta_window_days)),
        deck_effect_ridge=float(diagnostics.get("deck_effect_ridge", defaults.deck_effect_ridge)),
        synergy_min_decks=int(diagnostics.get("synergy_min_decks", defaults.synergy_min_decks)),
    )


def assign_tier(value: float, config: TierConfig | None = None, *, overall: bool = False) -> str:
    """The tier of a season or element lift - or, with ``overall``, of an overall score."""
    config = config or TierConfig()
    if value is None or pd.isna(value):
        return ""
    cuts = config.overall_cuts if overall else config.cuts
    for label, minimum in cuts:
        if value >= minimum:
            return label
    return cuts[-1][0]


def tier_rank(label: str, config: TierConfig | None = None) -> int:
    """0 for the best tier; unknown labels sort last."""
    order = (config or TierConfig()).tier_order
    return order.index(label) if label in order else len(order)


# --------------------------------------------------------------------------
# where every unit stands: its element tiers and its overall tier
# --------------------------------------------------------------------------

OVERALL_COLUMNS = ["unit_id", "overall", "overall_tier", "overall_rank", "provisional", "elements_observed",
                   "seasons_observed", "last_season", "treasure"]
ELEMENT_COLUMNS = ["unit_id", "element", "source", "element_lift", "element_tier", "element_seasons", "element_rank",
                   "treasure"]
SLOT_COLUMNS = ["unit_id", "element", "lift", "seasons"]
TURN_COLUMNS = ["season", "unit_id", "lift", "own"]


@dataclass
class Standings:
    """Where every unit stands at one moment.

    ``overall``: one row per unit, its overall tier, best first. ``elements``:
    one row per unit and element it counts as - its own (``source`` "own") and
    any its skill adds (``source`` "skill", ``extra_elements``) - with its
    tier in that element, element by element and best first; an element the
    unit has not met since its release has no tier yet (``element_seasons`` 0).
    ``overall_rank`` ranks a unit among all units, ``element_rank`` among the
    units of that element; 1 is the best. ``provisional`` marks an overall seen
    in fewer than ``min_elements_observed`` boss weaknesses or not yet in the
    unit's own element. ``slots``: the five values the overall is made of, one
    row per unit and boss weakness (``element``), with the seasons behind each
    (``seasons`` 0: not met yet, filled in). ``treasure`` says a unit's tiers
    stand on the seasons played with its treasure. ``rows``: the season rows
    the standing is made of, each with whether its boss was weak to an element
    the unit counts as (``own``) - what ``generality`` reads.
    """

    overall: pd.DataFrame
    elements: pd.DataFrame
    slots: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SLOT_COLUMNS))
    rows: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=TURN_COLUMNS))


def flags(rows: pd.DataFrame, column: str) -> pd.Series:
    """A flag column of season rows as booleans (False where there is none),
    whether it was computed or read back from a table as text."""
    if column not in rows.columns:
        return pd.Series(False, index=rows.index)
    return rows[column].astype(str).str.lower().isin(("true", "1"))


def played_with_treasure(rows: pd.DataFrame) -> pd.Series:
    """The ``treasure`` flag of season rows as booleans (False where there is none)."""
    return flags(rows, "treasure")


def _decay(ages_days: pd.Series, half_life_days: float) -> pd.Series:
    if half_life_days <= 0:
        return pd.Series(1.0, index=ages_days.index)
    return 0.5 ** (ages_days.clip(lower=0) / half_life_days)


def _instant(moment: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(moment)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def counted_seasons(seasons: pd.DataFrame, moment: Any, config: TierConfig | None = None) -> pd.DataFrame:
    """The seasons a view at ``moment`` stands on (``season``, ``end_at``,
    ``weak_element``, ``live``): every season over by then and, with
    ``include_live``, the season still in progress once a snapshot of it had
    been taken by then (``live``). ``seasons`` is the season summary."""
    config = config or TierConfig()
    moment = _instant(moment)
    final = seasons["final"].astype(bool)
    over = final & (seasons["end_at"] <= moment)
    live = pd.Series(False, index=seasons.index)
    if config.include_live and "collected_on" in seasons.columns:
        live = ~final & (seasons["collected_on"] <= moment)
    counted = seasons.loc[over | live, ["season", "end_at", "weak_element"]].assign(live=live[over | live])
    return counted.reset_index(drop=True)


def unit_elements(table: pd.DataFrame, treasured: Any = ()) -> pd.DataFrame:
    """Every element each unit counts as, one row per unit and element (``unit_id``,
    ``element``, ``source``), from the roster columns of the season table: its
    own ``element``, then the ``extra_elements`` its skill adds ("Iron;Water")
    and, for the ``treasured`` units, the ``treasure_elements`` its treasure's
    skill adds (both ``source`` "skill")."""
    columns = ["unit_id", "element", "source"]
    if table.empty or "element" not in table.columns:
        return pd.DataFrame(columns=columns)
    units = table.drop_duplicates("unit_id")
    own = units[["unit_id", "element"]].assign(source="own")
    frames = [own]
    adding = [("extra_elements", units)]
    if "treasure_elements" in units.columns:
        adding.append(("treasure_elements", units[units["unit_id"].isin(set(treasured))]))
    for column, which in adding:
        if column in which.columns:
            added = which[["unit_id"]].assign(element=which[column].map(listed_elements)).explode("element")
            frames.append(added[["unit_id", "element"]].assign(source="skill"))
    members = pd.concat(frames, ignore_index=True)
    members = members[members["element"].isin(ELEMENTS)]
    return members.drop_duplicates(["unit_id", "element"]).reset_index(drop=True)


def standings(
    table: pd.DataFrame,
    seasons: pd.DataFrame,
    moment: pd.Timestamp,
    config: TierConfig | None = None,
    *,
    treasured: Any = None,
) -> Standings:
    """Every unit's element tiers and overall tier, as known at ``moment``.

    Only what was known at ``moment`` counts: the seasons over by then and the
    one in progress as far as it had been collected (``counted_seasons``) - the
    view of the past never uses what happened after it. ``table`` is the season
    x unit table (with each unit's own ``element``) and ``seasons`` the season
    summary (it says which seasons are final and when each was collected).

    ``treasured`` - the units that had their treasure at ``moment`` - are
    tiered on the seasons they played with it, every other unit on the seasons
    without (the table's ``treasure`` flag). By default a unit counts as having
    it once a counted season was played with it.
    """
    config = config or TierConfig()
    moment = _instant(moment)
    counted = counted_seasons(seasons, moment, config)
    columns = ["season", "unit_id", "lift"] + (["treasure"] if "treasure" in table.columns else [])
    rows = table.loc[table["season"].isin(counted["season"]), columns].merge(counted, on="season")
    rows = rows[rows["weak_element"].isin(ELEMENTS)]
    has = played_with_treasure(rows)
    treasured = set(rows.loc[has, "unit_id"]) if treasured is None else set(treasured)
    rows = rows[has == rows["unit_id"].isin(treasured)]
    if rows.empty:
        return Standings(pd.DataFrame(columns=OVERALL_COLUMNS), pd.DataFrame(columns=ELEMENT_COLUMNS))

    # A season counts from its end; the one in progress as of now.
    counted["at"] = counted["end_at"].where(counted["end_at"] <= moment, moment)
    rows = rows.merge(counted[["season", "at"]], on="season")
    rows = rows.assign(w=_decay((moment - rows["at"]).dt.total_seconds() / 86400.0, config.half_life_days))
    rows["wl"] = rows["w"] * rows["lift"]
    unit = rows.groupby("unit_id").agg(W=("w", "sum"), WL=("wl", "sum"), seasons_observed=("season", "size"),
                                       last_season=("season", "max"))
    prior = unit["WL"] / unit["W"]
    slot = rows.groupby(["unit_id", "weak_element"]).agg(W=("w", "sum"), WL=("wl", "sum"), n=("w", "size"))
    mean = (slot["WL"] / slot["W"]).unstack().reindex(index=unit.index, columns=list(ELEMENTS))
    count = slot["n"].unstack().reindex(index=unit.index, columns=list(ELEMENTS)).fillna(0).astype(int)
    observed = count > 0

    # One slot per boss weakness, from the seasons of that weakness.
    k = config.prior_strength
    level = mean if k <= 0 else ((count * mean.fillna(0)).add(k * prior, axis=0)).div(count + k).where(observed)

    # The elements a unit counts as (its own, and any its skill adds) and the others are two
    # sides; a slot not observed since release is filled from the other-element side only. An
    # other-element slot takes the mean of the other-element slots seen - 0 while the unit has
    # met no other element yet. An own-element slot is never guessed: 0 until the unit meets a
    # season of it.
    members = unit_elements(table, treasured)
    members = members[members["unit_id"].isin(unit.index)].reset_index(drop=True)
    own = (pd.crosstab(members["unit_id"], members["element"]).reindex(index=unit.index, columns=list(ELEMENTS))
           .fillna(0).astype(bool))
    other_level = level.where(~own).mean(axis=1).fillna(0.0)
    fill = pd.DataFrame({e: other_level.where(~own[e], 0.0) for e in ELEMENTS})
    estimate = level.where(observed, fill)

    # Element tiers: the slots of the elements a unit counts as, once observed.
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
    elements["treasure"] = elements["unit_id"].isin(treasured)

    overall = pd.DataFrame(index=unit.index)
    if config.overall == "mean":
        overall["overall"] = estimate.mean(axis=1)
    elif config.overall == "max":
        overall["overall"] = estimate.where(observed).max(axis=1)
    else:  # frequency: weight each element by how often (recently) the boss was weak to it
        ages = (moment - counted["at"]).dt.total_seconds() / 86400.0
        freq = _decay(ages, config.half_life_days).groupby(counted["weak_element"].to_numpy()).sum()
        freq = freq.reindex(list(ELEMENTS)).fillna(0.0)
        freq = freq / freq.sum() if freq.sum() > 0 else pd.Series(1.0 / len(ELEMENTS), index=list(ELEMENTS))
        overall["overall"] = estimate.mul(freq, axis=1).sum(axis=1)
    overall["overall_tier"] = overall["overall"].map(lambda v: assign_tier(v, config, overall=True))
    overall["overall_rank"] = overall["overall"].rank(method="min", ascending=False).astype("Int64")
    n_obs = observed.sum(axis=1).astype(int)
    own_unseen = own.any(axis=1) & ~(observed & own).any(axis=1)
    overall["provisional"] = (n_obs < config.min_elements_observed) | own_unseen
    overall["elements_observed"] = n_obs
    overall["seasons_observed"] = unit["seasons_observed"].astype(int)
    overall["last_season"] = unit["last_season"].astype(int)
    overall["treasure"] = overall.index.isin(treasured)
    overall = overall.reset_index()[OVERALL_COLUMNS]
    overall = overall.sort_values(["overall", "unit_id"], ascending=[False, True]).reset_index(drop=True)
    slots = (estimate.rename_axis(index="unit_id", columns="element").stack().rename("lift").to_frame()
             .join(count.rename_axis(index="unit_id", columns="element").stack().rename("seasons")).reset_index())
    mine = set(zip(members["unit_id"], members["element"]))
    turns = rows.assign(own=[(u, e) in mine for u, e in zip(rows["unit_id"], rows["weak_element"])])
    return Standings(overall, elements[ELEMENT_COLUMNS].reset_index(drop=True), slots[SLOT_COLUMNS],
                     turns[TURN_COLUMNS].sort_values(["unit_id", "season"]).reset_index(drop=True))


# --------------------------------------------------------------------------
# lifespans: when each unit was in use
# --------------------------------------------------------------------------

LIFESPAN_COLUMNS = ["unit_id", "first_used", "run_from", "last_used", "seasons_used", "seasons_out", "returns",
                    "idle_days", "missed_own", "retired"]


def fielded(rows: pd.DataFrame, config: TierConfig | None = None) -> pd.Series:
    """Whether each season row fielded its unit: a season tier of ``min_tier`` or better
    there (and some use at all - a unit nobody fielded is not, whatever the cuts)."""
    config = config or TierConfig()
    lift = rows["lift"]
    return (lift > 0) & (lift >= config.cut(config.min_tier))


def lifespans(table: pd.DataFrame, seasons: pd.DataFrame, moment: Any, config: TierConfig | None = None) -> pd.DataFrame:
    """When each unit was in use, as known at ``moment``, one row per unit out by then.

    A season *used* a unit when the unit's season tier there was ``min_tier``
    or better (``fielded``: D, a lift of 0.03 - about one ranker in ten fielding
    it). Nothing else goes in - not the element, not the element or overall
    tiers, whose memory of past seasons would keep a unit long out of use
    looking current - so a specialist is used in its element's seasons and idle
    in between.

    A unit is ``retired`` once both hold since the end of the last season that
    used it: ``retire_after_days`` have gone by (``idle_days``), and at least
    ``retire_after_own_seasons`` of the seasons it sat out were weak to an
    element it counts as (``missed_own``; the table's ``element_match``). Days
    alone cannot tell a unit out of use from a specialist waiting for its
    element, which comes round every few months and sometimes only after a year;
    a season of its element passing it by can. So a unit used everywhere retires
    once it misses its own element as well, and a specialist whose element has
    not come round since stays in use however long that takes. With
    ``retire_after_own_seasons`` 0 the days alone decide.

    A unit used again after such a gap came back (``returns`` counts the gaps,
    measured from the end of one season that used it to the start of the next,
    with the own-element seasons in between), and its run in use since then
    starts at ``run_from``. ``first_used`` is its first season in use ever,
    ``last_used`` the latest, ``seasons_used`` how many used it of the
    ``seasons_out`` it was out for. A unit no season used has no seasons and is
    not retired.

    Same seasons as ``standings``: those over by ``moment`` and, with
    ``include_live``, the one in progress as far as collected - it counts as
    ending at ``moment``. A treasure does not split a lifespan: same unit.
    """
    config = config or TierConfig()
    moment = _instant(moment)
    counted = counted_seasons(seasons, moment, config)
    if counted.empty or table.empty:
        return pd.DataFrame(columns=LIFESPAN_COLUMNS)
    counted["start_at"] = counted["season"].map(seasons.set_index("season")["start_at"])
    counted["at"] = counted["end_at"].where(counted["end_at"] <= moment, moment)
    rows = (table.loc[table["season"].isin(counted["season"])]
            .assign(own=lambda frame: flags(frame, "element_match"), used=lambda frame: fielded(frame, config))
            [["season", "unit_id", "used", "own"]]
            .merge(counted[["season", "start_at", "at"]], on="season").sort_values(["unit_id", "season"]))
    window = pd.Timedelta(days=config.retire_after_days)
    need = config.retire_after_own_seasons
    out = []
    for unit_id, group in rows.groupby("unit_id", sort=True):
        in_use = group["used"].to_numpy(dtype=bool)
        used = group[in_use]
        record: dict[str, Any] = {"unit_id": unit_id, "first_used": pd.NA, "run_from": pd.NA, "last_used": pd.NA,
                                  "seasons_used": len(used), "seasons_out": len(group), "returns": 0,
                                  "idle_days": np.nan, "missed_own": 0, "retired": False}
        if not used.empty:
            own = np.cumsum(group["own"].to_numpy(dtype=bool))  # own-element seasons so far
            at = np.flatnonzero(in_use)
            missed = own[at[1:] - 1] - own[at[:-1]]  # own-element seasons between two that used it
            gaps = used["start_at"].iloc[1:].reset_index(drop=True) - used["at"].iloc[:-1].reset_index(drop=True)
            breaks = (gaps >= window).to_numpy(dtype=bool) & (missed >= need)
            since = int(np.flatnonzero(breaks)[-1]) + 1 if breaks.any() else 0
            idle = (moment - used["at"].iloc[-1]).total_seconds() / 86400.0
            missed_own = int(own[-1] - own[at[-1]])
            record.update(first_used=int(used["season"].iloc[0]), run_from=int(used["season"].iloc[since]),
                          last_used=int(used["season"].iloc[-1]), returns=int(breaks.sum()), idle_days=idle,
                          missed_own=missed_own, retired=idle >= config.retire_after_days and missed_own >= need)
        out.append(record)
    life = pd.DataFrame(out, columns=LIFESPAN_COLUMNS)
    for column in ("first_used", "run_from", "last_used"):
        life[column] = life[column].astype("Int64")
    life["retired"] = life["retired"].astype(bool)
    return life


# --------------------------------------------------------------------------
# generality: how general a unit is
# --------------------------------------------------------------------------

GENERALITY_COLUMNS = ["unit_id", "own_level", "other_level", "generality", "generality_band"]
GENERALITY_MIN_LEVEL = 0.05  # own + other level below this: too little use to say how general
GENERALITY_BANDS = ("specialist", "element_first", "generalist")  # low to high


def generality_band(value: float, config: TierConfig | None = None) -> str:
    """``specialist`` under the lower of ``generality_bands``, ``generalist`` from the upper,
    ``element_first`` between; empty for no value."""
    if value is None or pd.isna(value):
        return ""
    low, high = (config or TierConfig()).generality_bands
    return GENERALITY_BANDS[2] if value >= high else GENERALITY_BANDS[1] if value >= low else GENERALITY_BANDS[0]


def latest_turn(rows: pd.DataFrame) -> pd.DataFrame:
    """Each unit's latest turn of the element rotation, from its season rows (``season``,
    ``unit_id``, ``lift``, ``own``): ``own_level``, its lift in its latest own-element season
    (the mean with the own-element seasons right before it, back to back), and ``other_level``,
    the mean of its other-element seasons since the own-element season before that - the
    seasons on either side of the latest own one, about one turn of the rotation. A unit with no
    own-element season, or no other-element season in that span, has none."""
    out = []
    for unit_id, group in rows.sort_values(["unit_id", "season"]).groupby("unit_id", sort=False):
        own = group["own"].to_numpy(dtype=bool)
        lift = group["lift"].to_numpy(dtype=float)
        at = np.flatnonzero(own)
        if not len(at):
            continue
        end = start = int(at[-1])
        while start > 0 and own[start - 1]:
            start -= 1
        before = at[at < start]
        first = int(before[-1]) + 1 if len(before) else 0
        others = lift[first:][~own[first:]]
        if len(others):
            out.append((unit_id, float(lift[start:end + 1].mean()), float(others.mean())))
    return pd.DataFrame(out, columns=["unit_id", "own_level", "other_level"])


def generality(standing: Standings, config: TierConfig | None = None) -> pd.DataFrame:
    """How general each unit is at the moment of ``standing``: over its latest turn of the
    element rotation (``latest_turn``), with no memory beyond it.

    ``own_level``: its lift in its latest own-element season; ``other_level``: the
    mean of its other-element seasons around it. ``generality = 2 x other / (own +
    other)``: 0 for a unit fielded only when the boss is weak to its element, 1 for
    one the weakness makes no difference to (other = own), 2 for one fielded only
    when the boss is weak to another element (own = 0, as Delta: Ninja Thief).
    Empty until the unit has met both sides, and when it is barely used at all
    (own + other under ``GENERALITY_MIN_LEVEL``). A turn, not the tiers' memory:
    one own-element season comes round every few months, so a turn is the least
    that holds both sides, and the tiers' half-life would keep a unit that left
    the other elements' decks general for a year after (docs/lifecycle.md 2절).
    The seasons are the standing's - on the side of its treasure the unit was on.
    """
    config = config or TierConfig()
    if standing.overall.empty:
        return pd.DataFrame(columns=GENERALITY_COLUMNS)
    frame = latest_turn(standing.rows).set_index("unit_id").reindex(standing.overall["unit_id"])
    level = frame["own_level"] + frame["other_level"]
    frame["generality"] = (2 * frame["other_level"] / level).where(level >= GENERALITY_MIN_LEVEL)
    frame["generality_band"] = frame["generality"].map(lambda g: generality_band(g, config))
    return frame.rename_axis("unit_id").reset_index()[GENERALITY_COLUMNS]


# --------------------------------------------------------------------------
# career curves: the shape of a whole career
# --------------------------------------------------------------------------

ROTATION_COLUMNS = ["unit_id", "rotation", "own_season", "own", "other", "others", "level", "generality"]
CURVE_COLUMNS = ["unit_id", "turns", "peak", "g_peak", "g_low", "narrow_turns", "declined", "curve"]
CURVES = ("unused", "specialist", "narrowed", "faded", "general", "unknown")


def rotations(rows: pd.DataFrame) -> pd.DataFrame:
    """Each unit's career one turn of the element rotation at a time, from its season rows
    (``season``, ``unit_id``, ``lift``, ``own``).

    A turn is a season of the unit's own element (``own_season``) and the
    other-element seasons after it, up to the next own-element season; the first
    also takes the other-element seasons before it, and own-element seasons back
    to back share a turn. Per turn: its lift in the own-element season(s)
    (``own``, their mean), the mean of the others (``other``, over ``others``
    seasons; none after the latest own season yet, NaN), ``level = (own + other)
    / 2`` and ``generality = 2 x other / (own + other)``."""
    out = []
    for unit_id, group in rows.sort_values(["unit_id", "season"]).groupby("unit_id", sort=False):
        own = group["own"].to_numpy(dtype=bool)
        if not own.any():
            continue
        lift, season = group["lift"].to_numpy(dtype=float), group["season"].to_numpy()
        turn, k = np.zeros(len(own), dtype=int), -1
        for i in range(len(own)):  # a new turn at an own-element season not right after another
            if own[i] and (i == 0 or not own[i - 1]):
                k += 1
            turn[i] = max(k, 0)
        for t in range(k + 1):
            here = turn == t
            mine, rest = lift[here & own], lift[here & ~own]
            out.append({"unit_id": unit_id, "rotation": t, "own_season": int(season[here & own][0]),
                        "own": float(mine.mean()), "other": float(rest.mean()) if len(rest) else np.nan,
                        "others": int(len(rest))})
    frame = pd.DataFrame(out, columns=ROTATION_COLUMNS[:-2])
    total = frame["own"] + frame["other"]
    frame["level"] = total / 2
    frame["generality"] = (2 * frame["other"] / total).where(total > 0)
    return frame[ROTATION_COLUMNS]


def curve_of(turns: pd.DataFrame, config: TierConfig | None = None) -> dict[str, Any]:
    """The shape of one unit's career from its turns (``rotations``), in order.

    ``peak``: its best turn's level (a turn with no other-element season yet at
    half its own lift). ``g_peak``: its generality at the top - over the turns up
    to the best one at half its level or more, weighted by level. ``g_low``: the
    lowest generality from the best turn on while still in use (``own`` or
    ``other`` at ``curve_min_tier`` or better); ``narrow_turns``, those in-use
    turns with ``other`` under a quarter of ``own``; ``declined``: its latest turn
    under half the peak. Its ``curve``:

    * ``unused`` - no turn reached ``curve_min_tier``;
    * ``specialist`` - narrow from the start (``g_peak`` under ``curve_wide``);
    * ``narrowed`` - general at the top, then used in its own element's seasons
      only (``g_low`` under the lower generality band);
    * ``faded`` - general at the top and came down still general;
    * ``general`` - general and not come down yet: which of the two it ends as
      is not known yet;
    * ``unknown`` - fewer than two turns, or no other-element season yet.
    """
    config = config or TierConfig()
    use, narrow = config.cut(config.curve_min_tier), config.generality_bands[0]
    own, other = turns["own"].to_numpy(dtype=float), turns["other"].to_numpy(dtype=float)
    g = turns["generality"].to_numpy(dtype=float)
    level = np.where(np.isnan(other), own / 2, (own + np.nan_to_num(other)) / 2)
    other0 = np.nan_to_num(other)
    n = len(level)
    top = int(np.argmax(level))
    peak = float(level[top])
    rise = [i for i in range(top + 1) if level[i] >= peak / 2 and level[i] > 0 and not np.isnan(g[i])]
    weight = sum(level[i] for i in rise)
    g_peak = float(sum(g[i] * level[i] for i in rise) / weight) if rise and weight > 0 else np.nan
    after = [i for i in range(top, n) if (own[i] >= use or other0[i] >= use) and not np.isnan(g[i])]
    g_low = float(min(g[i] for i in after)) if after else np.nan
    declined = n > 1 and bool(level[-1] < peak / 2)
    if n < 2 or np.isnan(g_peak):
        curve = "unused" if n >= 2 and peak < use else "unknown"
    elif peak < use:
        curve = "unused"
    elif g_peak < config.curve_wide:
        curve = "specialist"
    elif g_low < narrow:
        curve = "narrowed"
    else:
        curve = "faded" if declined else "general"
    return {"turns": n, "peak": peak, "g_peak": g_peak, "g_low": g_low,
            "narrow_turns": sum(1 for i in after if other0[i] < own[i] / 4), "declined": declined, "curve": curve}


def curves(table: pd.DataFrame, seasons: pd.DataFrame, moment: Any, config: TierConfig | None = None) -> pd.DataFrame:
    """The shape of each unit's career as known at ``moment`` (``curve_of`` on its
    ``rotations``), one row per unit out by then with an own-element season.

    Same seasons as ``lifespans`` - those over by then and the one in progress as
    far as collected - and, like the lifespan, not split at the treasure: the
    same unit. A season is the unit's own when the table says so
    (``element_match``: its element, one its skill adds, or its treasure's once
    it had it). The curve is how a career has run, not a role: a unit fielded in
    its own element's seasons only may be dealing the damage there or giving that
    element's decks what they need."""
    config = config or TierConfig()
    counted = counted_seasons(seasons, moment, config)
    rows = table.loc[table["season"].isin(counted["season"]), ["season", "unit_id", "lift"]]
    if rows.empty:
        return pd.DataFrame(columns=CURVE_COLUMNS)
    rows = rows.assign(own=flags(table.loc[rows.index], "element_match"))
    out = [{"unit_id": unit_id, **curve_of(turns, config)}
           for unit_id, turns in rotations(rows).groupby("unit_id", sort=True)]
    return pd.DataFrame(out, columns=CURVE_COLUMNS)


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
    those are empty. ``generality`` is u's generality once s was over. For the season still in progress it is where u stands with
    that season so far (``include_live``; without it, where u stood after the
    last finished season): provisional, like the live season's own numbers.
    A unit that played s with its treasure is tiered there on its seasons with
    it, one that played without on its seasons without.
    """
    config = config or TierConfig()
    parts = []
    by_season = seasons.set_index("season")
    for season in season_order(table["season"]):
        info = by_season.loc[season]
        moment = info["end_at"] if bool(info["final"]) else info["collected_until"]
        if pd.isna(moment):
            continue
        here = table[table["season"] == season]
        treasured = here.loc[played_with_treasure(here), "unit_id"]
        standing = standings(table, seasons, moment, config, treasured=treasured)
        overall = standing.overall.drop(columns=["overall_rank", "seasons_observed", "last_season", "treasure"])
        element = (standing.elements.drop(columns=["source", "element_rank", "treasure"])
                   .rename(columns={"element": "weak_element"}))
        general = generality(standing, config)[["unit_id", "generality"]]
        rows = here.merge(overall, on="unit_id", how="left").merge(general, on="unit_id", how="left")
        parts.append(rows.merge(element, on=["unit_id", "weak_element"], how="left"))
    history = pd.concat(parts, ignore_index=True) if parts else table.copy()
    history["final"] = history["season"].map(by_season["final"]).astype(bool)
    return history


def _flag(value: Any) -> bool:
    return str(value).lower() in ("true", "1")


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
    ``treasure`` marks the step into the first season a unit played with its
    treasure - always listed: its element and overall tiers from there stand on
    those seasons.
    """
    config = config or TierConfig()
    columns = ["unit_id", "name_ko", "name_en", "weak_element", "lift", "tier", "element_lift", "element_tier",
               "overall", "overall_tier"]
    if "treasure" in history.columns:
        columns.append("treasure")
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
                treasure = _flag(row.get("treasure_to")) and not _flag(row.get("treasure_from"))
                if steps == 0 and element_steps == 0 and overall_steps == 0 and not treasure:
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
                        "treasure": treasure,
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
