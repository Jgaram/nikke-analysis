"""Turning measurements into a tier list, and tracking how it moves.

A tier list is an opinion. The point of deriving one from data is not that it is
more correct than a good player's, but that it is *reproducible*: same input,
same tiers, every time, with the reasoning visible as three numbers rather than
hidden in a judgement call.

Each unit is scored on three axes, each expressed as a percentile among the units
that were actually available that season:

``usage``        rank-weighted pick rate - how much of the top-50's evidence it carries.
``performance``  score delta - whether teams using it out-score teams that don't.
``breadth``      how many of the season's bosses it shows up against.

Breadth is what stops a hard-countered specialist outranking a generalist on pick
rate alone: a unit that dominates one elemental matchup and is unplayable in the
other four is a real thing in Solo Raid, and it should not read as S tier.

Units that were available but never picked score zero on every axis rather than
being dropped, so the percentiles describe the whole roster instead of only the
units that already made it.

Weights and cut points live in ``config/tiers.yaml``. Nothing here is magic - if
a cut looks wrong, move it in the config and re-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ..paths import REPO_ROOT
from .metrics import Availability, season_order

DEFAULT_TIER_CONFIG = REPO_ROOT / "config" / "tiers.yaml"

# Ordered best -> worst. The label is what appears in reports; the cut is the
# minimum composite score (0-100) required to reach it.
DEFAULT_CUTS: list[tuple[str, float]] = [
    ("SS", 92.0),
    ("S", 80.0),
    ("A", 62.0),
    ("B", 42.0),
    ("C", 20.0),
    ("D", 0.0),
]


@dataclass
class TierConfig:
    weight_usage: float = 0.55
    weight_performance: float = 0.30
    weight_breadth: float = 0.15
    cuts: list[tuple[str, float]] = field(default_factory=lambda: list(DEFAULT_CUTS))
    min_teams: int = 10

    @property
    def weights(self) -> tuple[float, float, float]:
        total = self.weight_usage + self.weight_performance + self.weight_breadth
        if total <= 0:
            raise ValueError("tier weights must sum to a positive number")
        return (
            self.weight_usage / total,
            self.weight_performance / total,
            self.weight_breadth / total,
        )

    @property
    def tier_order(self) -> list[str]:
        return [label for label, _ in self.cuts]


def load_tier_config(path: Path | None = None) -> TierConfig:
    target = path or DEFAULT_TIER_CONFIG
    if not target.is_file():
        return TierConfig()
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    cuts = document.get("cuts")
    parsed_cuts = (
        [(str(entry["label"]), float(entry["min_score"])) for entry in cuts]
        if cuts
        else list(DEFAULT_CUTS)
    )
    parsed_cuts.sort(key=lambda item: item[1], reverse=True)
    weights = document.get("weights") or {}
    return TierConfig(
        weight_usage=float(weights.get("usage", 0.55)),
        weight_performance=float(weights.get("performance", 0.30)),
        weight_breadth=float(weights.get("breadth", 0.15)),
        cuts=parsed_cuts,
        min_teams=int(document.get("min_teams", 10)),
    )


def _percentile(values: pd.Series) -> pd.Series:
    """Rank to 0-100. Ties share a rank, and an all-equal column maps to 50."""
    if values.empty:
        return values
    if values.nunique(dropna=True) <= 1:
        return pd.Series(50.0, index=values.index)
    return values.rank(pct=True, na_option="bottom") * 100.0


def season_unit_scores(
    usage: pd.DataFrame,
    roster: pd.DataFrame,
    availability: Availability,
    config: TierConfig | None = None,
) -> pd.DataFrame:
    """Collapse per-boss usage into one scored row per (season, unit)."""
    config = config or TierConfig()
    if usage.empty:
        return pd.DataFrame()

    work = usage.copy()
    work["season"] = work["season"].astype(str)

    bosses_per_season = work.groupby("season")["boss"].nunique().rename("bosses")
    per_unit = (
        work.groupby(["season", "unit_id"])
        .agg(
            weighted_pick_rate=("weighted_pick_rate", "mean"),
            pick_rate=("pick_rate", "mean"),
            lift=("lift", "mean"),
            score_delta=("score_delta", "mean"),
            bosses_used=("boss", "nunique"),
            best_rank=("best_rank", "min"),
            teams=("teams", "sum"),
        )
        .reset_index()
        .join(bosses_per_season, on="season")
    )
    per_unit["breadth"] = np.where(
        per_unit["bosses"] > 0, per_unit["bosses_used"] / per_unit["bosses"], np.nan
    )

    # Re-introduce available-but-unpicked units so percentiles cover the roster.
    filled: list[pd.DataFrame] = []
    for season in season_order(per_unit["season"]):
        present = per_unit[per_unit["season"] == season]
        available = availability.by_season.get(season, set())
        missing = sorted(available - set(present["unit_id"]))
        if missing:
            blanks = pd.DataFrame(
                {
                    "season": season,
                    "unit_id": missing,
                    "weighted_pick_rate": 0.0,
                    "pick_rate": 0.0,
                    "lift": 0.0,
                    "score_delta": 0.0,
                    "bosses_used": 0,
                    "best_rank": np.nan,
                    "teams": present["teams"].max() if not present.empty else 0,
                    "bosses": present["bosses"].max() if not present.empty else 0,
                    "breadth": 0.0,
                }
            )
            present = pd.concat([present, blanks], ignore_index=True)
        filled.append(present)
    per_unit = pd.concat(filled, ignore_index=True)

    # score_delta is undefined for a unit nobody ran; treat it as neutral so a
    # missing measurement cannot masquerade as a bad one.
    per_unit["score_delta"] = per_unit["score_delta"].fillna(0.0)

    w_usage, w_perf, w_breadth = config.weights
    parts = []
    for season, group in per_unit.groupby("season", sort=False):
        group = group.copy()
        group["pct_usage"] = _percentile(group["weighted_pick_rate"])
        group["pct_performance"] = _percentile(group["score_delta"])
        group["pct_breadth"] = _percentile(group["breadth"])
        group["tier_score"] = (
            w_usage * group["pct_usage"]
            + w_perf * group["pct_performance"]
            + w_breadth * group["pct_breadth"]
        )
        parts.append(group)
    scored = pd.concat(parts, ignore_index=True)
    scored["tier"] = scored["tier_score"].map(lambda value: assign_tier(value, config))

    names = roster.set_index("unit_id")[["name_en", "name_ko", "burst", "unit_class", "element"]]
    scored = scored.join(names, on="unit_id")
    return scored.sort_values(["season", "tier_score"], ascending=[True, False]).reset_index(drop=True)


def assign_tier(score: float, config: TierConfig | None = None) -> str:
    config = config or TierConfig()
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return config.cuts[-1][0]
    for label, minimum in config.cuts:
        if score >= minimum:
            return label
    return config.cuts[-1][0]


def tier_changes(scored: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Per-unit tier movement between consecutive seasons.

    ``steps`` is positive for a promotion. This is the table that answers "which
    units did this patch actually change", and it is the one worth reading first
    after a new season lands.
    """
    config = config or TierConfig()
    if scored.empty:
        return pd.DataFrame()

    order = {label: i for i, label in enumerate(config.tier_order)}
    seasons = season_order(scored["season"])
    by_season = {s: scored[scored["season"] == s].set_index("unit_id") for s in seasons}

    rows = []
    for previous, current in zip(seasons, seasons[1:]):
        before, after = by_season[previous], by_season[current]
        for unit_id in sorted(set(before.index) | set(after.index)):
            tier_before = before.loc[unit_id, "tier"] if unit_id in before.index else None
            tier_after = after.loc[unit_id, "tier"] if unit_id in after.index else None
            if tier_before is None and tier_after is None:
                continue
            steps = (
                order[tier_before] - order[tier_after]
                if tier_before is not None and tier_after is not None
                else np.nan
            )
            score_before = float(before.loc[unit_id, "tier_score"]) if unit_id in before.index else np.nan
            score_after = float(after.loc[unit_id, "tier_score"]) if unit_id in after.index else np.nan
            rows.append(
                {
                    "season_from": previous,
                    "season_to": current,
                    "unit_id": unit_id,
                    "name_en": (after if unit_id in after.index else before).loc[unit_id, "name_en"],
                    "tier_from": tier_before,
                    "tier_to": tier_after,
                    "steps": steps,
                    "tier_score_from": score_before,
                    "tier_score_to": score_after,
                    "tier_score_delta": score_after - score_before,
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values("tier_score_delta", ascending=False).reset_index(drop=True)


def summarise(scored: pd.DataFrame) -> dict[str, Any]:
    if scored.empty:
        return {}
    return {
        "seasons": season_order(scored["season"]),
        "tier_counts": {
            season: group["tier"].value_counts().to_dict()
            for season, group in scored.groupby("season")
        },
    }
