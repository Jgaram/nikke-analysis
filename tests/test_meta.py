"""The meta measures (analyze/meta.py): the generality mix of the units in use, weakness
similarity, the own-element share and the debuts."""

import pandas as pd
import pytest

from nikke_analysis.analyze import meta, tiers
from tests.test_tiers import monthly_table

ROTATION = ["Fire", "Water", "Wind", "Iron", "Electric"] * 2


def per_element(general: bool):
    parts = [monthly_table({e: [1.0 if general or w == e else 0.0 for w in ROTATION]}, ROTATION, element=e)
             for e in ROTATION[:5]]
    return pd.concat([t for t, _ in parts], ignore_index=True), parts[0][1]


def test_similarity_and_share_see_the_units_follow_the_weakness():
    split, seasons = per_element(False)
    same, _ = per_element(True)
    assert meta.weakness_similarity(split, seasons).tolist() == [0.0] * 6  # from the fifth: four others before it
    assert meta.weakness_similarity(same, seasons).tolist() == pytest.approx([1.0] * 6)
    assert meta.own_share(split).tolist() == [1.0] * 10 and meta.own_share(same).tolist() == pytest.approx([0.2] * 10)


def test_the_usage_mix_counts_units_by_their_generality_in_the_window():
    weak = ["Fire", "Water", "Wind"] * 6  # monthly: a year back from a season holds it and the eleven before
    lifts = {"special": [1.0 if w == "Fire" else 0.0 for w in weak], "general": [1.0] * 18,
             "narrowed": [1.0] * 9 + [1.0 if w == "Fire" else 0.0 for w in weak[9:]], "never": [0.05] * 18,
             "gone": [1.0] * 12 + [0.0] * 6}  # out after season 12: retired once Fire 13 and 16 pass it by
    table, seasons = monthly_table(lifts, weak)
    mix = meta.usage_mix(table, seasons, tiers.TierConfig())
    assert mix.loc[1].tolist() == [0, 0, 0, 0, 0]  # no other-element season yet
    assert mix.loc[6].tolist() == [4, 1, 0, 3, 0]  # "narrowed" still general, "gone" too
    # a year back from season 18 holds two of "narrowed"'s other-element seasons at 1.0 of eight: X 0.25, g 0.4;
    # "gone" was in use over that year, but retired by then: left out, and counted apart
    assert mix.loc[18].tolist() == [3, 1, 1, 1, 1]
    short = meta.usage_mix(table, seasons, tiers.TierConfig(meta_window_days=200))  # six or seven seasons back
    # seasons 12-18: "narrowed" is down to its Fire seasons; "gone" played season 12, and is still left out
    assert short.loc[18].tolist() == [3, 2, 0, 1, 1]


def test_debuts_read_a_units_first_year():
    weak = ["Fire", "Water", "Wind"] * 6
    lifts = {"special": [None] * 2 + [1.0 if w == "Fire" else 0.0 for w in weak[2:]], "general": [1.0] * 18,
             "late": [None] * 12 + [1.0] * 6, "never": [0.05] * 18}
    table, seasons = monthly_table(lifts, weak)
    first = meta.debuts(table, seasons, tiers.TierConfig()).set_index("unit_id")
    assert set(first.index) == {"special", "general"}  # "late"'s year is not over; "never" was not in use
    assert first.loc["special", ["first", "generality"]].tolist() == [4, 0.0]  # first fielded in Fire season 4
    assert first.loc["general", ["first", "generality"]].tolist() == [1, 1.0]
