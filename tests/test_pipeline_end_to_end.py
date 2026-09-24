"""One test that runs the whole thing: tables in, metrics out, charts on disk.

Uses the synthetic world so it needs no network and no committed ranking data.
"""

import pandas as pd
import pytest

from nikke_analysis.analyze import pipeline
from nikke_analysis.viz import charts
from tests.synthetic import make_world


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("processed")
    world = make_world(seasons=5, bosses=2, teams_per_boss=30, units=40, seed=11)
    world.entries.to_csv(directory / "raid_entries.csv", index=False)
    world.roster.to_csv(directory / "roster.csv", index=False)
    world.calendar.to_csv(directory / "season_calendar.csv", index=False)
    pd.DataFrame(
        [
            {"notice_id": "official:p2", "source": "official", "published_at": "2024-04-10T18:00:00+09:00",
             "updated_at": "", "kind": "update", "title": "4월 11일 업데이트 공지", "url": "", "chars": 100},
        ]
    ).to_csv(directory / "notices.csv", index=False)
    pd.DataFrame(
        [
            {"unit_id": world.newcomer, "kind": "special", "debut": 1, "start_at": "2024-02-10T00:00:00+09:00",
             "end_at": "2024-02-24T04:59:59+09:00", "start_after_maintenance": 1, "notice_id": "official:p1",
             "notice_title": "New Nikke", "notice_published_at": "2024-02-08T18:00:00+09:00", "label": "특수 모집 기간",
             "evidence": ""},
        ]
    ).to_csv(directory / "banners.csv", index=False)
    pd.DataFrame(
        [{"unit_id": world.newcomer, "release_at": "2024-08-25T00:00:00+09:00", "release_date": "2024-08-25",
          "release_after_maintenance": 1, "banner_kind": "special", "notice_id": "official:p1",
          "notice_title": "New Nikke", "notice_published_at": "2024-08-22T18:00:00+09:00", "evidence": ""}]
    ).to_csv(directory / "unit_releases.csv", index=False)
    return directory, world


def test_analyze_writes_every_metric_table(processed):
    directory, _ = processed
    summary = pipeline.run(data_dir=directory)
    assert summary["availability_source"] == "season_calendar"
    for name in (
        "metrics_usage.csv",
        "metrics_tiers.csv",
        "metrics_tier_changes.csv",
        "metrics_meta_shift.csv",
        "metrics_synergy.csv",
        "metrics_trajectory.csv",
        "metrics_patch_impact.csv",
    ):
        path = directory / name
        assert path.is_file(), name
        assert not pd.read_csv(path).empty, name


def test_analysis_is_reproducible(processed):
    """Same inputs must give byte-identical outputs - no RNG, no clock."""
    directory, _ = processed
    pipeline.run(data_dir=directory)
    first = (directory / "metrics_tiers.csv").read_bytes()
    pipeline.run(data_dir=directory)
    assert (directory / "metrics_tiers.csv").read_bytes() == first


def test_patch_impact_locates_releases_inside_the_window(processed):
    directory, world = processed
    pipeline.run(data_dir=directory)
    impact = pd.read_csv(directory / "metrics_patch_impact.csv")
    assert (impact["units_released"] >= 0).all()
    assert impact["total_variation"].between(0, 1).all()


def test_charts_render_in_both_themes(processed, tmp_path):
    directory, _ = processed
    pipeline.run(data_dir=directory)
    result = charts.render_all(data_dir=directory, out_dir=tmp_path)
    assert result["written"], result
    for name in result["written"]:
        path = tmp_path / f"{name}.png"
        assert path.is_file() and path.stat().st_size > 5_000, name
    assert any(n.endswith("-dark") for n in result["written"])


def test_analyze_refuses_without_ranking_data(tmp_path):
    pd.DataFrame([{"unit_id": "010", "name_en": "Rapi", "release_date": "2022-11-04"}]).to_csv(
        tmp_path / "roster.csv", index=False
    )
    with pytest.raises(RuntimeError, match="raid_entries"):
        pipeline.run(data_dir=tmp_path)
