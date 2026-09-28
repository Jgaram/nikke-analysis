"""Season tiers, element profiles and roles, against the synthetic world."""

import pandas as pd
import pytest

from nikke_analysis.analyze import metrics, tiers
from tests.synthetic import make_world


@pytest.fixture(scope="module")
def world():
    return make_world()


@pytest.fixture(scope="module")
def built(world):
    seasons = metrics.season_frame(world.seasons.astype(str))
    table = tiers.season_tiers(metrics.unit_season(world.entries, world.roster, seasons), tiers.TierConfig())
    summary = metrics.season_summary(world.entries, seasons)
    return table, summary


def profile_at(built, moment, config=None):
    table, summary = built
    return tiers.element_profiles(table, summary, pd.Timestamp(moment), config or tiers.TierConfig()).set_index("unit_id")


def newest(built):
    return built[1]["collected_until"].max()


def test_assign_tier_uses_the_cuts():
    config = tiers.TierConfig(cuts=[("S", 1.0), ("A", 0.5), ("B", 0.0)])
    assert tiers.assign_tier(1.2, config) == "S"
    assert tiers.assign_tier(0.5, config) == "A"
    assert tiers.assign_tier(0.0, config) == "B"
    assert tiers.assign_tier(float("nan"), config) == ""


def test_config_file_round_trip(tmp_path):
    path = tmp_path / "tiers.yaml"
    path.write_text(
        "population: {top_n: 20, servers: [KR], rank_weighting: uniform}\n"
        "cuts: [{label: S, min_lift: 1.2}, {label: A, min_lift: 0.6}, {label: B, min_lift: 0}]\n"
        "element: {half_life_days: 90, prior_strength: 1, overall: frequency, coverage_min_tier: A}\n"
        "roles: {min_elements_observed: 2, viable_fraction: 0.4}\n",
        encoding="utf-8",
    )
    config = tiers.load_tier_config(path)
    assert config.top_n == 20 and config.servers == ("KR",) and config.rank_weighting == "uniform"
    assert config.tier_order == ["S", "A", "B"]
    assert config.half_life_days == 90 and config.prior_strength == 1 and config.overall == "frequency"
    assert config.min_elements_observed == 2 and config.viable_fraction == 0.4


def test_repo_config_loads():
    config = tiers.load_tier_config()
    assert config.tier_order[0] == "SS" and config.overall in tiers.OVERALL_MODES


def test_bad_parameters_are_rejected():
    with pytest.raises(ValueError):
        tiers.TierConfig(overall="median")
    with pytest.raises(ValueError):
        tiers.TierConfig(coverage_min_tier="Z")


def test_tier_labels_are_monotone_in_lift(built):
    table, _ = built
    config = tiers.TierConfig()
    ranked = table.sort_values("lift", ascending=False)
    positions = ranked["tier"].map(lambda t: tiers.tier_rank(t, config)).tolist()
    assert positions == sorted(positions)


def test_a_dealer_is_a_specialist_in_its_own_element(world, built):
    profiles = profile_at(built, newest(built))
    for element, unit_id in world.element_dps.items():
        row = profiles.loc[unit_id]
        assert row["role"] == "specialist"
        assert row["best_element"] == element
        assert row["best_tier"] == "SS"
        assert row["overall"] < 0.6  # worth little in four elements out of five


def test_a_partner_follows_the_element_of_the_deck_it_supports(world, built):
    row = profile_at(built, newest(built)).loc[world.partner]
    assert row["best_element"] == "Wind"  # its own element is Water
    assert row["role"] == "specialist"


def test_supports_that_go_anywhere_are_universal(world, built):
    profiles = profile_at(built, newest(built))
    for unit_id in world.universal:
        row = profiles.loc[unit_id]
        assert row["role"] == "universal"
        assert row["coverage"] == 5
        assert row["overall_tier"] in ("SS", "S")


def test_the_past_is_viewed_without_the_future(world, built):
    """As of the newcomer's release week, it does not exist in the profiles yet."""
    table, summary = built
    before = summary.set_index("season").loc[world.newcomer_season - 1, "end_at"] + pd.Timedelta(days=1)
    profiles = profile_at(built, before)
    assert world.newcomer not in profiles.index
    assert profiles["last_season"].max() == world.newcomer_season - 1


def test_the_season_in_progress_never_counts(world, built):
    profiles = profile_at(built, newest(built) + pd.Timedelta(days=30))
    assert profiles["last_season"].max() == world.live_season - 1


def test_an_unobserved_slot_borrows_the_unit_level_and_is_flagged(world, built):
    """Seen in few elements: the rest borrow its level, and the overall is provisional."""
    table, summary = built
    moment = summary.set_index("season").loc[world.newcomer_season, "end_at"] + pd.Timedelta(days=1)
    row = profile_at(built, moment).loc[world.newcomer]
    assert row["elements_observed"] == 1 and bool(row["provisional"])
    assert row["role"] == "undetermined"
    observed = [c for c in ("fire", "water", "wind", "iron", "electric") if row[f"n_{c}"] > 0]
    assert len(observed) == 1
    values = {row[f"lift_{c}"] for c in ("fire", "water", "wind", "iron", "electric")}
    assert len({round(v, 9) for v in values}) == 1


def test_recent_seasons_weigh_more(world, built):
    """With a short half-life the latest Fire season dominates; with none, all count alike."""
    fire = world.element_dps["Fire"]
    short = profile_at(built, newest(built), tiers.TierConfig(half_life_days=1)).loc[fire, "lift_fire"]
    flat = profile_at(built, newest(built), tiers.TierConfig(half_life_days=0)).loc[fire, "lift_fire"]
    table, _ = built
    fire_seasons = table[(table["unit_id"] == fire) & (table["weak_element"] == "Fire") & (table["season"] < world.live_season)]
    latest = fire_seasons.sort_values("season")["lift"].iloc[-1]
    assert short == pytest.approx(latest, rel=1e-3)
    assert flat == pytest.approx(fire_seasons["lift"].mean(), rel=1e-6)


def test_prior_strength_pulls_a_specialist_toward_its_average(world, built):
    fire = world.element_dps["Fire"]
    plain = profile_at(built, newest(built)).loc[fire, "lift_fire"]
    pulled = profile_at(built, newest(built), tiers.TierConfig(prior_strength=2)).loc[fire, "lift_fire"]
    assert pulled < plain


def test_overall_modes(world, built):
    fire = world.element_dps["Fire"]
    mean = profile_at(built, newest(built), tiers.TierConfig(overall="mean")).loc[fire, "overall"]
    best = profile_at(built, newest(built), tiers.TierConfig(overall="max")).loc[fire, "overall"]
    freq = profile_at(built, newest(built), tiers.TierConfig(overall="frequency")).loc[fire, "overall"]
    assert best > mean
    assert 0 < freq < best


def test_role_thresholds_are_parameters(world, built):
    strict = tiers.TierConfig(universal_min_share=1.0, viable_fraction=0.95)
    roles = profile_at(built, newest(built), strict)["role"]
    assert (roles == "hybrid").any()


def test_history_carries_the_profile_as_of_each_season(world, built):
    table, summary = built
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    assert len(history) == len(table)
    assert history["overall"].notna().all()
    assert not history.loc[history["season"] == world.live_season, "final"].any()
    dealer = history[history["unit_id"] == world.element_dps["Water"]].sort_values("season")
    assert dealer["role"].iloc[-1] == "specialist"


def test_tier_changes_have_signed_steps(built):
    table, summary = built
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    changes = tiers.tier_changes(history)
    promoted = changes[changes["steps"] > 0]
    assert not promoted.empty
    assert (promoted["lift_to"] > promoted["lift_from"]).all()
