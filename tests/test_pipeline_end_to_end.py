"""The whole thing: tables in, metrics out, charts on disk, tiers at a moment.

Uses the synthetic world so it needs no network and no committed ranking data.
"""

from pathlib import Path

import pandas as pd
import pytest

from nikke_analysis import raidstats
from nikke_analysis.analyze import pipeline, tiers
from nikke_analysis.raidstats import QueryError, RaidBook
from nikke_analysis.servers import ServerError, ServerFilter
from nikke_analysis.tierlist import TierBook, render, render_element, render_unit
from nikke_analysis.viz import charts
from tests.synthetic import make_world, write_processed


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("processed")
    world = make_world(seasons=8, rankers=15, fillers=24, seed=11)
    write_processed(world, directory)
    summary = pipeline.run(data_dir=directory)
    return directory, world, summary


def test_analyze_writes_every_metric_table(processed):
    directory, _, summary = processed
    for name in pipeline.OUTPUTS:
        path = directory / name
        assert path.is_file(), name
        assert not pd.read_csv(path).empty, name
    assert summary["final_seasons"] == 7 and summary["live_season"] == 8


def test_analysis_is_reproducible(processed):
    """Same inputs must give byte-identical outputs - no RNG, no clock."""
    directory, _, _ = processed
    pipeline.run(data_dir=directory)
    first = {name: (directory / name).read_bytes() for name in pipeline.OUTPUTS}
    pipeline.run(data_dir=directory)
    assert all((directory / name).read_bytes() == first[name] for name in pipeline.OUTPUTS)


def test_patch_impact_locates_releases_inside_the_window(processed):
    directory, world, _ = processed
    impact = pd.read_csv(directory / "metrics_patch_impact.csv")
    assert impact["total_variation"].between(0, 1).all()
    arrival = impact[impact["season_to"] == world.newcomer_season].iloc[0]
    assert arrival["units_released"] == 1


def test_charts_render_in_both_themes(processed, tmp_path):
    directory, world, _ = processed
    result = charts.render_all(data_dir=directory, out_dir=tmp_path)
    assert not result["skipped_no_data"], result
    assert len(result["written"]) == 24  # twelve charts, one per element among them, in two themes
    assert {f"element-tiers-{e.lower()}" for e in tiers.ELEMENTS} <= set(result["written"])
    for name in result["written"]:
        path = tmp_path / f"{name}.png"
        assert path.is_file() and path.stat().st_size > 5_000, name
    chosen = charts.render_all(data_dir=directory, out_dir=tmp_path, themes=("light",), units=["Newcomer"])
    assert "tier-trajectories" in chosen["written"]


def test_tiers_now_show_the_last_season_and_the_overall_table(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    view = book.at("2026-01-01")
    assert view.finished.number == world.live_season - 1
    text = render(view)
    assert "직전 시즌" in text and "종합 티어" in text and "다음" not in text
    # every unit once in the overall table, and once per element it counts as in the element tables
    assert view.overall["unit_id"].is_unique and set(view.elements["unit_id"]) == set(view.overall["unit_id"])


def test_an_element_table_lists_its_units_by_their_tier_in_it(processed):
    directory, world, _ = processed
    view = TierBook.load(directory).at("2026-01-01")
    fire = view.element("Fire")
    assert set(fire["unit_id"]) == set(world.roster.loc[world.roster["element"] == "Fire", "unit_id"]) & set(view.overall["unit_id"])
    assert fire["element_lift"].is_monotonic_decreasing
    text = render_element(view, "Fire")
    assert "작열 속성 티어" in text and "Fire Dealer(ko)" in text and "Water Dealer(ko)" not in text
    assert view.element_dict("Fire")["units"][0]["unit_id"] == fire["unit_id"].iloc[0]


def test_a_skill_element_lists_a_unit_under_both(tmp_path):
    """The roster's extra_elements (data/manual/extra_elements.csv) put a unit in two element tables."""
    world = make_world(seasons=8, rankers=10, fillers=20, seed=11)
    world.roster["extra_elements"] = world.roster["unit_id"].map({world.partner: "Wind"}).fillna("")
    write_processed(world, tmp_path)
    pipeline.run(data_dir=tmp_path)
    elements = pd.read_csv(tmp_path / "metrics_element_tiers.csv", dtype={"unit_id": str})
    overall = pd.read_csv(tmp_path / "metrics_overall_tiers.csv", dtype={"unit_id": str})
    assert overall["unit_id"].is_unique and len(elements) == len(overall) + 1
    partner = elements[elements["unit_id"] == world.partner].set_index("element")["source"].to_dict()
    assert partner == {"Water": "own", "Wind": "skill"}

    book = TierBook.load(tmp_path)
    view = book.at("2026-01-01")
    assert "Wind Partner(ko)" in render_element(view, "Wind") and "본래 수냉" in render_element(view, "Wind")
    assert world.partner in set(view.element("Water")["unit_id"])  # never fielded there: listed, not printed
    text = render_unit(book.unit("Wind Partner"), book.config)
    assert "스킬로 풍압 우월 코드" in text and "풍압 (스킬)" in text and "▶풍압" in text and "▶수냉" in text


def test_tiers_of_the_past_use_only_what_was_known(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    view = book.at("2025-04-01")  # season 3 over, season 4 not started yet
    assert view.final_seasons == [1, 2, 3]
    assert world.newcomer not in set(view.overall["unit_id"])
    assert view.current is None  # between seasons


def test_the_season_in_progress_is_provisional(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    live_start = pd.Timestamp(world.seasons.set_index("season").loc[world.live_season, "start_at"])
    view = book.at((live_start + pd.Timedelta(days=4)).isoformat())
    assert view.current is not None and view.current.kind == "live"
    early = book.at((live_start + pd.Timedelta(hours=2)).isoformat())
    assert early.current is not None and early.current.kind == "pending" and early.current.rows.empty
    assert "아직 수집분 없음" in render(early)


def test_the_live_season_counts_in_the_tiers_once_collected(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    live_start = pd.Timestamp(world.seasons.set_index("season").loc[world.live_season, "start_at"])
    view = book.at((live_start + pd.Timedelta(days=4)).isoformat())
    assert view.live_seasons == [world.live_season] and view.final_seasons[-1] == world.live_season - 1
    assert f"진행 중 시즌 {world.live_season}(잠정)" in render(view)
    weak = world.seasons.set_index("season").loc[world.live_season, "weak_element"]
    assert view.element_seasons(weak)[-1] == world.live_season
    assert f"{world.live_season}(진행 중)" in render_element(view, weak)
    assert view.to_dict()["live_seasons"] == [world.live_season]
    assert book.at((live_start + pd.Timedelta(hours=2)).isoformat()).live_seasons == []  # no snapshot yet


def test_unit_history_reads_every_season_since_release(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    history = book.unit("Newcomer")
    assert history.unit_id == world.newcomer
    assert list(history.rows["season"]) == list(range(world.newcomer_season, world.live_season + 1))
    text = render_unit(history, book.config)
    assert "종합 티어" in text and "속성 티어" in text and "기여도" in text and "lift" not in text
    # Electric, but no Electric-weak season since its release: no element tier yet
    assert [(e["element"], e["element_lift"]) for e in history.profile["elements"]] == [("Electric", None)]
    assert "미관측" in text
    with pytest.raises(LookupError):
        book.unit("Filler")  # matches many


def test_a_unit_shows_what_its_overall_is_made_of(processed):
    """The newcomer (Electric) has met Fire, Water and - in progress - Wind, never Electric: its Electric slot
    counts 0, the two others it has not met take the mean of those it has, and the overall is provisional."""
    directory, world, _ = processed
    book = TierBook.load(directory)
    history = book.unit("Newcomer")
    assert history.live_seasons == [world.live_season]
    slots = {s["element"]: s for s in history.profile["slots"]}
    assert (slots["Electric"]["seasons"], slots["Electric"]["lift"]) == (0, 0.0)
    met = [slots[e]["lift"] for e in ("Fire", "Water", "Wind")]
    assert slots["Iron"]["seasons"] == 0 and slots["Iron"]["lift"] == pytest.approx(sum(met) / 3)
    assert history.profile["overall"] == pytest.approx((sum(met) + slots["Iron"]["lift"]) / 5)
    text = render_unit(history, book.config)
    assert "잠정(자기 속성 시즌을 아직 못 겪음)" in text and "▶전격 (0.00)" in text
    assert "다른 속성은 겪은 다른 속성의 평균, 자기 속성은 0" in text
    assert f"진행 중 시즌 {world.live_season}도 지금까지 수집분으로 잠정 반영" in text


def test_analyze_refuses_without_ranking_data(tmp_path):
    pd.DataFrame([{"unit_id": "010", "name_en": "Rapi", "release_date": "2022-11-04"}]).to_csv(
        tmp_path / "roster.csv", index=False
    )
    with pytest.raises(RuntimeError, match="raid_entries"):
        pipeline.run(data_dir=tmp_path)


def test_the_na_server_is_a_server_not_a_missing_value(tmp_path):
    """pandas reads "NA" as missing unless told not to; the NA server's rankers must survive."""
    world = make_world(seasons=6, rankers=5, fillers=10, seed=3)
    world.entries["server"] = world.entries["server"].map({"S1": "NA", "S2": "KR"})
    write_processed(world, tmp_path)
    assert set(pipeline.load_inputs(tmp_path)["entries"]["server"]) == {"NA", "KR"}
    summary = pipeline.run(data_dir=tmp_path)
    assert summary["rankers"] == 6 * 2 * 5 and summary["servers"] == ["KR", "NA"]
    usage = RaidBook.load(tmp_path).season(3, servers=["na"])
    assert usage.server_filter.include == ("NA",) and usage.server_names == ("NA",) and usage.rankers == 5
    book = TierBook.load(tmp_path, servers=ServerFilter.of("북미"), cache_dir=tmp_path / "cache")
    assert book.sample.servers == ["NA"] and str(book.sample) == "NA × 상위 50위"


def test_raid_view_defaults_to_the_newest_season(processed):
    directory, world, _ = processed
    book = RaidBook.load(directory)
    number, unit = book.parse(None, None)
    assert (number, unit) == (world.live_season, None)
    usage = book.season(number)
    assert (usage.rankers, usage.decks, usage.servers) == (30, 150, 2)
    assert not usage.final
    ranks = list(usage.used["usage_rank"])
    assert ranks == sorted(ranks) and ranks[0] == 1
    text = raidstats.render_season(usage)
    assert "진행 중인 시즌" in text and "Newcomer(ko)" in text


def test_raid_view_takes_a_moment_and_a_unit_in_either_order(processed):
    directory, world, _ = processed
    book = RaidBook.load(directory)
    start = pd.Timestamp(world.seasons.set_index("season").loc[3, "start_at"])
    assert book.parse((start + pd.Timedelta(days=2)).date().isoformat(), None) == (3, None)
    assert book.parse("Newcomer", "7") == book.parse("7", "Newcomer") == (7, "Newcomer")
    assert book.parse("Newcomer", None) == (world.live_season, "Newcomer")

    usage = book.season(7)
    row = book.unit(usage, "Newcomer")
    assert row["unit_id"] == world.newcomer and row["rankers"] == 30
    assert sum(int(row[c]) for c in raidstats.SPLIT) == 30
    assert "평균 덱 순위" in raidstats.render_unit(usage, row)
    with pytest.raises(QueryError, match="출시 전"):
        book.unit(book.season(3), "Newcomer")


def test_raid_view_narrows_the_sample_from_raid_entries(processed):
    directory, _, _ = processed
    book = RaidBook.load(directory)
    narrow = book.season(7, servers=["s1"], top=5)
    assert (narrow.rankers, narrow.decks, narrow.servers, narrow.server_filter.include) == (5, 25, 1, ("S1",))
    assert (narrow.rows[raidstats.SPLIT].sum(axis=1) == narrow.rows["rankers"]).all()
    # recomputing the whole sample gives back the committed table
    committed = book.season(7).rows.set_index("unit_id").sort_index()
    recomputed = book.season(7, servers=["S1", "S2"]).rows.set_index("unit_id").sort_index()
    columns = ["rankers", "usage_rank", *raidstats.SPLIT]
    pd.testing.assert_frame_equal(committed[columns], recomputed[columns], check_dtype=False)
    assert (committed["lift"] - recomputed["lift"]).abs().max() < 1e-6
    with pytest.raises(QueryError, match="없는 서버"):
        book.season(7, servers=["XX"])


def test_raid_view_leaves_servers_out(processed):
    directory, _, _ = processed
    book = RaidBook.load(directory)
    whole = book.season(7)
    assert whole.server_names == ("S1", "S2") and "2개 서버" in raidstats.render_season(whole)
    without = book.season(7, exclude="s2")
    assert (without.rankers, without.server_names) == (15, ("S1",))
    assert "S2 제외 1개 서버" in raidstats.render_season(without)
    assert without.to_dict()["server_filter"] == {"include": [], "exclude": ["S2"]}
    same = book.season(7, servers="s1").rows.set_index("unit_id").sort_index()
    pd.testing.assert_frame_equal(without.rows.set_index("unit_id").sort_index(), same)
    with pytest.raises(QueryError, match="없는 서버: XX"):
        book.season(7, exclude="xx")
    with pytest.raises(QueryError, match="하나도 남지 않는다"):
        book.season(7, exclude="s1,s2")


def test_raid_view_lists_units_nobody_fielded_only_on_request(processed):
    directory, world, _ = processed
    book = RaidBook.load(directory)
    usage = book.season(7)
    # the dealers of the four elements the boss is not weak to sit the season out
    weak = world.seasons.set_index("season").loc[7, "weak_element"]
    benched = {unit for element, unit in world.element_dps.items() if element != weak}
    unused = set(usage.rows.loc[usage.rows["rankers"] == 0, "unit_id"])
    assert benched <= unused and not unused & set(usage.used["unit_id"])
    assert len(usage.to_dict(include_unused=True)["units"]) == len(usage.rows)
    assert len(usage.to_dict()["units"]) == len(usage.used)
    names = world.roster.set_index("unit_id")["name_ko"]
    assert not any(names[u] in raidstats.render_season(usage) for u in benched)
    assert all(names[u] in raidstats.render_season(usage, include_unused=True) for u in benched)


def test_raid_view_says_what_it_cannot_find(processed):
    directory, _, _ = processed
    book = RaidBook.load(directory)
    with pytest.raises(QueryError, match="랭킹이 없다"):
        book.season_of("99")
    with pytest.raises(QueryError, match="시즌 번호나 날짜가 아니다"):
        book.parse("Newcomer", "Core A")
    usage = book.season(7)
    with pytest.raises(LookupError):
        book.unit(usage, "Nobody")
    with pytest.raises(LookupError):
        book.unit(usage, "Filler")  # matches many


# --------------------------------------------------------------------------
# another server sample
# --------------------------------------------------------------------------

def test_the_season_table_names_its_servers(processed):
    directory, _, summary = processed
    seasons = pd.read_csv(directory / "metrics_seasons.csv")
    assert set(seasons["server_names"]) == {"S1;S2"} and (seasons["servers"] == 2).all()
    assert summary["servers"] == ["S1", "S2"] and summary["server_filter"] == {"include": [], "exclude": []}


def test_every_server_chosen_by_name_gives_back_the_committed_tables(processed, tmp_path):
    directory, _, _ = processed
    result = pipeline.run_servers(ServerFilter.of("s1,s2"), data_dir=directory, cache_dir=tmp_path)
    out = tmp_path / "S1+S2"
    assert result["out_dir"] == str(out) and not result["reused"]
    for name in pipeline.OUTPUTS:
        assert (out / name).read_bytes() == (directory / name).read_bytes(), name


def test_another_sample_goes_to_its_own_directory_and_is_reused(processed, tmp_path):
    directory, _, summary = processed
    committed = {name: (directory / name).read_bytes() for name in pipeline.OUTPUTS}
    chosen = ServerFilter.of(exclude="s2")
    first = pipeline.run_servers(chosen, data_dir=directory, cache_dir=tmp_path)
    assert not first["reused"] and first["servers"] == ["S1"] and first["rankers"] == summary["rankers"] // 2
    assert first["server_filter"] == {"include": [], "exclude": ["S2"]}
    assert set(pd.read_csv(tmp_path / "excl-S2" / "metrics_seasons.csv")["server_names"]) == {"S1"}
    assert {name: (directory / name).read_bytes() for name in pipeline.OUTPUTS} == committed

    again = pipeline.run_servers(chosen, data_dir=directory, cache_dir=tmp_path)
    assert again["reused"] and again["rankers"] == first["rankers"]
    other = pipeline.run_servers(chosen, data_dir=directory, cache_dir=tmp_path,
                                 config=tiers.TierConfig(half_life_days=30))
    assert not other["reused"]  # different parameters
    forced = pipeline.run_servers(chosen, data_dir=directory, cache_dir=tmp_path,
                                  config=tiers.TierConfig(half_life_days=30), reuse=False)
    assert not forced["reused"]


def test_changed_rankings_are_not_served_from_the_old_tables(tmp_path):
    world = make_world(seasons=6, rankers=5, fillers=10, seed=5)
    write_processed(world, tmp_path)
    pipeline.run(data_dir=tmp_path)
    chosen = ServerFilter.of(exclude="s1")
    assert not pipeline.run_servers(chosen, data_dir=tmp_path, cache_dir=tmp_path / "cache")["reused"]
    world.entries[world.entries["rank"] <= 3].to_csv(tmp_path / "raid_entries.csv", index=False)
    rerun = pipeline.run_servers(chosen, data_dir=tmp_path, cache_dir=tmp_path / "cache")
    assert not rerun["reused"] and rerun["rankers"] == 6 * 3  # six seasons, S2's ranks 1-3


def test_a_misspelt_server_stops_the_analysis(processed, tmp_path):
    directory, _, _ = processed
    with pytest.raises(ServerError, match="없는 서버: XX"):
        pipeline.run_servers(ServerFilter.of("xx"), data_dir=directory, cache_dir=tmp_path)
    with pytest.raises(ServerError):
        pipeline.run(data_dir=directory, out_dir=tmp_path, config=tiers.TierConfig(exclude_servers=("XX",)))


def test_tiers_on_another_sample_say_which(processed, tmp_path):
    directory, world, _ = processed
    whole = TierBook.load(directory)
    assert whole.sample.servers == ["S1", "S2"]
    assert "표본: 2개 서버(S1·S2) × 상위 50위" in render(whole.at("2026-01-01"))
    assert "표본" not in render_unit(whole.unit("Newcomer"), whole.config)

    book = TierBook.load(directory, servers=ServerFilter.of(exclude="s2"), cache_dir=tmp_path)
    assert book.sample.servers == ["S1"] and book.config.exclude_servers == ("S2",)
    view = book.at("2026-01-01")
    assert "표본: S2 제외 1개 서버(S1) × 상위 50위" in render(view)
    assert view.to_dict()["sample"] == {"servers": ["S1"], "include": [], "exclude": ["S2"], "top_n": 50}
    history = book.unit("Newcomer")
    assert list(history.rows["season"]) == list(range(world.newcomer_season, world.live_season + 1))
    assert "표본: S2 제외 1개 서버(S1)" in render_unit(history, book.config)


def test_charts_of_another_sample_say_so_and_leave_no_trace(processed, tmp_path):
    directory, _, _ = processed
    tables = pipeline.run_servers(ServerFilter.of(exclude="s2"), data_dir=directory, cache_dir=tmp_path / "t")
    result = charts.render_all(data_dir=Path(tables["out_dir"]), out_dir=tmp_path / "c",
                               themes=("light",), sample="S2 제외 전 서버")
    assert len(result["written"]) == 12
    assert charts._sample_caption == "" and charts._extras == {}
