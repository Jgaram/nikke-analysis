"""Season tiers, element tiers and overall tiers, against the synthetic world."""

import pandas as pd
import pytest

from nikke_analysis.analyze import metrics, tiers
from nikke_analysis.timeline import parse_element
from tests.synthetic import make_world


@pytest.fixture(scope="module")
def world():
    return make_world()


def build(world, roster=None):
    seasons = metrics.season_frame(world.seasons.astype(str))
    roster = world.roster if roster is None else roster
    table = tiers.season_tiers(metrics.unit_season(world.entries, roster, seasons), tiers.TierConfig())
    summary = metrics.season_summary(world.entries, seasons)
    return table, summary


@pytest.fixture(scope="module")
def built(world):
    return build(world)


@pytest.fixture(scope="module")
def skilled(world):
    """The same world, with a skill that adds Wind to the (Water) partner's own element."""
    extra = world.roster["unit_id"].map({world.partner: "Wind"}).fillna("")
    return build(world, world.roster.assign(extra_elements=extra))


TREASURE_SEASON = 6  # the first season the partner plays with its treasure


@pytest.fixture(scope="module")
def treasure_skilled(world):
    """The same world, where the (Water) partner's treasure, out before season 6, adds Wind:
    of the Wind-weak seasons, 3 is before it and 8 after."""
    start = pd.Timestamp(world.seasons.set_index("season").loc[TREASURE_SEASON, "start_at"])
    roster = world.roster.assign(treasure_at="", treasure_elements="")
    mine = roster["unit_id"] == world.partner
    roster.loc[mine, "treasure_at"] = (start - pd.Timedelta(days=7)).isoformat()
    roster.loc[mine, "treasure_elements"] = "Wind"
    return build(world, roster)


def standing_at(built, moment, config=None):
    table, summary = built
    return tiers.standings(table, summary, pd.Timestamp(moment), config or tiers.TierConfig())


def overall_at(built, moment, config=None):
    return standing_at(built, moment, config).overall.set_index("unit_id")


def element_at(built, moment, unit_id, element, config=None):
    rows = standing_at(built, moment, config).elements
    return rows[(rows["unit_id"] == unit_id) & (rows["element"] == element)].iloc[0]


def newest(built):
    return built[1]["collected_until"].max()


def settled(world, built):
    """The day after the last finished season: the live one not started yet."""
    return built[1].set_index("season").loc[world.live_season - 1, "end_at"] + pd.Timedelta(days=1)


def tiny(lifts, *, element="Fire", extra="", live=()):
    """One unit's standing from hand-made seasons: ``lifts`` maps a boss weakness
    to the unit's lift in a season of it (one season each, a week apart, in that
    order); a weakness in ``live`` is the season in progress, collected so far."""
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    seasons, rows = [], []
    for number, (weak, lift) in enumerate(lifts.items(), start=1):
        end = start + pd.Timedelta(days=7 * number)
        seasons.append({"season": number, "weak_element": weak, "end_at": end, "final": weak not in live,
                        "collected_on": end - pd.Timedelta(days=2)})
        rows.append({"season": number, "unit_id": "001", "lift": lift, "element": element, "extra_elements": extra})
    summary = pd.DataFrame(seasons)
    moment = summary["end_at"].max() + pd.Timedelta(days=1)
    return tiers.standings(pd.DataFrame(rows), summary, moment, tiers.TierConfig(half_life_days=0))


def overall_of(standing):
    return standing.overall.iloc[0]


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
        "element: {half_life_days: 90, prior_strength: 1, overall: frequency, min_elements_observed: 2,\n"
        "          include_live: false}\n"
        "lifespan: {min_usage: 0.25, retire_after_days: 200, retire_after_own_seasons: 2}\n",
        encoding="utf-8",
    )
    config = tiers.load_tier_config(path)
    assert config.top_n == 20 and config.servers == ("KR",) and config.rank_weighting == "uniform"
    assert config.tier_order == ["S", "A", "B"]
    assert config.half_life_days == 90 and config.prior_strength == 1 and config.overall == "frequency"
    assert config.min_elements_observed == 2 and not config.include_live
    assert config.min_usage == 0.25 and config.retire_after_days == 200 and config.retire_after_own_seasons == 2


def test_repo_config_loads():
    config = tiers.load_tier_config()
    assert config.tier_order[0] == "SS" and config.overall in tiers.OVERALL_MODES and config.include_live
    assert [l for l, _ in config.overall_cuts] == config.tier_order
    assert all(o < c for (_, o), (_, c) in zip(config.overall_cuts[:-1], config.cuts[:-1]))


def test_the_overall_tier_has_cuts_of_its_own():
    """An element-SS specialist that sits out the rest is SS in its element and, on the lower overall cuts, A."""
    config = tiers.TierConfig()
    assert tiers.assign_tier(1.4, config) == "SS"
    assert tiers.assign_tier(1.4 / 5, config) == "C"
    assert tiers.assign_tier(0.3, config, overall=True) == "A"
    standing = tiny({"Fire": 1.5})
    assert overall_of(standing)["overall"] == pytest.approx(0.3)
    assert overall_of(standing)["overall_tier"] == "A" and standing.elements.iloc[0]["element_tier"] == "SS"


def test_overall_cuts_follow_custom_cuts_unless_given():
    custom = [("S", 1.0), ("A", 0.5), ("B", 0.0)]
    assert tiers.TierConfig(cuts=custom).overall_cuts == custom
    given = tiers.TierConfig(cuts=custom, overall_cuts=[("B", 0.0), ("S", 0.4), ("A", 0.2)])
    assert given.overall_cuts == [("S", 0.4), ("A", 0.2), ("B", 0.0)]
    with pytest.raises(ValueError):
        tiers.TierConfig(cuts=custom, overall_cuts=[("SS", 0.4), ("A", 0.2), ("B", 0.0)])


def test_bad_parameters_are_rejected():
    with pytest.raises(ValueError):
        tiers.TierConfig(overall="median")


@pytest.mark.parametrize("name", ["작열", "fire", " Fire ", "FIRE"])
def test_an_element_is_named_in_either_language(name):
    assert parse_element(name) == "Fire"


def test_an_unknown_element_lists_the_names():
    with pytest.raises(LookupError, match="작열\\(Fire\\)"):
        parse_element("불")


def test_tier_labels_are_monotone_in_lift(built):
    table, _ = built
    config = tiers.TierConfig()
    ranked = table.sort_values("lift", ascending=False)
    positions = ranked["tier"].map(lambda t: tiers.tier_rank(t, config)).tolist()
    assert positions == sorted(positions)


def test_a_dealer_is_top_of_its_element_and_weak_overall(world, built):
    overall = overall_at(built, settled(world, built))
    for element, unit_id in world.element_dps.items():
        row = element_at(built, settled(world, built), unit_id, element)
        assert row["source"] == "own"
        assert row["element_tier"] == "SS" and row["element_rank"] == 1
        assert overall.loc[unit_id, "overall"] < 0.6  # worth little in four elements out of five


def test_a_partner_earns_its_overall_in_the_element_it_supports(world, built):
    """A Water support fielded only in Wind-weak seasons: low in Water, but not overall."""
    row = element_at(built, newest(built), world.partner, "Water")
    overall = overall_at(built, newest(built)).loc[world.partner]
    assert row["element_lift"] < 0.5
    assert overall["overall"] > row["element_lift"]


def test_supports_that_go_anywhere_are_strong_in_both(world, built):
    overall = overall_at(built, newest(built))
    own = world.roster.set_index("unit_id")["element"]
    for unit_id in world.universal:
        assert element_at(built, newest(built), unit_id, own[unit_id])["element_tier"] in ("SS", "S")
        assert overall.loc[unit_id, "overall_tier"] in ("SS", "S")


def test_a_skill_element_puts_a_unit_in_both_element_tables(world, built, skilled):
    standing = standing_at(skilled, newest(skilled))
    mine = standing.elements[standing.elements["unit_id"] == world.partner].set_index("element")
    assert mine["source"].to_dict() == {"Water": "own", "Wind": "skill"}
    assert mine.loc["Wind", "element_tier"] in ("SS", "S") and mine.loc["Water", "element_lift"] < 0.5
    wind = standing.elements[standing.elements["element"] == "Wind"]
    assert {world.partner, world.element_dps["Wind"]} <= set(wind["unit_id"])
    assert wind["element_rank"].max() == len(wind)  # ranked among the Wind units, itself included
    # The overall never looked at the unit's own element, so a skill element leaves it alone.
    plain = overall_at(built, newest(built))["overall"].sort_index()
    pd.testing.assert_series_equal(standing.overall.set_index("unit_id")["overall"].sort_index(), plain)


def test_a_skill_element_counts_as_the_units_own(world, skilled):
    table, _ = skilled
    partner = table[table["unit_id"] == world.partner]
    assert partner["element_match"].equals(partner["weak_element"].isin(["Water", "Wind"]))


def test_an_element_the_treasure_adds_is_the_units_from_the_treasure_on(world, treasure_skilled):
    table, _ = treasure_skilled
    partner = table[table["unit_id"] == world.partner].set_index("season")
    assert list(partner.index[partner["element_match"]]) == [2, 7, 8]  # Water always, Wind with the treasure
    assert list(partner.index[partner["treasure"]]) == list(range(TREASURE_SEASON, 11))


def test_an_element_the_treasure_adds_is_tiered_on_its_side_only(world, treasure_skilled):
    table, summary = treasure_skilled
    moment = newest(treasure_skilled)

    def mine(treasured):
        standing = tiers.standings(table, summary, moment, tiers.TierConfig(), treasured=treasured)
        return standing.elements[standing.elements["unit_id"] == world.partner].set_index("element")

    with_it = mine([world.partner])
    assert with_it["source"].to_dict() == {"Water": "own", "Wind": "skill"}
    assert with_it.loc["Wind", "element_seasons"] == 1  # season 8 alone
    assert mine([])["source"].to_dict() == {"Water": "own"}  # before it, Water only
    # A season's element tier follows its side: Wind-weak season 3 was not the partner's, 8 was.
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    rows = history[history["unit_id"] == world.partner].set_index("season")
    assert pd.isna(rows.loc[3, "element_lift"]) and pd.notna(rows.loc[8, "element_lift"])


def test_the_past_is_viewed_without_the_future(world, built):
    """As of the newcomer's release week, it does not exist in the standings yet."""
    table, summary = built
    before = summary.set_index("season").loc[world.newcomer_season - 1, "end_at"] + pd.Timedelta(days=1)
    standing = standing_at(built, before)
    assert world.newcomer not in set(standing.overall["unit_id"]) | set(standing.elements["unit_id"])
    assert standing.overall["last_season"].max() == world.newcomer_season - 1


def test_the_season_in_progress_counts_once_collected(world, built):
    """The live season counts as far as it was collected - not before its first snapshot, and not at all
    without include_live."""
    _, summary = built
    collected = summary.set_index("season").loc[world.live_season, "collected_on"]
    assert overall_at(built, newest(built))["last_season"].max() == world.live_season
    assert overall_at(built, collected - pd.Timedelta(hours=1))["last_season"].max() == world.live_season - 1
    without = overall_at(built, newest(built) + pd.Timedelta(days=30), tiers.TierConfig(include_live=False))
    assert without["last_season"].max() == world.live_season - 1
    # The newcomer (Electric) meets its first Electric season in the live one: a tier there, and first.
    electric = world.seasons.set_index("season").loc[world.live_season, "weak_element"]
    row = element_at(built, newest(built), world.newcomer, electric)
    assert row["element_seasons"] == 1 and row["element_rank"] == 1
    counted = tiers.counted_seasons(summary, newest(built))
    assert counted.loc[counted["live"], "season"].tolist() == [world.live_season]


def test_other_elements_come_from_other_elements():
    """Seen in its own element and one other: the three unseen others take the other's level, not its own."""
    standing = tiny({"Fire": 1.5, "Water": 0.0})
    overall = overall_of(standing)
    assert overall["overall"] == pytest.approx((1.5 + 0.0 * 4) / 5)
    assert overall["elements_observed"] == 2 and bool(overall["provisional"])
    assert standing.elements.iloc[0]["element_lift"] == pytest.approx(1.5)
    # two others seen: the unseen others take their mean
    assert overall_of(tiny({"Fire": 1.5, "Water": 0.2, "Wind": 0.6}))["overall"] == pytest.approx((1.5 + 0.2 + 0.6 + 0.4 * 2) / 5)


def test_with_no_other_element_seen_the_others_count_zero():
    """Fielded in its own element only so far: taken for a specialist, not given its own level elsewhere."""
    standing = tiny({"Fire": 1.2})
    overall = overall_of(standing)
    assert overall["overall"] == pytest.approx(1.2 / 5) and bool(overall["provisional"])
    slots = standing.slots.set_index("element")
    assert slots.loc["Water", "lift"] == 0 and slots.loc["Water", "seasons"] == 0


def test_an_unseen_own_element_counts_zero():
    """Seen in other elements only: its own slot is not guessed from them, and the overall is provisional."""
    standing = tiny({"Water": 1.0, "Wind": 1.5, "Iron": 0.5, "Electric": 1.0})
    overall = overall_of(standing)
    assert overall["overall"] == pytest.approx((0 + 1.0 + 1.5 + 0.5 + 1.0) / 5)
    assert overall["elements_observed"] == 4 and bool(overall["provisional"])
    own = standing.elements.iloc[0]
    assert own["element"] == "Fire" and pd.isna(own["element_lift"]) and own["element_tier"] == ""


def test_a_skill_elements_unseen_slot_counts_zero():
    """Fire with Iron by skill, seen in Fire and Water: Iron is its own side, and an own slot is not guessed -
    not from Fire either (Sugar's Iron is not what it did in Water with its treasure)."""
    standing = tiny({"Fire": 1.5, "Water": 0.5}, extra="Iron")
    assert overall_of(standing)["overall"] == pytest.approx((1.5 + 0.0 + 0.5 * 3) / 5)
    iron = standing.elements.set_index("element").loc["Iron"]
    assert iron["source"] == "skill" and iron["element_seasons"] == 0 and pd.isna(iron["element_lift"])


def test_the_live_season_stands_in_for_what_is_not_over_yet():
    """Makoto's case: one Fire season over, a Water one in progress where nobody fields it."""
    live = overall_of(tiny({"Fire": 1.09, "Water": 0.0}, live=("Water",)))
    assert live["overall"] == pytest.approx(1.09 / 5) and live["last_season"] == 2 and bool(live["provisional"])


def test_an_element_not_met_yet_has_no_tier_and_the_overall_is_provisional(world, built):
    """Seen in one boss weakness, not its own: no element tier, and a provisional overall."""
    table, summary = built
    moment = summary.set_index("season").loc[world.newcomer_season, "end_at"] + pd.Timedelta(days=1)
    standing = standing_at(built, moment)
    overall = standing.overall.set_index("unit_id").loc[world.newcomer]
    assert overall["elements_observed"] == 1 and bool(overall["provisional"])
    electric = standing.elements[standing.elements["element"] == "Electric"]
    row = electric[electric["unit_id"] == world.newcomer].iloc[0]
    assert row["element_seasons"] == 0 and pd.isna(row["element_lift"]) and row["element_tier"] == ""
    assert pd.isna(row["element_rank"]) and electric["unit_id"].iloc[-1] == world.newcomer  # listed last


def test_recent_seasons_weigh_more(world, built):
    """With a short half-life the latest Fire season dominates; with none, all count alike."""
    fire = world.element_dps["Fire"]
    short = element_at(built, newest(built), fire, "Fire", tiers.TierConfig(half_life_days=1))["element_lift"]
    flat = element_at(built, newest(built), fire, "Fire", tiers.TierConfig(half_life_days=0))["element_lift"]
    table, _ = built
    fire_seasons = table[(table["unit_id"] == fire) & (table["weak_element"] == "Fire") & (table["season"] < world.live_season)]
    latest = fire_seasons.sort_values("season")["lift"].iloc[-1]
    assert short == pytest.approx(latest, rel=1e-3)
    assert flat == pytest.approx(fire_seasons["lift"].mean(), rel=1e-6)


def test_prior_strength_pulls_a_specialist_toward_its_average(world, built):
    fire = world.element_dps["Fire"]
    plain = element_at(built, newest(built), fire, "Fire")["element_lift"]
    pulled = element_at(built, newest(built), fire, "Fire", tiers.TierConfig(prior_strength=2))["element_lift"]
    assert pulled < plain


def test_overall_modes(world, built):
    fire = world.element_dps["Fire"]
    mean = overall_at(built, newest(built), tiers.TierConfig(overall="mean")).loc[fire, "overall"]
    best = overall_at(built, newest(built), tiers.TierConfig(overall="max")).loc[fire, "overall"]
    freq = overall_at(built, newest(built), tiers.TierConfig(overall="frequency")).loc[fire, "overall"]
    assert best > mean
    assert 0 < freq < best


def test_history_carries_where_each_unit_stood(world, built):
    table, summary = built
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    assert len(history) == len(table)
    assert history["overall"].notna().all()
    assert not history.loc[history["season"] == world.live_season, "final"].any()
    dealer = history[history["unit_id"] == world.element_dps["Water"]].sort_values("season")
    own = (dealer["weak_element"] == "Water").to_numpy()
    assert dealer.loc[own, "element_tier"].eq("SS").all()  # after each Water season
    assert dealer.loc[~own, "element_tier"].isna().all()  # nothing to say in the others


def test_history_gives_a_skill_element_its_seasons_too(world, skilled):
    table, summary = skilled
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    partner = history[(history["unit_id"] == world.partner) & history["final"]]
    mine = partner["weak_element"].isin(["Water", "Wind"])
    assert partner.loc[mine, "element_tier"].notna().all() and partner.loc[~mine, "element_tier"].isna().all()
    wind = partner[partner["weak_element"] == "Wind"]
    assert wind["element_tier"].isin(["SS", "S"]).all()


def test_tier_changes_have_signed_steps(built):
    table, summary = built
    history = tiers.tier_history(table, summary, tiers.TierConfig())
    changes = tiers.tier_changes(history)
    promoted = changes[changes["steps"] > 0]
    assert not promoted.empty
    assert (promoted["lift_to"] > promoted["lift_from"]).all()
    # An element tier moves only in a season of that element.
    weak = summary.set_index("season")["weak_element"]
    moved = changes[changes["element_steps"] != 0]
    assert (moved["element"] == moved["season_to"].map(weak)).all()
    assert changes.loc[changes["element"] == "", "element_steps"].eq(0).all()


# --------------------------------------------------------------------------
# lifespans


def seasons_monthly(usage, *, live=False, weak=None):
    """Hand-made seasons a month apart (a week long each), unit "001" (Fire) fielded by
    ``usage[i]`` of the rankers in season i + 1; ``weak`` gives the seasons' boss weaknesses
    (by default every one Fire, the unit's own); with ``live`` the last is in progress."""
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    weak = weak or ["Fire"] * len(usage)
    seasons, rows = [], []
    for number, (share, element) in enumerate(zip(usage, weak, strict=True), start=1):
        begin = start + pd.DateOffset(months=number - 1)
        end = begin + pd.Timedelta(days=7)
        last = number == len(usage)
        seasons.append({"season": number, "weak_element": element, "start_at": begin, "end_at": end,
                        "final": not (live and last), "collected_on": begin + pd.Timedelta(days=3)})
        rows.append({"season": number, "unit_id": "001", "usage_rate": share, "element_match": element == "Fire"})
    return pd.DataFrame(rows), pd.DataFrame(seasons)


def life_of(usage, moment, *, live=False, weak=None, **config):
    table, summary = seasons_monthly(usage, live=live, weak=weak)
    return tiers.lifespans(table, summary, pd.Timestamp(moment), tiers.TierConfig(**config)).iloc[0]


def test_a_lifespan_runs_from_the_first_season_that_used_the_unit_to_the_last():
    # used in seasons 2-5 (10% or more), out but unused in 1 and 6
    life = life_of([0.05, 0.4, 0.1, 0.02, 0.9, 0.0], "2024-07-01T00:00:00Z")
    assert (life["first_used"], life["run_from"], life["last_used"]) == (2, 2, 5)
    assert (life["seasons_used"], life["seasons_out"], life["returns"]) == (3, 6, 0)
    assert life["idle_days"] == pytest.approx(54.0) and life["missed_own"] == 1  # since 2024-05-08; June was Fire
    assert not life["retired"]  # under 90 days


def test_three_months_unused_through_a_season_of_its_element_is_retired():
    usage = [0.5] * 3 + [0.0] * 13  # used in January-March 2024, then not; every boss weak to Fire, its element
    assert not life_of(usage, "2024-06-01T00:00:00Z")["retired"]  # under 90 days since March 8
    life = life_of(usage, "2024-06-10T00:00:00Z")
    assert life["retired"] and life["missed_own"] == 3  # the Fire seasons of April, May and June went by
    assert not life_of(usage, "2024-06-10T00:00:00Z", retire_after_days=120)["retired"]
    assert not life_of(usage, "2024-06-10T00:00:00Z", retire_after_own_seasons=4)["retired"]
    back = life_of(usage + [0.6], "2025-06-01T00:00:00Z")  # used again in May 2025
    assert (back["first_used"], back["run_from"], back["last_used"], back["returns"]) == (1, 17, 17, 1)
    assert not back["retired"] and back["missed_own"] == 0


def test_a_specialist_waiting_for_its_element_is_not_retired():
    # a Fire dealer used in January 2024, then ten months of other bosses' weaknesses, then Fire again
    weak = ["Fire"] + ["Water", "Wind", "Iron", "Electric", "Water"] * 2 + ["Fire"]
    waiting = life_of([0.5] + [0.0] * 10, "2024-11-20T00:00:00Z", weak=weak[:-1])
    assert waiting["idle_days"] > 300 and waiting["missed_own"] == 0 and not waiting["retired"]
    assert life_of([0.5] + [0.0] * 10, "2024-11-20T00:00:00Z", weak=weak[:-1], retire_after_own_seasons=0)["retired"]
    # its element comes round and passes it by: retired; or it is used there: in use all along
    assert life_of([0.5] + [0.0] * 11, "2024-12-20T00:00:00Z", weak=weak)["retired"]
    kept = life_of([0.5] + [0.0] * 10 + [0.4], "2024-12-20T00:00:00Z", weak=weak)
    assert (kept["run_from"], kept["returns"], kept["retired"]) == (1, 0, False)


def test_a_gap_is_a_return_only_when_long_and_through_a_season_of_its_element():
    usage = [0.5] + [0.0] * 6 + [0.5]  # used in January and August 2024, 206 days apart
    assert life_of(usage, "2024-09-01T00:00:00Z")["returns"] == 1  # every boss weak to Fire: it sat out six
    assert life_of(usage, "2024-09-01T00:00:00Z", weak=["Fire"] + ["Water"] * 6 + ["Fire"])["returns"] == 0
    assert life_of(usage, "2024-09-01T00:00:00Z", retire_after_days=240)["returns"] == 0


def test_the_live_season_counts_as_in_use_now():
    life = life_of([0.0, 0.3], "2024-02-05T00:00:00Z", live=True)
    assert life["last_used"] == 2 and life["idle_days"] == 0
    assert pd.isna(life_of([0.0, 0.3], "2024-02-05T00:00:00Z", live=True, include_live=False)["last_used"])


def test_a_unit_no_season_used_has_no_lifespan():
    life = life_of([0.05, 0.0], "2026-01-01T00:00:00Z")
    assert pd.isna(life["first_used"]) and life["seasons_used"] == 0 and life["missed_own"] == 0
    assert not life["retired"]
