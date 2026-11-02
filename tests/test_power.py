"""체급 (power.py): weights read back from decks whose damage is a known product of their members."""

import numpy as np
import pandas as pd
import pytest

from nikke_analysis import power

UNITS = [f"u{i:02d}" for i in range(18)]
TRUE = {u: np.exp(0.08 * i) for i, u in enumerate(UNITS)} | {"p0": 1.5, "p1": 1.2}
CP_EFFECT = 0.25


def world(seasons=2, servers=2, players=30, seed=3):
    """Every player decks 15 of the units in three decks and the other three with the pair p0 + p1,
    who are never apart. A deck does the player's level x the product of its members' weights x
    (combat power / 100k) ^ 0.25 per member. "n0" is out but nobody decks it."""
    rng = np.random.default_rng(seed)
    rows = []
    for season in range(1, seasons + 1):
        for s in range(servers):
            for rank in range(1, players + 1):
                level = rng.uniform(1, 3)
                order = list(rng.permutation(UNITS))
                decks = [order[0:5], order[5:10], order[10:15], ["p0", "p1"] + order[15:18]]
                for number, deck in enumerate(decks, start=1):
                    cps = 1e5 * np.exp(rng.normal(0, 0.1, len(deck)))
                    score = level * 1e9 * np.prod([TRUE[u] for u in deck]) * np.prod((cps / 1e5) ** CP_EFFECT)
                    for unit, cp in zip(deck, cps):
                        rows.append({"season": season, "server": f"S{s}", "player": f"p{rank}", "rank": rank,
                                     "deck": number, "deck_score": score, "unit_id": unit, "unit_cp": cp})
    entries = pd.DataFrame(rows)
    table = pd.DataFrame([{"season": season, "unit_id": u, "element_match": False, "treasure": False}
                          for season in range(1, seasons + 1) for u in UNITS + ["p0", "p1", "n0"]])
    return entries, table


@pytest.fixture(scope="module")
def solved():
    entries, table = world()
    result = power.fit(power.cells(entries, table))
    exact = result.solve(ridge=1e-6)
    return entries, table, result, power.weights(result, reference=("u00", "other"), coef=exact).set_index("cell"), exact


def test_the_weights_come_back_against_the_reference(solved):
    _, _, _, table, _ = solved
    for unit in UNITS:
        assert table.at[f"{unit}:other", "weight"] == pytest.approx(TRUE[unit] / TRUE["u00"], rel=0.02)
        assert table.at[f"{unit}:other", "status"] == "ok"


def test_better_built_copies_are_taken_out(solved):
    *_, exact = solved
    assert exact[-1] == pytest.approx(CP_EFFECT, abs=0.03)


def test_two_units_never_apart_are_weighed_only_as_a_pair(solved):
    _, _, _, table, _ = solved
    pair = table.loc[["p0:other", "p1:other"]]
    assert set(pair["status"]) == {"pair"} and set(pair["partner"]) == {"p0:other", "p1:other"}
    assert pair["together"].min() == 1.0
    assert pair["pair_weight"].iloc[0] == pytest.approx(TRUE["p0"] * TRUE["p1"] / TRUE["u00"] ** 2, rel=0.03)


def test_a_unit_nobody_decked_has_no_weight_rather_than_zero(solved):
    entries, table_in, _, table, _ = solved
    assert power.unobserved(entries, table_in) == ["n0"]
    assert not any(cell.startswith("n0") for cell in table.index)


def test_the_check_on_swaps_finds_the_weights_hold():
    """Decks that differ by one member: with every deck a pure product, the other servers' weights
    predict the whole difference."""
    rng = np.random.default_rng(5)
    rows = []
    core = ["c1", "c2", "c3", "c4"]
    weight = {"a": 1.0, "b": 1.6, "c": 0.7} | {c: 1.0 for c in core} | {f"f{i}": np.exp(0.05 * i) for i in range(20)}
    for server in ("S1", "S2", "S3"):
        for rank in range(1, 41):
            fifth = ["a", "b", "c"][rank % 3]
            fillers = list(rng.permutation([f"f{i}" for i in range(20)]))[:10]
            decks = [core + [fifth], fillers[:5], fillers[5:]]
            for number, deck in enumerate(decks, start=1):
                score = 1e9 * np.prod([weight[u] for u in deck]) * rng.uniform(0.99, 1.01)
                rows += [{"season": 1, "server": server, "player": f"p{rank}", "rank": rank, "deck": number,
                          "deck_score": score, "unit_id": u, "unit_cp": 1e5} for u in deck]
    entries = pd.DataFrame(rows)
    table = pd.DataFrame({"season": 1, "unit_id": sorted(weight), "element_match": False, "treasure": False})
    check = power.swap_check(power.fit(power.cells(entries, table)), ridge=1e-6)
    assert check["slope"] == pytest.approx(1.0, abs=0.1) and check["corr"] > 0.9


def test_the_creep_is_the_weight_a_later_release_date_buys():
    roster = pd.DataFrame({"unit_id": ["a", "b", "c", "d"],
                           "release_date": ["2022-11-04", "2023-11-04", "2024-11-03", "2025-11-03"]})
    table = pd.DataFrame({"unit_id": ["a", "b", "c", "d"] * 2, "own": [True] * 4 + [False] * 4,
                          "treasure": False, "status": "ok",
                          "log": [0.0, 0.1, 0.2, 0.3] + [0.0, 0.05, 0.1, 0.15]})
    rates = power.creep(table, roster)
    assert rates["own"] == pytest.approx(np.exp(0.1), rel=0.01)
    assert rates["other"] == pytest.approx(np.exp(0.05), rel=0.01)


def test_the_overall_mixes_the_sides_by_how_often_the_boss_was_weak_to_the_unit():
    history = pd.DataFrame({"season": [1, 2, 3, 4] * 2, "unit_id": ["a"] * 4 + ["b"] * 4,
                            "weak_element": ["Fire", "Water", "Water", "Iron"] * 2,
                            "element": ["Fire"] * 4 + ["Water"] * 4, "extra_elements": [None] * 4 + ["Iron"] * 4,
                            "treasure_elements": None})
    share = power.own_share(history).set_index(["unit_id", "treasure"])["share"]
    assert share[("a", False)] == pytest.approx(0.25) and share[("b", False)] == pytest.approx(0.75)
    table = pd.DataFrame({"unit_id": ["a", "a", "b", "b", "c"], "own": [True, False, True, False, True], "treasure": False,
                          "log": [0.4, 0.0, 0.2, -0.2, 0.3], "se": 0.02, "status": ["ok", "ok", "ok", "provisional", "ok"]})
    combined = power.overall(table, history).set_index("unit_id")
    assert combined.at["a", "log"] == pytest.approx(0.1) and combined.at["a", "status"] == "ok"
    assert combined.at["b", "log"] == pytest.approx(0.1) and combined.at["b", "status"] == "provisional"
    assert "c" not in combined.index  # never weighed in other seasons: no 종합


def test_the_field_is_the_strongest_cells_out_that_season():
    history = pd.DataFrame({"season": [1, 1, 2, 2, 2], "unit_id": ["a", "b", "a", "b", "c"],
                            "element_match": [True, False, False, False, True], "treasure": False})
    table = pd.DataFrame({"cell": ["a:own", "b:other", "a:other", "c:own"], "log": [np.log(2), 0.0, 0.0, np.log(4)]})
    top = power.field_strength(table, history)
    assert top[1] == pytest.approx(np.sqrt(2)) and top[2] == pytest.approx(4 ** (1 / 3))


def test_the_site_gets_every_cell_and_the_field():
    entries, table = world()
    data = power.payload(entries, table, reference=("u00", "other"))
    by_cell = {(c["unit"], c["own"], c["treasure"]): c for c in data["cells"]}
    weights = power.weights(power.fit(power.cells(entries, table)), reference=("u00", "other")).set_index("cell")
    assert by_cell[("u00", False, False)]["log"] == 0.0
    assert by_cell[("u05", False, False)]["log"] == pytest.approx(weights.at["u05:other", "log"], abs=1e-4)
    pair = by_cell[("p0", False, False)]
    assert pair["status"] == "pair" and pair["partner"] == "p1"
    assert pair["pairLog"] == pytest.approx(np.log(weights.at["p0:other", "pair_weight"]), abs=1e-4)
    assert [season for season, _ in data["field"]] == [1, 2] and all(v > 1 for _, v in data["field"])
    assert data["treasureFrom"] == {}
    assert data["overall"] == []  # nobody played a season of their own element: no 종합


def test_the_site_gets_the_season_a_treasure_first_played():
    entries, table = world()
    table.loc[(table["unit_id"] == "u03") & (table["season"] == 2), "treasure"] = True
    data = power.payload(entries, table, reference=("u00", "other"))
    assert data["treasureFrom"] == {"u03": 2}
    assert {(c["unit"], c["treasure"]) for c in data["cells"] if c["unit"] == "u03"} == {("u03", False), ("u03", True)}


def test_no_site_data_without_the_reference():
    entries, table = world()
    assert power.payload(entries, table, reference=("zz", "own")) is None


def _rows(entries):
    """The roster and season table the split needs: one element, no treasure, bosses weak to another."""
    units = sorted(entries["unit_id"].unique())
    roster = pd.DataFrame({"unit_id": units, "element": "Fire", "release_date": "2022-11-04"})
    seasons = pd.DataFrame({"season": sorted(entries["season"].unique())})
    seasons["start_at"] = pd.to_datetime("2023-01-01", utc=True) + pd.to_timedelta(28 * seasons["season"], unit="D")
    seasons["end_at"] = seasons["start_at"] + pd.Timedelta(days=7)
    seasons = seasons.assign(weak_element="Water", boss_en="", boss_ko="")
    return roster, seasons


def test_the_tiers_split_by_the_weights_the_decks_had_shown_by_then():
    entries, _ = world(seasons=3)
    roster, seasons = _rows(entries)
    split = power.split_weights(entries, roster, seasons).set_index(["season", "unit_id"])["weight"]
    # the ridge holds the weights back while the decks are few, less with every season that comes in
    gaps = [split[(season, "u10")] - split[(season, "u00")] for season in (1, 2, 3)]
    assert 0.8 * np.log(TRUE["u10"] / TRUE["u00"]) < gaps[0] < gaps[1] < gaps[2] < np.log(TRUE["u10"] / TRUE["u00"])
    pair = split[(3, "p0")] + split[(3, "p1")] - 2 * split[(3, "u00")]  # a pair: only the two together
    assert pair == pytest.approx(np.log(TRUE["p0"] * TRUE["p1"] / TRUE["u00"] ** 2), rel=0.1)
    # a season's weights do not move when later seasons come in
    early = power.split_weights(entries[entries["season"] == 1], roster, seasons).set_index(["season", "unit_id"])
    assert split.loc[1].to_numpy() == pytest.approx(early["weight"].loc[1].to_numpy())
    assert "n0" not in split.index.get_level_values("unit_id")  # nobody decked it: no weight


def _fielded(spec, seed=0):
    """Decks from ``{season: [(decks, units), ...]}``: that many decks of those units, each the first deck
    of a player of its own, filled up to five from fifteen fillers drawn at random (no two fillers are a pair)."""
    rng = np.random.default_rng(seed)
    rows = []
    for season, kinds in spec.items():
        player = 0
        for count, units in kinds:
            for _ in range(count):
                player += 1
                deck = list(units) + list(rng.permutation([f"f{i:02d}" for i in range(15)]))[:5 - len(units)]
                rows += [{"season": season, "server": "S0", "player": f"p{player}", "deck": 1, "unit_id": u}
                         for u in deck]
    return pd.DataFrame(rows)


def _groups(found):
    return {season: sorted(rows.groupby("group")["unit_id"].apply(tuple)) for season, rows in found.groupby("season")}


def test_units_decked_together_since_the_later_one_came_are_a_group():
    # x is decked without y before y came (season 1), then always with it; p, q, r always together
    entries = _fielded({1: [(40, ["x"]), (40, ["p", "q", "r"])],
                        2: [(40, ["x", "y"]), (40, ["p", "q", "r"])],
                        3: [(40, ["x", "y"])],
                        4: [(40, ["x"]), (40, ["y"])]})  # they split
    found = _groups(power.together(entries))
    assert 1 not in found  # one season together is not a pair yet
    assert found[2] == [("p", "q", "r")]  # x and y: only y's first season so far
    assert found[3] == [("x", "y")]  # x's decks before y came do not count against the pair
    assert 4 not in found  # apart from then on ...
    early = _groups(power.together(entries[entries["season"] <= 3]))
    assert {s: found[s] for s in (2, 3)} == early  # ... and the seasons before keep theirs


def test_a_pair_needs_two_seasons_with_enough_decks_together():
    # 35 decks together in y's first season and a handful in the next: enough decks, one real season
    entries = _fielded({1: [(35, ["x", "y"])], 2: [(5, ["x", "y"])], 3: [(10, ["x", "y"])]})
    found = _groups(power.together(entries))
    assert sorted(found) == [3] and found[3] == [("x", "y")]


def test_a_group_shares_its_weight_evenly_and_keeps_its_part_of_the_deck():
    from nikke_analysis.analyze import metrics

    split = pd.DataFrame({"season": [1] * 5 + [2], "unit_id": ["a", "b", "c", "d", "e", "a"],
                          "weight": [0.9, -0.2, 0.3, 0.0, 0.1, 0.9]})
    groups = pd.DataFrame({"season": [1, 1], "unit_id": ["a", "b"], "group": ["a", "a"]})
    pooled = power.pool(split, groups)
    assert np.exp(pooled["weight"].iloc[:2]).tolist() == pytest.approx([(np.exp(0.9) + np.exp(-0.2)) / 2] * 2)
    assert pooled["weight"].iloc[2:].tolist() == split["weight"].iloc[2:].tolist()  # nobody else, no other season
    deck = pd.DataFrame({"season": 1, "server": "S0", "player": "p", "deck": 1, "unit_id": list("abcde"), "size": 5})
    before, after = metrics.split_fractions(deck, split), metrics.split_fractions(deck, pooled)
    assert after[0] == pytest.approx(after[1]) and after[0] + after[1] == pytest.approx(before[0] + before[1])
    assert after[2:] == pytest.approx(before[2:])


def test_the_split_pools_a_pair_the_decks_cannot_tell_apart(monkeypatch):
    """x is weak and decked alone in season 1; from season 2 always with the strong y. The decks put the
    pair's strength on y; the split shares it once the pair has two seasons."""
    rng = np.random.default_rng(7)
    true = {"x": 0.8, "y": 2.0} | {f"f{i:02d}": np.exp(0.04 * i) for i in range(15)}
    rows = []
    for season in (1, 2, 3):
        for server in ("S0", "S1"):
            for rank in range(1, 31):
                fillers = list(rng.permutation([f"f{i:02d}" for i in range(15)]))
                pair = ["x", "y"] if season > 1 else ["x"]
                for number, deck in enumerate([pair + fillers[:5 - len(pair)], fillers[5:10], fillers[10:15]], start=1):
                    score = rng.uniform(1, 2) * 1e9 * np.prod([true[u] for u in deck])
                    rows += [{"season": season, "server": server, "player": f"p{rank}", "rank": rank, "deck": number,
                              "deck_score": score, "unit_id": u, "unit_cp": 1e5} for u in deck]
    entries = pd.DataFrame(rows)
    roster, seasons = _rows(entries)
    split = power.split_weights(entries, roster, seasons).set_index(["season", "unit_id"])["weight"]
    assert split[(2, "y")] > split[(2, "x")] + 0.3  # y's first season: not a pair yet
    assert split[(3, "x")] == pytest.approx(split[(3, "y")])
    monkeypatch.setattr(power, "together", lambda entries: pd.DataFrame(columns=["season", "unit_id", "group"]))
    raw = power.split_weights(entries, roster, seasons).set_index(["season", "unit_id"])["weight"]
    assert 2 * np.exp(split[(3, "x")]) == pytest.approx(np.exp(raw[(3, "x")]) + np.exp(raw[(3, "y")]))
    others = split.index.get_level_values("unit_id").str.startswith("f")
    assert split[others].tolist() == raw[others].tolist() and split.loc[[1, 2]].tolist() == raw.loc[[1, 2]].tolist()
