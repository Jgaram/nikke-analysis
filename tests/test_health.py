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
    from nikke_analysis.collect import enikk, notices
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
    monkeypatch.setattr(enikk, "collect_seasons", lambda: {"refreshed": []})
    monkeypatch.setattr(enikk, "collect_characters", lambda: {"changed": False})
    monkeypatch.setattr(pipeline, "build_timeline", lambda: {"issues": {}})

    assert cli.main(["refresh"]) == 1
    assert "collector_failed" in capsys.readouterr().err

    monkeypatch.setattr(notices, "collect_official", lambda: {"written": 0})
    assert cli.main(["refresh"]) == 0
