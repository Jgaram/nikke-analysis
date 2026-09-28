"""The whole thing: tables in, metrics out, charts on disk, tiers at a moment.

Uses the synthetic world so it needs no network and no committed ranking data.
"""

import pandas as pd
import pytest

from nikke_analysis.analyze import pipeline
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
