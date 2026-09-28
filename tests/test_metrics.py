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
def seasons(world):
    return metrics.season_frame(world.seasons.astype(str))


@pytest.fixture(scope="module")
def table(world, seasons):
    return tiers.season_tiers(metrics.unit_season(world.entries, world.roster, seasons), tiers.TierConfig())


def test_rank_weight_is_decreasing_and_positive():
    weights = metrics.rank_weight(pd.Series([1, 2, 10, 50]))
    assert weights[0] > weights[1] > weights[2] > weights[3] > 0
    assert weights[0] == pytest.approx(1.0)
    assert (metrics.rank_weight([1, 50], "uniform") == 1.0).all()
    with pytest.raises(ValueError):
        metrics.rank_weight([1], "linear")


def test_population_filters_rank_and_server(world):
    top = metrics.select_population(world.entries, top_n=10)
    assert top["rank"].max() == 10
    one = metrics.select_population(world.entries, top_n=50, servers=("S1",))
    assert set(one["server"]) == {"S1"}


def test_deck_shares_sum_to_one_per_player(world):
    decks = metrics.deck_table(world.entries)
    totals = decks.groupby(metrics.RANKER_KEYS)["share"].sum()
    assert np.allclose(totals, 1.0)
    assert (decks.groupby(metrics.RANKER_KEYS)["is_main"].sum() >= 1).all()


def test_credit_is_a_distribution_over_units(table):
    assert np.allclose(table.groupby("season")["credit"].sum(), 1.0)
    assert table["presence"].between(0, 1).all()


def test_lift_averages_one_over_the_fielded_slots(table):
    """25 slots share the damage, so the lift of the fielded units averages 1 per slot."""
    for _, group in table.groupby("season"):
        fielded = group[group["rankers"] > 0]
        weighted = (fielded["lift"] * fielded["presence"]).sum() / fielded["presence"].sum()
        assert 0.6 < weighted < 1.6
        assert group["slots"].iloc[0] == 25


def test_main_deck_units_carry_more_than_back_deck_units(world, table):
    season = table[table["season"] == 1]
    fire = season[season["unit_id"] == world.element_dps["Fire"]].iloc[0]
    assert fire["lift"] > 1.4 and fire["main_deck_rate"] > 0.9 and fire["tier"] == "SS"
    back = season[(season["rankers"] > 0)].sort_values("lift").iloc[0]
    assert back["lift"] < 1.0


def test_every_released_unit_gets_a_row_and_unused_ones_read_zero(world, table):
    unused = table[table["unit_id"].isin(world.never_used)]
    assert not unused.empty
    assert (unused["lift"] == 0).all() and (unused["tier"] == "D").all()
    assert unused["deck_effect"].isna().all()
    assert table.groupby("season")["unit_id"].apply(lambda s: s.is_unique).all()


def test_units_do_not_exist_before_their_release(world, table):
    before = table[(table["season"] < world.newcomer_season) & (table["unit_id"] == world.newcomer)]
    assert before.empty
    debut = table[(table["season"] == world.newcomer_season) & (table["unit_id"] == world.newcomer)]
    assert debut["lift"].iloc[0] > 1.4


def test_element_match_follows_the_boss_weakness(world, table):
    rows = table[table["unit_id"] == world.element_dps["Water"]]
    assert (rows.loc[rows["element_match"], "lift"].min()) > rows.loc[~rows["element_match"], "lift"].max()


def test_deck_effect_sees_the_newcomer_raise_its_deck(world, table):
    effect = table[(table["unit_id"] == world.newcomer) & (table["season"] >= world.newcomer_season)]["deck_effect"]
    assert (effect > 0).all()


def test_season_summary_marks_the_season_in_progress(world, seasons):
    summary = metrics.season_summary(world.entries, seasons)
    live = summary.set_index("season").loc[world.live_season]
    assert not live["final"]
    assert summary[summary["season"] != world.live_season]["final"].all()
    assert (summary["rankers"] == 40).all()


def test_meta_shift_is_bounded_and_sees_the_newcomer(world, table):
    shift = metrics.meta_shift(table)
    assert set(shift.columns) >= {"total_variation", "jsd", "top_k_churn", "newcomer_share", "effective_units"}
    assert shift["total_variation"].between(0, 1).all()
    assert shift["jsd"].between(0, 1).all()
    arrival = shift[shift["season_to"] == world.newcomer_season].iloc[0]
    assert arrival["newcomer_share"] > 0.03


def test_identical_distributions_have_zero_divergence():
    p = np.array([0.5, 0.3, 0.2])
    assert metrics.jensen_shannon(p, p) == pytest.approx(0.0, abs=1e-12)
    assert metrics.jensen_shannon(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_synergy_finds_the_pair_that_always_shares_a_deck(world):
    pairs = metrics.synergy(world.entries, min_decks=10)
    season = pairs[pairs["season"] == 1]
    expected = tuple(sorted(world.core_pair))
    together = season[(season["unit_id_x"] == expected[0]) & (season["unit_id_y"] == expected[1])]
    assert not together.empty and together["pmi"].iloc[0] > 1.0


def test_trajectories_put_the_newcomer_debut_where_it_was_released(world, table):
    arcs = metrics.trajectories(table)
    newcomer = arcs[arcs["unit_id"] == world.newcomer].iloc[0]
    assert newcomer["debut_season"] == world.newcomer_season
    assert {"peak_season", "retention", "latest_tier"}.issubset(arcs.columns)


def test_empty_inputs_return_empty_frames_not_exceptions(world, seasons):
    empty = world.entries.iloc[0:0]
    assert metrics.unit_season(empty, world.roster, seasons).empty
    assert metrics.synergy(empty).empty
    assert metrics.trajectories(pd.DataFrame()).empty


def test_a_deck_that_dealt_no_damage_was_not_fought(world, seasons):
    entries = world.entries[world.entries["season"] == 1].copy()
    player = entries["player"].iloc[0]
    unfought = (entries["player"] == player) & (entries["deck"] == 3)
    benched = set(entries.loc[unfought, "unit_id"])
    entries.loc[unfought, "deck_score"] = 0

    population = metrics.select_population(entries)
    assert not (population["deck_score"] <= 0).any()
    summary = metrics.season_summary(population, seasons).iloc[0]
    assert summary["decks"] == 5 * summary["rankers"] - 1

    before = metrics.unit_season(world.entries[world.entries["season"] == 1], world.roster, seasons).set_index("unit_id")
    after = metrics.unit_season(population, world.roster, seasons).set_index("unit_id")
    assert (after.loc[list(benched), "rankers"] == before.loc[list(benched), "rankers"] - 1).all()


def test_deck_rank_follows_damage_not_the_order_decks_were_listed(world):
    listed = world.entries.copy()
    listed["deck"] = 6 - listed["deck"]  # the synthetic world lists decks strongest first; reverse that
    decks = metrics.deck_table(listed)
    strongest = decks.loc[decks.groupby(metrics.RANKER_KEYS)["deck_score"].idxmax()]
    assert (strongest["deck_rank"] == 1).all() and strongest["is_main"].all()
    assert decks.groupby(metrics.RANKER_KEYS)["deck_rank"].apply(lambda r: sorted(r) == [1, 2, 3, 4, 5]).all()
    pd.testing.assert_frame_equal(metrics.deck_split(listed), metrics.deck_split(world.entries))


def test_deck_split_accounts_for_every_user(world, table):
    assert (table[metrics.DECK_SPLIT].sum(axis=1) == table["rankers"]).all()
    used = table[table["rankers"] > 0]
    assert used["avg_deck"].between(1, 5).all()
    assert table.loc[table["rankers"] == 0, "avg_deck"].isna().all()
    # the newcomer is the strongest unit from its release on: the main deck, nearly always
    newcomer = table[(table["unit_id"] == world.newcomer) & (table["season"] >= world.newcomer_season)]
    assert (newcomer["avg_deck"] < 1.2).all()


def test_usage_rate_and_rank_count_players_without_weights(world, table):
    players = world.entries.drop_duplicates(metrics.RANKER_KEYS).groupby("season").size()
    assert np.allclose(table["usage_rate"], table["rankers"] / table["season"].map(players))
    for _, group in table.groupby("season"):
        expected = group["rankers"].rank(method="min", ascending=False).astype(int)
        assert (group["usage_rank"] == expected).all()  # ties share a rank: 1, 1, 3
