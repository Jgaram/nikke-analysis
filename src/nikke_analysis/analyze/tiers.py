"""Turning measurements into tiers, per season, per element, and over time.

A tier list is an opinion. Deriving one from data does not make it more correct
than a good player's; it makes it *reproducible* - same input, same tiers, with
the reasoning visible as numbers instead of hidden in a judgement call. Every
judgement that remains is a parameter in ``config/tiers.yaml``.

Three tiers answer three different questions:

**Season tier** - how much a unit carried in one season: fixed cuts on its lift.
Fixed cuts, not percentiles, so the number of SS units is itself information: a
season one deck dominates has five, a season with no dominant deck may have none.

**Element tier** - how much a unit is worth when the boss is weak to a given
element. Solo Raid's meta turns on the boss's weakness, and more so every year,
so each unit gets five slots: its recent lift in seasons whose boss was weak to
Fire, Water, Wind, Iron and Electric. The condition is the *boss's* weakness,
not the unit's own element, because supports follow the element of the deck they
support: a Water support fielded only in Wind-weak seasons is a Wind unit here.
Recent seasons count more (``half_life_days``). A slot with no season since the
unit's release is *unobserved*: it borrows the unit's overall level and is
flagged, rather than reading as zero.

**Overall tier** - one number from the five slots (``overall``): their mean by
default, so a unit's standing does not depend on which elements happened to come
up lately. A specialist's overall is low by construction; its best element and
coverage (slots at A or better) say the rest.

**Role** - in how many elements a unit is viable, meaning its slot is at least
``viable_fraction`` of its best one. Viable in (nearly) every observed element:
``universal``. In one: ``specialist``. In between: ``hybrid`` - where damage-
dealing supports and partner units land without needing a label. The
``specialization`` column is the continuous version: 1 - (average of the other
observed slots / the best slot), 0 when every element is worth the same.

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
ROLES = ("universal", "hybrid", "specialist", "outside", "undetermined")
SLOT = {e: e.lower() for e in ELEMENTS}


@dataclass
class TierConfig:
    # population
    top_n: int = 50
    servers: tuple[str, ...] = ()  # () = every server
    exclude_servers: tuple[str, ...] = ()
    rank_weighting: str = "dcg"
    # season tier
    cuts: list[tuple[str, float]] = field(default_factory=lambda: list(DEFAULT_CUTS))
    # element profile
    half_life_days: float = 180.0
    prior_strength: float = 0.0
    overall: str = "mean"
    coverage_min_tier: str = "A"
    # roles
    min_elements_observed: int = 3
    min_best_lift: float = 0.5
    viable_fraction: float = 0.5
    universal_min_share: float = 0.8
    specialist_max_viable: int = 1
    # diagnostics
    deck_effect_ridge: float = 20.0
    synergy_min_decks: int = 20

    def __post_init__(self) -> None:
        self.cuts = sorted(((str(l), float(v)) for l, v in self.cuts), key=lambda c: c[1], reverse=True)
        if self.overall not in OVERALL_MODES:
            raise ValueError(f"element.overall must be one of {OVERALL_MODES}, not {self.overall!r}")
        if self.coverage_min_tier not in self.tier_order:
            raise ValueError(f"element.coverage_min_tier {self.coverage_min_tier!r} is not a tier label")
        if not 0 < self.viable_fraction <= 1 or not 0 < self.universal_min_share <= 1:
            raise ValueError("roles.viable_fraction and roles.universal_min_share must be in (0, 1]")

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
    roles = doc.get("roles") or {}
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
        coverage_min_tier=str(element.get("coverage_min_tier", defaults.coverage_min_tier)),
        min_elements_observed=int(roles.get("min_elements_observed", defaults.min_elements_observed)),
        min_best_lift=float(roles.get("min_best_lift", defaults.min_best_lift)),
        viable_fraction=float(roles.get("viable_fraction", defaults.viable_fraction)),
        universal_min_share=float(roles.get("universal_min_share", defaults.universal_min_share)),
        specialist_max_viable=int(roles.get("specialist_max_viable", defaults.specialist_max_viable)),
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


def assign_role(viable: int, best: float, observed: int, config: TierConfig) -> str:
    """``viable``: observed elements whose slot is at least ``viable_fraction`` of the best."""
    if observed < config.min_elements_observed:
        return "undetermined"
    if pd.isna(best) or best < config.min_best_lift:
        return "outside"
    if viable <= config.specialist_max_viable:
        return "specialist"
    if viable >= config.universal_min_share * observed:
        return "universal"
    return "hybrid"


# --------------------------------------------------------------------------
# element profiles
# --------------------------------------------------------------------------

PROFILE_COLUMNS = (
    ["unit_id", "overall", "overall_tier", "provisional", "best_element", "best_lift", "best_tier", "coverage",
     "viable_elements", "specialization", "role", "elements_observed", "seasons_observed", "last_season"]
    + [f"lift_{SLOT[e]}" for e in ELEMENTS]
    + [f"tier_{SLOT[e]}" for e in ELEMENTS]
    + [f"n_{SLOT[e]}" for e in ELEMENTS]
)


def _decay(ages_days: pd.Series, half_life_days: float) -> pd.Series:
    if half_life_days <= 0:
        return pd.Series(1.0, index=ages_days.index)
    return 0.5 ** (ages_days.clip(lower=0) / half_life_days)


def element_profiles(
    table: pd.DataFrame,
    seasons: pd.DataFrame,
    moment: pd.Timestamp,
    config: TierConfig | None = None,
) -> pd.DataFrame:
    """Every unit's five element slots, overall tier and role, as known at ``moment``.

    Only seasons that were over by ``moment`` count: the view of the past never
    uses what happened after it. ``table`` is the season x unit table and
    ``seasons`` the season summary (it says which seasons are final).
    """
    config = config or TierConfig()
    moment = pd.Timestamp(moment)
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    final = seasons.loc[seasons["final"].astype(bool) & (seasons["end_at"] <= moment), ["season", "end_at", "weak_element"]]
    rows = table.loc[table["season"].isin(final["season"]), ["season", "unit_id", "lift"]].merge(final, on="season")
    rows = rows[rows["weak_element"].isin(ELEMENTS)]
    if rows.empty:
        return pd.DataFrame(columns=PROFILE_COLUMNS)

    rows = rows.assign(w=_decay((moment - rows["end_at"]).dt.total_seconds() / 86400.0, config.half_life_days))
    rows["wl"] = rows["w"] * rows["lift"]
    unit = rows.groupby("unit_id").agg(W=("w", "sum"), WL=("wl", "sum"), seasons_observed=("season", "size"),
                                       last_season=("season", "max"))
    prior = unit["WL"] / unit["W"]
    slot = rows.groupby(["unit_id", "weak_element"]).agg(W=("w", "sum"), WL=("wl", "sum"), n=("w", "size"))
    mean = (slot["WL"] / slot["W"]).unstack().reindex(columns=list(ELEMENTS))
    count = slot["n"].unstack().reindex(columns=list(ELEMENTS)).fillna(0).astype(int)

    k = config.prior_strength
    estimate = pd.DataFrame(index=unit.index)
    for element in ELEMENTS:
        n = count[element].reindex(unit.index).fillna(0)
        m = mean[element].reindex(unit.index)
        shrunk = (n * m.fillna(0) + k * prior) / (n + k) if k > 0 else m
        estimate[element] = np.where(n > 0, shrunk, prior)

    out = pd.DataFrame(index=unit.index)
    observed = count.reindex(unit.index).fillna(0) > 0
    if config.overall == "mean":
        out["overall"] = estimate.mean(axis=1)
    elif config.overall == "max":
        out["overall"] = estimate.where(observed).max(axis=1)
    else:  # frequency: weight each element by how often (recently) the boss was weak to it
        ages = (moment - final["end_at"]).dt.total_seconds() / 86400.0
        freq = _decay(ages, config.half_life_days).groupby(final["weak_element"].to_numpy()).sum()
        freq = freq.reindex(list(ELEMENTS)).fillna(0.0)
        freq = freq / freq.sum() if freq.sum() > 0 else pd.Series(1.0 / len(ELEMENTS), index=list(ELEMENTS))
        out["overall"] = estimate.mul(freq, axis=1).sum(axis=1)
    out["overall_tier"] = out["overall"].map(lambda v: assign_tier(v, config))

    best_values = estimate.where(observed)
    out["best_element"] = best_values.idxmax(axis=1)
    out["best_lift"] = best_values.max(axis=1)
    out["best_tier"] = out["best_lift"].map(lambda v: assign_tier(v, config))
    out["coverage"] = (best_values >= config.cut(config.coverage_min_tier)).sum(axis=1).astype(int)

    # Shape of the value over the elements, from the observed slots, unshrunk.
    raw = mean.reindex(unit.index).where(observed)
    n_obs = observed.sum(axis=1).astype(int)
    top = raw.max(axis=1)
    others = (raw.sum(axis=1) - top) / (n_obs - 1).where(n_obs > 1)
    out["specialization"] = (1.0 - others / top.where(top > 0)).clip(lower=0.0)
    out["viable_elements"] = raw.ge(config.viable_fraction * top, axis=0).sum(axis=1).astype(int)
    out["elements_observed"] = n_obs
    out["provisional"] = n_obs < config.min_elements_observed
    out["role"] = [
        assign_role(int(v), b, int(o), config)
        for v, b, o in zip(out["viable_elements"], top, out["elements_observed"])
    ]
    out["seasons_observed"] = unit["seasons_observed"].astype(int)
    out["last_season"] = unit["last_season"].astype(int)
    for element in ELEMENTS:
        out[f"lift_{SLOT[element]}"] = estimate[element]
        out[f"tier_{SLOT[element]}"] = estimate[element].map(lambda v: assign_tier(v, config))
        out[f"n_{SLOT[element]}"] = count[element].reindex(unit.index).fillna(0).astype(int)
    out = out.reset_index()
    return out[PROFILE_COLUMNS].sort_values(["overall", "unit_id"], ascending=[False, True]).reset_index(drop=True)


# --------------------------------------------------------------------------
# season tiers and their history
# --------------------------------------------------------------------------

def season_tiers(table: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    config = config or TierConfig()
    out = table.copy()
    out["tier"] = out["lift"].map(lambda v: assign_tier(v, config))
    return out


def tier_history(table: pd.DataFrame, seasons: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """The season table with each unit's element profile as known at that season's end.

    Row (season s, unit u) carries both what u did in s (``lift``, ``tier``) and
    where u stood overall once s was over (``overall``, ``overall_tier``, role,
    the five slots). For the season still in progress the profile is the one of
    the last finished season: its own numbers are provisional.
    """
    config = config or TierConfig()
    parts = []
    by_season = seasons.set_index("season")
    for season in season_order(table["season"]):
        info = by_season.loc[season]
        moment = info["end_at"] if bool(info["final"]) else info["collected_until"]
        if pd.isna(moment):
            continue
        profile = element_profiles(table, seasons, moment, config)
        profile = profile.drop(columns=["last_season", "seasons_observed"])
        rows = table[table["season"] == season].merge(profile, on="unit_id", how="left")
        parts.append(rows)
    history = pd.concat(parts, ignore_index=True) if parts else table.copy()
    history["final"] = history["season"].map(by_season["final"]).astype(bool)
    return history


def tier_changes(history: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Units whose season tier or overall tier moved between consecutive seasons.

    ``steps`` and ``overall_steps`` are positive for a promotion. This is the
    table that answers "what did this season change".
    """
    config = config or TierConfig()
    seasons = season_order(history["season"])
    rows = []
    columns = ["unit_id", "name_ko", "name_en", "lift", "tier", "overall", "overall_tier"]
    for previous, current in zip(seasons, seasons[1:]):
        before = history.loc[history["season"] == previous, columns].set_index("unit_id")
        after = history.loc[history["season"] == current, columns].set_index("unit_id")
        both = before.join(after, lsuffix="_from", rsuffix="_to", how="inner")
        for unit_id, row in both.iterrows():
            steps = tier_rank(row["tier_from"], config) - tier_rank(row["tier_to"], config)
            overall_steps = tier_rank(row["overall_tier_from"], config) - tier_rank(row["overall_tier_to"], config)
            if steps == 0 and overall_steps == 0:
                continue
            rows.append(
                {
                    "season_from": previous,
                    "season_to": current,
                    "unit_id": unit_id,
                    "name_ko": row["name_ko_to"],
                    "name_en": row["name_en_to"],
                    "tier_from": row["tier_from"],
                    "tier_to": row["tier_to"],
                    "steps": steps,
                    "lift_from": row["lift_from"],
                    "lift_to": row["lift_to"],
                    "overall_tier_from": row["overall_tier_from"],
                    "overall_tier_to": row["overall_tier_to"],
                    "overall_steps": overall_steps,
                    "overall_from": row["overall_from"],
                    "overall_to": row["overall_to"],
                }
            )
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
