"""The career study (lifecycle.py): the own-season outlook, eras."""

import pandas as pd
import pytest

from nikke_analysis import lifecycle
from nikke_analysis.analyze import tiers


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


# Fire every third season: 1, 4, 7, 10
WEAK = ["Fire", "Water", "Wind"] * 4


def test_the_outlook_counts_who_the_next_own_season_passed_by():
    usage = {"fading": [0.8 if w == "Fire" else 0.0 for w in WEAK],
             "gone": [0.8, 0, 0, 0.3, 0, 0, 0, 0, 0, 0, 0, 0]}
    usage["fading"][9] = 0.0  # used in Fire seasons 1, 4, 7, not 10
    table, seasons = monthly(usage, WEAK)
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
