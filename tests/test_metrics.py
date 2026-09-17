"""The metrics are checked against a world whose answers are known in advance.

See ``tests/synthetic.py`` for how that world is constructed.
"""

import numpy as np
import pandas as pd
import pytest

from nikke_analysis.analyze import metrics, tiers
from tests.synthetic import make_world


@pytest.fixture(scope="module")
def world():
    return make_world()


@pytest.fixture(scope="module")
def availability(world):
    return metrics.build_availability(world.roster, world.entries, world.calendar)


@pytest.fixture(scope="module")
def usage(world, availability):
    return metrics.unit_usage(world.entries, world.roster, availability=availability)


def test_rank_weight_is_decreasing_and_positive():
    weights = metrics.rank_weight(pd.Series([1, 2, 10, 50]))
    assert weights[0] > weights[1] > weights[2] > weights[3] > 0
    assert weights[0] == pytest.approx(1.0)


def test_season_order_is_numeric_not_lexical():
    assert metrics.season_order(["10", "9", "2"]) == ["2", "9", "10"]


def test_teams_frame_collapses_five_rows_into_one(world):
    teams = metrics.teams_frame(world.entries)
    assert (teams["slots"] <= metrics.TEAM_SIZE).all()
    assert len(teams) == world.entries.groupby(
        metrics.GROUP_KEYS + ["rank"]
    ).ngroups


def test_pick_rate_is_a_share_of_teams(usage):
    assert usage["pick_rate"].between(0, 1).all()
    assert usage["weighted_pick_rate"].between(0, 1).all()


def test_weighted_usage_sums_to_team_size_worth_of_share(usage):
    """Five slots per team, so the weighted shares over a group sum to ~5."""
    totals = usage.groupby(metrics.GROUP_KEYS)["weighted_pick_rate"].sum()
    assert np.allclose(totals, metrics.TEAM_SIZE, atol=0.35)


def test_availability_grows_and_never_shrinks(world, availability):
    sizes = [availability.size(s) for s in metrics.season_order(world.entries["season"])]
    assert sizes == sorted(sizes)
    assert availability.source == "season_calendar"


def test_availability_falls_back_when_no_calendar(world):
    inferred = metrics.build_availability(world.roster, world.entries, None)
    assert inferred.source == "inferred_from_entries"
    sizes = [inferred.size(s) for s in metrics.season_order(world.entries["season"])]
    assert sizes == sorted(sizes)


def test_lift_is_one_for_a_baseline_unit(usage):
    """Lift divides out the roster size, so it is comparable across seasons."""
    assert (usage["lift"] > 0).all()
    baseline = usage["baseline_pick_rate"] * usage["roster_size"]
    assert np.allclose(baseline, metrics.TEAM_SIZE)


def test_score_delta_is_defined_and_finite_where_measurable(usage):
    measurable = usage[usage["picks"] < usage["teams"]]
    assert measurable["score_delta"].notna().any()
    assert np.isfinite(measurable["score_delta"].dropna()).all()


def test_meta_shift_spikes_when_a_dominant_unit_arrives(world, usage):
    shift = metrics.meta_shift(usage, world.roster)
    assert set(shift.columns) >= {"total_variation", "jsd", "top_k_churn", "newcomer_share"}
    assert shift["total_variation"].between(0, 1).all()
    assert shift["jsd"].between(0, 1).all()

    arrival = shift[shift["season_to"] == world.newcomer_season]
    others = shift[shift["season_to"] != world.newcomer_season]
    assert not arrival.empty
    assert arrival["total_variation"].iloc[0] > others["total_variation"].max()
    assert arrival["newcomer_share"].iloc[0] > 0


def test_identical_distributions_have_zero_divergence():
    p = np.array([0.5, 0.3, 0.2])
    assert metrics.jensen_shannon(p, p) == pytest.approx(0.0, abs=1e-12)
    disjoint = metrics.jensen_shannon(np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    assert disjoint == pytest.approx(1.0)


def test_synergy_finds_the_pair_that_is_always_run_together(world):
    pairs = metrics.synergy(world.entries)
    expected = tuple(sorted(world.core_pair))
    top = pairs.head(5)[["unit_id_x", "unit_id_y"]].apply(tuple, axis=1).tolist()
    assert expected in top
    assert (pairs["lift"] > 0).all()


def test_trajectories_put_the_peak_at_or_near_debut(world, usage):
    arcs = metrics.trajectories(usage)
    assert {"debut_season", "peak_season", "retention"}.issubset(arcs.columns)
    newcomer = arcs[arcs["unit_id"] == world.newcomer]
    assert not newcomer.empty
    assert newcomer["debut_season"].iloc[0] == world.newcomer_season


def test_tier_scores_cover_every_available_unit(world, usage, availability):
    scored = tiers.season_unit_scores(usage, world.roster, availability)
    for season in metrics.season_order(world.entries["season"]):
        rows = scored[scored["season"] == season]
        assert len(rows) == availability.size(season)
        assert rows["unit_id"].is_unique


def test_tier_labels_are_monotone_in_score(world, usage, availability):
    config = tiers.load_tier_config()
    scored = tiers.season_unit_scores(usage, world.roster, availability, config)
    order = {label: i for i, label in enumerate(config.tier_order)}
    ranked = scored.sort_values("tier_score", ascending=False)
    positions = ranked["tier"].map(order).tolist()
    assert positions == sorted(positions)


def test_assign_tier_uses_the_configured_cuts():
    config = tiers.TierConfig(cuts=[("S", 80.0), ("A", 50.0), ("B", 0.0)])
    assert tiers.assign_tier(95, config) == "S"
    assert tiers.assign_tier(50, config) == "A"
    assert tiers.assign_tier(0, config) == "B"
    assert tiers.assign_tier(float("nan"), config) == "B"


def test_tier_changes_reports_movement_with_sign(world, usage, availability):
    scored = tiers.season_unit_scores(usage, world.roster, availability)
    changes = tiers.tier_changes(scored)
    assert {"tier_from", "tier_to", "steps", "tier_score_delta"}.issubset(changes.columns)
    promoted = changes[changes["steps"] > 0]
    assert (promoted["tier_score_delta"] > 0).all()


def test_empty_inputs_return_empty_frames_not_exceptions(world):
    empty = world.entries.iloc[0:0]
    assert metrics.unit_usage(empty, world.roster).empty
    assert metrics.synergy(empty).empty
    assert metrics.trajectories(pd.DataFrame()).empty
