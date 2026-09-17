"""The measurements that turn leaderboards into a meta.

A leaderboard answers "who won". A meta answers "what is worth using, and how is
that changing". Getting from one to the other needs four ideas, and each one
exists to defuse a specific way the raw counts lie.

**Rank weighting.** The #1 team and the #50 team are not equal evidence. Usage is
weighted by ``1 / log2(rank + 1)``, the discount used in ranking evaluation: it
falls off fast near the top and flattens out, which matches how strongly a
placement signals "this is the best answer" rather than "this cleared".

**Availability censoring.** A unit that did not exist during a season did not
"fail to be picked" - it was not available. Counting those zeroes would drag every
historical average down and make old units look worse the longer they exist.
Seasons are therefore scored only over units that had been released, which is why
the release dates in the roster are load-bearing.

**Lift over baseline.** Raw pick rate is not comparable across time, because the
roster keeps growing: five slots shared among 120 units is a different baseline
from five among 200. Lift divides by the baseline a unit would get from pure
chance, so 1.0 always means "no better than random" whatever the year.

**Conditional performance.** Pick rate alone rewards fashion. The performance term
asks a different question - do teams containing this unit actually score higher
than teams that do not, within the same boss and season - so that a popular unit
carried by its teammates separates from one that raises the ceiling.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TEAM_SIZE = 5
GROUP_KEYS = ["content", "season", "boss"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def rank_weight(rank: pd.Series | np.ndarray) -> np.ndarray:
    """Discounted-cumulative-gain weighting: ``1 / log2(rank + 1)``."""
    ranks = np.asarray(rank, dtype=float)
    ranks = np.where(ranks < 1, 1.0, ranks)
    return 1.0 / np.log2(ranks + 1.0)


def _season_sort_key(season: str) -> tuple[int, str]:
    """Order seasons numerically when they look numeric, else lexically."""
    digits = "".join(ch for ch in str(season) if ch.isdigit())
    return (int(digits) if digits else 10**9, str(season))


def season_order(seasons) -> list[str]:
    return sorted({str(s) for s in seasons}, key=_season_sort_key)


def teams_frame(entries: pd.DataFrame) -> pd.DataFrame:
    """Collapse the long entry table back to one row per team.

    Scores are per team, so any score statistic computed on the long table would
    count each team five times.
    """
    return (
        entries.groupby(GROUP_KEYS + ["rank"], as_index=False)
        .agg(score=("score", "max"), player=("player", "first"), slots=("unit_id", "size"))
        .sort_values(GROUP_KEYS + ["rank"])
    )


def normalized_scores(teams: pd.DataFrame) -> pd.DataFrame:
    """Scores rescaled within each (season, boss) so groups are comparable.

    Solo Raid damage numbers inflate over time with power creep, so absolute
    scores cannot be compared across seasons. Within a group, each score is
    expressed as a fraction of that group's best.
    """
    out = teams.copy()
    group_max = out.groupby(GROUP_KEYS)["score"].transform("max")
    out["score_norm"] = np.where(group_max > 0, out["score"] / group_max, np.nan)
    return out


# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------

@dataclass
class Availability:
    """Which units count as available in each season, and how we know."""

    by_season: dict[str, set[str]]
    source: str

    def size(self, season: str) -> int:
        return len(self.by_season.get(str(season), set()))


def availability_from_calendar(
    roster: pd.DataFrame, calendar: pd.DataFrame, seasons: list[str]
) -> Availability:
    """Exact censoring: a unit is available once its release date precedes the
    season's start."""
    starts = {
        str(row["season"]): pd.to_datetime(row["start_date"], errors="coerce")
        for _, row in calendar.iterrows()
    }
    release = pd.to_datetime(roster["release_date"], errors="coerce")
    by_season: dict[str, set[str]] = {}
    for season in seasons:
        start = starts.get(str(season))
        if pd.isna(start):
            by_season[str(season)] = set(roster["unit_id"])
            continue
        by_season[str(season)] = set(roster.loc[release <= start, "unit_id"])
    return Availability(by_season, "season_calendar")


def availability_from_entries(
    roster: pd.DataFrame, entries: pd.DataFrame, seasons: list[str]
) -> Availability:
    """Fallback when no season calendar exists.

    Uses the data itself: the newest unit that actually appears in a season must
    have been released by then, so every unit released on or before that date was
    available too. That is a lower bound on the real roster - it can miss a unit
    that existed but nobody used - so it is reported as its own source rather
    than passed off as exact.
    """
    release = pd.to_datetime(roster["release_date"], errors="coerce")
    release_by_unit = dict(zip(roster["unit_id"], release))
    by_season: dict[str, set[str]] = {}
    ordered = season_order(seasons)
    cutoff = pd.Timestamp.min

    for season in ordered:
        picked = entries.loc[entries["season"].astype(str) == season, "unit_id"].unique()
        dates = [release_by_unit.get(u) for u in picked]
        dates = [d for d in dates if d is not None and not pd.isna(d)]
        if dates:
            # Monotonic: the roster never shrinks between seasons.
            cutoff = max(cutoff, max(dates))
        available = {
            unit
            for unit, date in release_by_unit.items()
            if date is not None and not pd.isna(date) and date <= cutoff
        }
        by_season[season] = available or set(roster["unit_id"])
    return Availability(by_season, "inferred_from_entries")


def build_availability(
    roster: pd.DataFrame, entries: pd.DataFrame, calendar: pd.DataFrame | None
) -> Availability:
    seasons = season_order(entries["season"])
    if calendar is not None and not calendar.empty and "start_date" in calendar.columns:
        return availability_from_calendar(roster, calendar, seasons)
    return availability_from_entries(roster, entries, seasons)


# --------------------------------------------------------------------------
# core metric table
# --------------------------------------------------------------------------

def unit_usage(
    entries: pd.DataFrame,
    roster: pd.DataFrame,
    *,
    availability: Availability | None = None,
    by_boss: bool = True,
) -> pd.DataFrame:
    """One row per unit per group, with every usage and performance measure.

    Columns:
      ``teams``                teams in the group
      ``picks``                teams containing the unit
      ``pick_rate``            picks / teams
      ``weighted_pick_rate``   rank-discounted share of the group's evidence
      ``lift``                 pick_rate / (TEAM_SIZE / available roster)
      ``mean_score_norm_with`` mean normalised score of teams using the unit
      ``score_delta``          that, minus the mean for teams not using it
      ``best_rank``            best placement the unit appears in
    """
    if entries.empty:
        return pd.DataFrame()

    keys = GROUP_KEYS if by_boss else ["content", "season"]
    work = entries.copy()
    work["season"] = work["season"].astype(str)
    work["boss"] = work["boss"].astype(str)

    teams = normalized_scores(teams_frame(work))
    teams["w"] = rank_weight(teams["rank"])

    team_keys = GROUP_KEYS + ["rank"]
    member = work.merge(teams[team_keys + ["score_norm", "w"]], on=team_keys, how="left")

    group_totals = teams.groupby(keys).agg(
        teams=("rank", "size"), w_total=("w", "sum"), score_mean=("score_norm", "mean")
    )

    agg = member.groupby(keys + ["unit_id"]).agg(
        picks=("rank", "nunique"),
        w_sum=("w", "sum"),
        mean_score_norm_with=("score_norm", "mean"),
        best_rank=("rank", "min"),
    )
    out = agg.join(group_totals, on=keys).reset_index()

    out["pick_rate"] = out["picks"] / out["teams"]
    out["weighted_pick_rate"] = np.where(out["w_total"] > 0, out["w_sum"] / out["w_total"], np.nan)

    # Mean score of the teams that did NOT use the unit, derived from the group
    # mean so it needs no second pass over the data.
    without_count = out["teams"] - out["picks"]
    total_score = out["score_mean"] * out["teams"]
    with_score = out["mean_score_norm_with"] * out["picks"]
    out["mean_score_norm_without"] = np.where(
        without_count > 0, (total_score - with_score) / without_count, np.nan
    )
    out["score_delta"] = out["mean_score_norm_with"] - out["mean_score_norm_without"]

    if availability is not None:
        roster_size = out["season"].map(lambda s: availability.size(s)).astype(float)
    else:
        roster_size = float(roster["unit_id"].nunique())
    out["roster_size"] = roster_size
    baseline = np.where(roster_size > 0, TEAM_SIZE / roster_size, np.nan)
    out["baseline_pick_rate"] = baseline
    out["lift"] = np.where(baseline > 0, out["pick_rate"] / baseline, np.nan)

    names = roster.set_index("unit_id")[["name_en", "name_ko", "burst", "unit_class", "element"]]
    out = out.join(names, on="unit_id")
    out = out.drop(columns=["w_sum", "w_total", "score_mean"])
    sort_keys = keys + ["weighted_pick_rate"]
    return out.sort_values(sort_keys, ascending=[True] * len(keys) + [False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# meta shift
# --------------------------------------------------------------------------

def _distribution(usage: pd.DataFrame, season: str, units: list[str]) -> np.ndarray:
    """Usage share over a fixed unit axis, so two seasons can be compared."""
    subset = usage[usage["season"].astype(str) == str(season)]
    share = subset.groupby("unit_id")["weighted_pick_rate"].sum()
    vector = np.array([share.get(unit, 0.0) for unit in units], dtype=float)
    total = vector.sum()
    return vector / total if total > 0 else vector


def jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """JSD in bits: 0 = identical metas, 1 = no overlap at all."""
    mask = (p > 0) | (q > 0)
    p, q = p[mask], q[mask]
    if p.sum() == 0 or q.sum() == 0:
        return float("nan")
    m = 0.5 * (p + q)

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        nz = a > 0
        return float(np.sum(a[nz] * np.log2(a[nz] / b[nz])))

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def meta_shift(
    usage: pd.DataFrame, roster: pd.DataFrame, *, top_k: int = 20
) -> pd.DataFrame:
    """How much the meta moved between each pair of consecutive seasons.

    ``total_variation`` is the headline number and reads directly as a
    percentage: 0.18 means 18% of the rank-weighted usage moved to different
    units. ``jsd`` is the same idea on a log scale and is less swayed by one
    dominant unit. ``top_k_churn`` answers the practical question - how much of
    the tier list you would have to rewrite.

    ``newcomer_share`` splits the movement into "new units arrived" versus "the
    order among existing units changed", which is what separates a patch that
    added a strong unit from one that re-tuned the old ones.
    """
    seasons = season_order(usage["season"])
    if len(seasons) < 2:
        return pd.DataFrame()

    units = sorted(usage["unit_id"].unique())
    release = dict(
        zip(roster["unit_id"], pd.to_datetime(roster["release_date"], errors="coerce"))
    )

    rows = []
    for previous, current in zip(seasons, seasons[1:]):
        p = _distribution(usage, previous, units)
        q = _distribution(usage, current, units)

        prev_units = set(usage.loc[usage["season"].astype(str) == previous, "unit_id"])
        newcomers = {u for u in usage.loc[usage["season"].astype(str) == current, "unit_id"] if u not in prev_units}
        newcomer_mass = float(sum(q[i] for i, u in enumerate(units) if u in newcomers))

        top_prev = set(pd.Series(p, index=units).nlargest(top_k).index)
        top_curr = set(pd.Series(q, index=units).nlargest(top_k).index)

        rows.append(
            {
                "season_from": previous,
                "season_to": current,
                "total_variation": float(0.5 * np.abs(p - q).sum()),
                "jsd": jensen_shannon(p, q),
                "top_k": top_k,
                "top_k_churn": len(top_curr - top_prev) / top_k if top_k else np.nan,
                "entrants": ", ".join(sorted(top_curr - top_prev)),
                "leavers": ", ".join(sorted(top_prev - top_curr)),
                "newcomer_share": newcomer_mass,
                "units_in_use": int((q > 0).sum()),
                "effective_units": float(
                    math.exp(-np.sum(q[q > 0] * np.log(q[q > 0])))
                ),  # perplexity: how many units the meta *behaves* like it has
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# synergy
# --------------------------------------------------------------------------

def synergy(entries: pd.DataFrame, *, min_teams: int = 3) -> pd.DataFrame:
    """Which pairs of units are run together more than chance would predict.

    Uses pointwise mutual information on co-occurrence within a team. Solo Raid
    teams are built around two- and three-unit cores, and PMI surfaces those
    cores without being dominated by whichever unit is simply most popular.
    """
    if entries.empty:
        return pd.DataFrame()

    work = entries.copy()
    work["season"] = work["season"].astype(str)
    team_key = work[GROUP_KEYS + ["rank"]].astype(str).agg("|".join, axis=1)
    work = work.assign(team_key=team_key)

    total_teams = work["team_key"].nunique()
    if total_teams == 0:
        return pd.DataFrame()

    unit_teams = work.groupby("unit_id")["team_key"].nunique()
    pairs = work[["team_key", "unit_id"]].merge(work[["team_key", "unit_id"]], on="team_key")
    pairs = pairs[pairs["unit_id_x"] < pairs["unit_id_y"]]
    counts = pairs.groupby(["unit_id_x", "unit_id_y"])["team_key"].nunique().reset_index(name="together")
    counts = counts[counts["together"] >= min_teams]
    if counts.empty:
        return pd.DataFrame()

    p_x = counts["unit_id_x"].map(unit_teams) / total_teams
    p_y = counts["unit_id_y"].map(unit_teams) / total_teams
    p_xy = counts["together"] / total_teams
    counts["lift"] = p_xy / (p_x * p_y)
    counts["pmi"] = np.log2(counts["lift"])
    counts["support"] = p_xy
    return counts.sort_values("pmi", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# per-unit trajectory
# --------------------------------------------------------------------------

def trajectories(usage: pd.DataFrame) -> pd.DataFrame:
    """Each unit's arc: when it debuted, when it peaked, where it is now.

    ``seasons_since_peak`` and ``retention`` are how power creep shows up in the
    data - a unit whose retention has collapsed has been replaced, even if it is
    still technically usable.
    """
    if usage.empty:
        return pd.DataFrame()

    ordered = season_order(usage["season"])
    position = {season: i for i, season in enumerate(ordered)}
    per_season = (
        usage.groupby(["unit_id", "season"], as_index=False)["weighted_pick_rate"].sum()
    )
    per_season["season_index"] = per_season["season"].astype(str).map(position)
    per_season = per_season.sort_values(["unit_id", "season_index"])

    rows = []
    for unit_id, group in per_season.groupby("unit_id"):
        used = group[group["weighted_pick_rate"] > 0]
        if used.empty:
            continue
        peak = used.loc[used["weighted_pick_rate"].idxmax()]
        latest = group.iloc[-1]
        peak_value = float(peak["weighted_pick_rate"])
        rows.append(
            {
                "unit_id": unit_id,
                "debut_season": str(used.iloc[0]["season"]),
                "peak_season": str(peak["season"]),
                "peak_weighted_pick_rate": peak_value,
                "latest_season": str(latest["season"]),
                "latest_weighted_pick_rate": float(latest["weighted_pick_rate"]),
                "seasons_active": int((group["weighted_pick_rate"] > 0).sum()),
                "seasons_since_peak": int(latest["season_index"] - peak["season_index"]),
                "retention": float(latest["weighted_pick_rate"] / peak_value) if peak_value > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("peak_weighted_pick_rate", ascending=False).reset_index(drop=True)
