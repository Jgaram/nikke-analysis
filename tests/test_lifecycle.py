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


# --------------------------------------------------------------------------
# curves: the shape of a whole career


def season_table(lifts: dict[str, list[float | None]], weak: list[str], element: str = "Fire") -> pd.DataFrame:
    """Rows of units (``element``) at ``lifts[unit][i]`` in season i + 1, weak to ``weak[i]``;
    None = not out yet."""
    return pd.DataFrame([{"season": n, "unit_id": u, "lift": values[n - 1], "element_match": e == element,
                          "weak_element": e}
                         for u, values in lifts.items() for n, e in enumerate(weak, start=1) if values[n - 1] is not None])


def test_a_turn_is_an_own_season_and_the_others_after_it():
    weak = ["Water", "Fire", "Fire", "Wind", "Water", "Fire", "Iron"]
    turns = lifecycle.rotations(season_table({"a": [0.6, 1.0, 0.8, 0.3, 0.0, 0.5, 0.1]}, weak))
    first, second = turns.iloc[0], turns.iloc[1]
    # the Water season before the first Fire one, and Fire back to back, go in the first turn
    assert (first["own_season"], first["own"], first["others"]) == (2, pytest.approx(0.9), 3)
    assert first["other"] == pytest.approx(0.3) and first["generality"] == pytest.approx(2 * 0.3 / 1.2)
    assert (second["own_season"], second["own"], second["other"], second["others"]) == (6, 0.5, 0.1, 1)
    assert len(turns) == 2


def test_curves_tell_the_four_shapes_apart():
    everywhere = [1.0] * 6
    lifts = {
        "narrowed": everywhere + [1.0, 0, 0, 1.0, 0, 0] + [0.0] * 6,  # own seasons only from 7, then out
        "faded": everywhere + [0.4] * 3 + [0.0] * 9,  # down everywhere at once
        "general": [1.0] * 18,
        "special": [1.0 if w == "Fire" else 0.0 for w in EVERY_THIRD],
        "never": [0.1] * 18,  # under the C cut throughout
        "new": [None] * 15 + [1.0, 1.0, 1.0],  # one turn only
    }
    shapes = lifecycle.curves(season_table(lifts, EVERY_THIRD), tiers.TierConfig()).set_index("unit_id")
    assert shapes["curve"].to_dict() == {"narrowed": "narrowed", "faded": "faded", "general": "general",
                                         "special": "specialist", "never": "unused", "new": "unknown"}
    assert tuple(shapes.loc["narrowed", ["g_peak", "g_low", "narrow_turns"]]) == (1.0, 0.0, 2)
    assert shapes.loc["faded", "g_low"] == 1.0 and shapes.loc["faded", "declined"]
    assert not shapes.loc["general", "declined"]


def test_the_meta_index_sees_the_units_follow_the_weakness():
    weak = ["Fire", "Water", "Wind", "Iron", "Electric"] * 2

    def table(general: bool) -> pd.DataFrame:
        return pd.concat([season_table({e: [1.0 if general or w == e else 0.0 for w in weak]}, weak, element=e)
                          for e in weak[:5]], ignore_index=True)

    split, same = lifecycle.meta_index(table(False)), lifecycle.meta_index(table(True))
    assert split["same"].dropna().tolist() == [0.0] * 6  # from the fifth season: four others before it
    assert same["same"].dropna().tolist() == pytest.approx([1.0] * 6)
    assert split.loc[10, ["good_own", "good_other", "pool", "own_share"]].tolist() == [1, 0, 1, 1.0]
    assert same.loc[10, "good_other"] == 4 and same.loc[10, "own_share"] == pytest.approx(1 / 5)


def test_the_usage_mix_counts_units_by_their_generality_in_the_window():
    weak = ["Fire", "Water", "Wind"] * 6  # monthly: a year back from a season holds it and the eleven before
    lifts = {"special": [1.0 if w == "Fire" else 0.0 for w in weak], "general": [1.0] * 18,
             "narrowed": [1.0] * 9 + [1.0 if w == "Fire" else 0.0 for w in weak[9:]], "never": [0.05] * 18}
    table = season_table(lifts, weak)
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    table["start_at"] = table["season"].map(lambda n: start + pd.DateOffset(months=n - 1))
    mix = lifecycle.usage_mix(table, tiers.TierConfig())
    assert mix.loc[1, ["units", "specialist", "generalist"]].tolist() == [0, 0, 0]  # no other-element season yet
    assert mix.loc[6].tolist() == [3, 1, 0, 2]  # "narrowed" still general
    # a year back from season 18 holds two of its other-element seasons at 1.0 of eight: X 0.25, g 0.4
    assert mix.loc[18].tolist() == [3, 1, 1, 1]
