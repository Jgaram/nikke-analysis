"""The career study (lifecycle.py): the paths generalists took, the own-season outlook, eras."""

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


# --------------------------------------------------------------------------
# careers: the path a generalist took


def careers_of(lifts: dict[str, list[float]], weak: list[str], season: int, **kwargs) -> pd.DataFrame:
    """The paths at the end of ``season`` of units (all Fire) at a lift of ``lifts[unit][i]`` in
    season i + 1 of monthly seasons whose boss is weak to ``weak[i]``."""
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    seasons = pd.DataFrame([{"season": n, "weak_element": e, "start_at": start + pd.DateOffset(months=n - 1),
                             "end_at": start + pd.DateOffset(months=n - 1) + pd.Timedelta(days=7), "final": True,
                             "collected_on": start} for n, e in enumerate(weak, start=1)])
    table = pd.DataFrame([{"season": n, "unit_id": u, "lift": values[n - 1], "element_match": e == "Fire"}
                          for u, values in lifts.items() for n, e in enumerate(weak, start=1)])
    moment = seasons.set_index("season").loc[season, "end_at"]
    return lifecycle.careers(table, seasons, moment, tiers.TierConfig(), **kwargs).set_index("unit_id")


# Fire every third season: 1, 4, 7, 10, 13, 16
EVERY_THIRD = ["Fire", "Water", "Wind"] * 6


def test_careers_tell_the_two_ways_a_generalist_retires():
    everywhere = [1.0] * 6
    lifts = {
        "narrowed": everywhere + [1.0, 0, 0, 0.8, 0, 0] + [0.5, 0, 0, 0, 0, 0],  # own seasons only from 7, then out
        "dropped": everywhere + [0.0] * 12,  # out everywhere at once
        "still": [1.0] * 18,
        "special": [1.0 if w == "Fire" else 0.0 for w in EVERY_THIRD],  # own seasons only, ever
        "never": [0.01] * 18,  # season tier F throughout
    }
    early = careers_of(lifts, EVERY_THIRD, 12)
    assert early.loc[["narrowed", "still", "special", "dropped", "never"], "path"].tolist() == [
        "element_only", "generalist", "specialist", "retired_generalist", "unused"]
    assert tuple(early.loc["narrowed", ["other_used", "last_other", "other_since", "own_after"]]) == (4, 6, 4, 2)
    assert tuple(early.loc["special", ["other_used", "other_since", "own_after"]]) == (0, 8, 4)  # all its own seasons
    late = careers_of(lifts, EVERY_THIRD, 18)  # "narrowed" sat out Fire season 16, over 90 days after season 13
    assert late.loc["narrowed", "path"] == "retired_element_only" and late.loc["dropped", "path"] == "retired_generalist"
    assert late.loc["special", "path"] == "specialist"
    # one other-element season makes a generalist; a quicker bar for "left the others"
    once = {"once": [1.0 if w == "Fire" else 0.0 for w in EVERY_THIRD[:4]] + [1.0] + [0.0] * 13}
    assert careers_of(once, EVERY_THIRD, 6).loc["once", ["path", "other_used"]].tolist() == ["generalist", 1]
    assert careers_of(lifts, EVERY_THIRD, 8, left_after=1).loc["narrowed", "path"] == "element_only"
    assert careers_of(lifts, EVERY_THIRD, 8).loc["narrowed", "path"] == "generalist"  # left only one behind yet


def test_a_generalist_out_of_the_others_waits_for_its_own_season():
    weak = ["Fire", "Water", "Wind", "Iron", "Water", "Wind"]
    lifts = {"waiting": [1.0, 1.0, 1.0, 1.0, 0.0, 0.0]}  # out of the last two, and no Fire season since
    row = careers_of(lifts, weak, 6, left_after=2).loc["waiting"]
    assert row["path"] == "left_others" and (row["other_since"], row["own_after"]) == (2, 0)
    assert careers_of(lifts, weak, 6).loc["waiting", "path"] == "generalist"  # three to leave, by default
