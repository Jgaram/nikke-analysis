"""The career study (lifecycle.py): generality, career paths, the own-season outlook."""

import pandas as pd
import pytest

from nikke_analysis import lifecycle
from nikke_analysis.analyze import tiers
from tests.synthetic import make_world
from tests.test_tiers import build


@pytest.fixture(scope="module")
def world():
    return make_world()


def test_generality_splits_specialists_from_units_that_go_anywhere(world):
    table, summary = build(world)
    standing = tiers.standings(table, summary, summary["end_at"].max(), tiers.TierConfig())
    g = lifecycle.generality(standing).set_index("unit_id")
    for dealer in world.element_dps.values():  # strong only when the boss is weak to its element
        assert g.loc[dealer, "g"] < 0.05 and g.loc[dealer, "band"] == "특화"
    for unit in world.universal:  # strong everywhere
        assert g.loc[unit, "g"] == pytest.approx(0.5, abs=0.05) and g.loc[unit, "band"] == "범용"
    assert g.loc[world.partner, "g"] > 0.9  # a Water support that only Wind decks field
    # O and X are the numbers behind the two tiers: overall = (O + 4X) / 5
    overall = standing.overall.set_index("unit_id")["overall"]
    dealer = world.element_dps["Fire"]
    assert overall[dealer] == pytest.approx((g.loc[dealer, "O"] + 4 * g.loc[dealer, "X"]) / 5)


def monthly(usage: dict[str, list[float]], weak: list[str]):
    """Seasons a month apart, a week long; each unit (all Fire) fielded by ``usage[unit][i]``
    of the rankers in season i + 1, whose boss is weak to ``weak[i]``."""
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    seasons, rows = [], []
    for number, element in enumerate(weak, start=1):
        begin = start + pd.DateOffset(months=number - 1)
        seasons.append({"season": number, "weak_element": element, "start_at": begin,
                        "end_at": begin + pd.Timedelta(days=7), "final": True, "collected_on": begin})
        for unit_id, shares in usage.items():
            rows.append({"season": number, "unit_id": unit_id, "usage_rate": shares[number - 1],
                         "lift": 2 * shares[number - 1], "element_match": element == "Fire"})
    return pd.DataFrame(rows), pd.DataFrame(seasons)


# Fire every third season: 1, 4, 7, 10, 13, 16
WEAK = ["Fire", "Water", "Wind"] * 6


def test_careers_tell_the_two_ways_a_generalist_retires():
    everywhere = [0.8] * 6
    usage = {
        "narrowed": everywhere + [0.8, 0, 0, 0.5, 0, 0] + [0.3, 0, 0, 0, 0, 0],  # own seasons only from 7, then out
        "dropped": everywhere + [0.0] * 12,  # out everywhere at once
        "still": [0.8] * 18,
        "special": [0.8 if w == "Fire" else 0.0 for w in WEAK],  # own seasons only, ever
    }
    table, seasons = monthly(usage, WEAK)
    config = tiers.TierConfig()
    at = lambda season: seasons.set_index("season").loc[season, "end_at"]
    path = lambda season: lifecycle.careers(table, seasons, at(season), config).set_index("unit_id")["path"]
    early = path(12)
    assert early["narrowed"] == "속성 전용" and early["still"] == "범용" and early["special"] == "특화"
    assert early["dropped"] == "범용 → 은퇴"
    late = path(18)  # "narrowed" sat out Fire season 16, over 90 days after season 13
    assert late["narrowed"] == "범용 → 속성 전용 → 은퇴" and late["dropped"] == "범용 → 은퇴"
    row = lifecycle.careers(table, seasons, at(12), config).set_index("unit_id").loc["narrowed"]
    assert (row["other_used"], row["last_other"], row["other_since"], row["own_after"]) == (4, 6, 4, 2)


def test_the_outlook_counts_who_the_next_own_season_passed_by():
    usage = {"fading": [0.8 if w == "Fire" else 0.0 for w in WEAK[:12]],
             "gone": [0.8, 0, 0, 0.3, 0, 0, 0, 0, 0, 0, 0, 0]}
    usage["fading"][9] = 0.0  # used in Fire seasons 1, 4, 7, not 10
    table, seasons = monthly(usage, WEAK[:12])
    outlook = lifecycle.own_outlook(table, seasons, tiers.TierConfig())
    pairs = {(r.unit_id, r.season): (r.tier, r.stopped) for r in outlook.itertuples()}
    assert pairs == {("fading", 1): ("S 이상", False), ("fading", 4): ("S 이상", False), ("fading", 7): ("S 이상", True),
                     ("gone", 1): ("S 이상", False), ("gone", 4): ("B", True)}
    rates = lifecycle.stop_rates(outlook)
    assert rates.loc["S 이상", "rate"] == pytest.approx(1 / 4) and rates.loc["B", "rate"] == 1.0


def test_eras_run_ten_seasons_at_a_time_and_fold_a_short_tail():
    labels = lifecycle.eras_of(range(1, 42))
    assert (labels[1], labels[10], labels[11], labels[31], labels[41]) == ("S1-10", "S1-10", "S11-20", "S31-41",
                                                                           "S31-41")
    assert lifecycle.eras_of(range(1, 46))[45] == "S41-45"
