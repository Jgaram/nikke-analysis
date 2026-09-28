"""The whole thing: tables in, metrics out, charts on disk, tiers at a moment.

Uses the synthetic world so it needs no network and no committed ranking data.
"""

import pandas as pd
import pytest

from nikke_analysis import raidstats
from nikke_analysis.analyze import pipeline
from nikke_analysis.raidstats import QueryError, RaidBook
from nikke_analysis.tierlist import TierBook, render, render_unit
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
    assert len(result["written"]) == 14
    for name in result["written"]:
        path = tmp_path / f"{name}.png"
        assert path.is_file() and path.stat().st_size > 5_000, name
    chosen = charts.render_all(data_dir=directory, out_dir=tmp_path, themes=("light",), units=["Newcomer"])
    assert "tier-trajectories" in chosen["written"]


def test_tiers_now_show_last_live_and_next_season(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    view = book.at("2026-01-01")
    assert view.finished.number == world.live_season - 1
    assert view.upcoming is not None and view.upcoming.kind == "expected"
    text = render(view)
    assert "직전 시즌" in text and "종합 티어" in text


def test_tiers_of_the_past_use_only_what_was_known(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    view = book.at("2025-04-01")  # season 3 over, season 4 not started yet
    assert view.final_seasons == [1, 2, 3]
    assert world.newcomer not in set(view.overall["unit_id"])
    assert view.upcoming is not None and view.upcoming.number == 4


def test_the_season_in_progress_is_provisional(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    live_start = pd.Timestamp(world.seasons.set_index("season").loc[world.live_season, "start_at"])
    view = book.at((live_start + pd.Timedelta(days=4)).isoformat())
    assert view.current is not None and view.current.kind == "live"
    early = book.at((live_start + pd.Timedelta(hours=2)).isoformat())
    assert early.current is not None and early.current.kind == "expected"


def test_unit_history_reads_every_season_since_release(processed):
    directory, world, _ = processed
    book = TierBook.load(directory)
    history = book.unit("Newcomer")
    assert history.unit_id == world.newcomer
    assert list(history.rows["season"]) == list(range(world.newcomer_season, world.live_season + 1))
    assert "종합" in render_unit(history, book.config)
    with pytest.raises(LookupError):
        book.unit("Filler")  # matches many


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
    assert summary["rankers"] == 6 * 2 * 5
    usage = RaidBook.load(tmp_path).season(3, servers=["na"])
    assert usage.filter_servers == ("NA",) and usage.rankers == 5


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
    assert (narrow.rankers, narrow.decks, narrow.servers, narrow.filter_servers) == (5, 25, 1, ("S1",))
    assert (narrow.rows[raidstats.SPLIT].sum(axis=1) == narrow.rows["rankers"]).all()
    # recomputing the whole sample gives back the committed table
    committed = book.season(7).rows.set_index("unit_id").sort_index()
    recomputed = book.season(7, servers=["S1", "S2"]).rows.set_index("unit_id").sort_index()
    columns = ["rankers", "usage_rank", *raidstats.SPLIT]
    pd.testing.assert_frame_equal(committed[columns], recomputed[columns], check_dtype=False)
    assert (committed["lift"] - recomputed["lift"]).abs().max() < 1e-6
    with pytest.raises(QueryError, match="없는 서버"):
        book.season(7, servers=["XX"])


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
