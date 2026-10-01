import csv
from datetime import datetime

import pytest

from nikke_analysis import cli, health
from nikke_analysis.util.kdate import KST


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def season(number, start, checks="", enikk_first=""):
    return {"season": number, "start_at": start, "checks": checks, "enikk_first_seen": enikk_first}


def roster_row(unit_id, name, source, release="2026-09-17", element="Fire"):
    return {"unit_id": unit_id, "name_ko": name, "name_en": "", "release_date": release,
            "release_date_source": source, "element": element, "unit_class": "Attacker"}


@pytest.fixture()
def processed(tmp_path):
    directory = tmp_path / "processed"
    directory.mkdir()
    write(directory / "soloraid_seasons.csv", [
        season(40, "2026-08-20T12:00:00+09:00", "enikk_after_periods"),
        season(41, "2026-09-24T12:00:00+09:00"),
        season(42, "", "no_notice"),
    ])
    write(directory / "roster.csv", [
        roster_row("404", "길티 : 마이티 바니", "patchnote"),
        roster_row("193", "네베", "datafile", "2022-12-08"),
        roster_row("999", "미공개", "", "", element=""),
    ])
    write(directory / "release_unresolved.csv", [
        {"notice_id": "n", "notice_title": "10월 1일 업데이트 공지", "name": "미지의 니케", "line": "1.1 SSR 니케 [미지의 니케]"},
    ])
    write(directory / "notices.csv", [
        {"notice_id": "n", "source": "official", "published_at": "2026-09-14T18:00:00+09:00", "kind": "update", "title": "t"},
    ])
    return directory


def test_known_gaps_are_warnings_not_errors(processed):
    issues = health.data_issues(processed)
    codes = {(i.level, i.code) for i in issues}
    assert ("warning", "enikk_disagrees") in codes
    assert ("warning", "unresolved_name") in codes
    assert ("warning", "release_from_datafile") in codes
    assert ("info", "unit_without_date") in codes
    # 42 is known to enikk but not played yet: not a problem.
    assert not health.has_errors(issues)


def test_a_season_played_without_any_notice_is_an_error(processed):
    write(processed / "soloraid_seasons.csv", [season(42, "", "no_notice", enikk_first="2026-10-23T10:00:00+09:00")])
    issues = health.data_issues(processed, problems=["season numbers claimed twice: [42]"])
    assert {i.code for i in issues if i.level == "error"} == {"season_played_without_notice", "season_numbering"}


def test_silence_longer_than_the_game_ever_goes_quiet_is_an_error(processed):
    fresh = health.run_issues(processed, datetime(2026, 9, 24, 12, tzinfo=KST))
    assert fresh == []
    stale = health.run_issues(processed, datetime(2026, 12, 31, tzinfo=KST), {"collect.notices.official": "HTTP 404"})
    assert {i.code for i in stale} == {"collector_failed", "notices_stale", "soloraid_stale"}


def test_issues_round_trip_and_render(processed):
    issues = health.data_issues(processed)
    health.write(processed, issues)
    assert health.read(processed) == issues
    assert "정상 (알려진 공백만 있음)" in health.render(issues)


def test_refresh_ends_red_when_a_source_could_not_be_collected(tmp_path, monkeypatch, capsys):
    """An unattended run must not look fresh when it is not."""
    from nikke_analysis.build import pipeline
    from nikke_analysis.collect import blablalink, enikk, notices
    from nikke_analysis.collect import roster as roster_collector

    monkeypatch.setenv("NIKKE_DATA_ROOT", str(tmp_path))
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "notices.csv", [
        {"notice_id": "n", "source": "official", "published_at": datetime.now(KST).isoformat(), "kind": "update", "title": "t"},
    ])
    write(processed / "soloraid_seasons.csv", [season(41, datetime.now(KST).isoformat())])
    health.write(processed, [])

    def broken():
        raise RuntimeError("POST .../GetContentByLabel -> HTTP 404")

    monkeypatch.setattr(roster_collector, "collect_gamefiles", lambda: "ok")
    monkeypatch.setattr(roster_collector, "collect_nikkeutils", lambda: "ok")
    monkeypatch.setattr(notices, "collect_official", broken)
    monkeypatch.setattr(notices, "collect_naver", lambda: {"written": 0})
    monkeypatch.setattr(notices, "collect_naver_raid", lambda: {"written": 0})
    monkeypatch.setattr(enikk, "collect_seasons", lambda: {"refreshed": []})
    monkeypatch.setattr(enikk, "collect_characters", lambda: {"changed": False})
    monkeypatch.setattr(enikk, "collect_rankings", lambda **kwargs: {"fetched": []})
    monkeypatch.setattr(blablalink, "collect_icons", lambda: {"fetched": []})
    monkeypatch.setattr(pipeline, "build_timeline", lambda: {"issues": {}})

    assert cli.main(["refresh"]) == 1
    assert "collector_failed" in capsys.readouterr().err

    monkeypatch.setattr(notices, "collect_official", lambda: {"written": 0})
    assert cli.main(["refresh"]) == 0


def test_a_skill_element_for_a_unit_the_roster_lacks_is_a_warning(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "roster.csv", [roster_row("016", "라피 : 레드 후드", "patchnote")])
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "extra_elements.csv").write_text("unit_id,element,reason\n016,Iron,스킬\n061,Water,오타\n",
                                               encoding="utf-8")
    issues = health.manual_issues(processed, manual)
    assert [(i.level, i.code, i.subject) for i in issues] == [("warning", "extra_element_unknown_unit", "061")]
    assert not health.has_errors(issues)


def test_a_treasure_row_is_checked_too_and_so_is_its_since(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "roster.csv", [roster_row("140", "슈가", "launch")])
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "extra_elements.csv").write_text(
        "unit_id,element,since,reason\n140,Water,treasure,애장품\n041,Water,treasure,오타\n140,Wind,언젠가,오타\n",
        encoding="utf-8")
    issues = health.manual_issues(processed, manual)
    assert [(i.code, i.subject) for i in issues] == [("extra_element_unknown_unit", "041"),
                                                     ("extra_element_unknown_since", "140")]


def test_a_ranking_pin_to_a_unit_the_roster_lacks_is_a_warning(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "roster.csv", [roster_row("831", "레이", "patchnote")])
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "ranking_names.csv").write_text("name,unit_id,reason\nRei,831,레이\nSakura,999,오타\n",
                                              encoding="utf-8")
    issues = health.manual_issues(processed, manual)
    assert [(i.code, i.subject) for i in issues] == [("ranking_name_unknown_unit", "999")]


def test_the_committed_skill_elements_name_units_of_the_committed_roster():
    from nikke_analysis import paths
    from nikke_analysis.build.roster import load_extra_elements

    assert load_extra_elements() and health.manual_issues(paths.processed_dir()) == []


def test_ranking_findings_name_unmatched_names_and_missing_seasons(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "raid_unresolved_names.csv", [{"name": "Rei", "occurrences": 7, "seasons": "19;20", "candidates": "392;831"}])
    write(processed / "metrics_seasons.csv", [{"season": "40", "rankers": "300"}])
    missing = {**season(39, "2026-07-16T12:00:00+09:00"), "end_at": "2026-07-23T04:59:59+09:00",
               "enikk_first_seen": "2026-07-17T00:00:00+09:00"}
    played = {**season(40, "2026-08-20T12:00:00+09:00"), "end_at": "2026-08-27T04:59:59+09:00",
              "enikk_first_seen": "2026-08-21T00:00:00+09:00"}
    just_ended = {**season(41, "2026-09-17T12:00:00+09:00"), "end_at": "2026-09-24T04:59:59+09:00",
                  "enikk_first_seen": "2026-09-18T00:00:00+09:00"}
    untracked = {**season(38, "2026-06-11T12:00:00+09:00"), "end_at": "2026-06-18T04:59:59+09:00"}
    write(processed / "soloraid_seasons.csv", [missing, played, just_ended, untracked])
    issues = health.ranking_issues(processed, datetime(2026, 9, 28, tzinfo=KST))
    levels = {(i.code, i.subject): i.level for i in issues}
    assert levels == {
        ("ranking_name_unresolved", "Rei"): "warning",
        # a week past its end with nothing: the collection has stopped
        ("ranking_missing", "시즌 39"): "error",
        # season 41 ended four days ago - enikk may still be collecting; 38 enikk never tracked
    }
    assert health.has_errors(issues)


def test_missing_rankings_are_reported_without_any_metric_table(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "soloraid_seasons.csv", [
        {**season(39, "2026-07-16T12:00:00+09:00"), "end_at": "2026-07-23T04:59:59+09:00",
         "enikk_first_seen": "2026-07-17T00:00:00+09:00"},
    ])
    issues = health.ranking_issues(processed, datetime(2026, 9, 28, tzinfo=KST))
    assert [(i.level, i.code) for i in issues] == [("error", "ranking_missing")]


def test_a_season_ranked_only_before_its_end_is_reported_after_a_week(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    write(processed / "metrics_seasons.csv", [
        {"season": "40", "rankers": "300", "end_at": "2026-08-27T04:59:59+09:00", "final": "False",
         "collected_on": "2026-08-25T09:00:00+09:00"},
        {"season": "41", "rankers": "300", "end_at": "2026-09-24T04:59:59+09:00", "final": "False",
         "collected_on": "2026-09-22T09:00:00+09:00"},
        {"season": "39", "rankers": "300", "end_at": "2026-07-23T04:59:59+09:00", "final": "True"},
    ])
    issues = health.ranking_issues(processed, datetime(2026, 9, 28, tzinfo=KST))
    # 40 is a month past its end; 41 is four days past, still inside the week the hourly check asks
    assert [(i.level, i.code, i.subject) for i in issues] == [("error", "ranking_not_final", "시즌 40")]
