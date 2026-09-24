import csv
from datetime import datetime

import pytest

from nikke_analysis.timeline import Timeline, render, render_seasons, resolve_moment
from nikke_analysis.util.kdate import KST


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def unit(unit_id, name, element, release_date, source, release_at="", confidence="high"):
    return {
        "unit_id": unit_id, "name_en": "", "name_ko": name, "name_ja": "", "rarity": "SSR", "burst": "III",
        "element": element, "manufacturer": "", "unit_class": "Attacker", "weapon": "", "squad": "",
        "release_date": release_date, "release_at": release_at, "release_date_source": source,
        "release_date_confidence": confidence,
    }


def season(number, boss, element, weak, disrupted=0, reset=0, checks=""):
    return {
        "season": number, "boss_en": boss, "boss_ko": "", "element": element, "weak_element": weak,
        "scheduled_start": "", "scheduled_end": "", "start_at": "", "end_at": "", "periods": 0,
        "disrupted": disrupted, "record_reset": reset, "numbered_by": "notice", "enikk_first_seen": "",
        "enikk_last_seen": "", "enikk_collections": 0, "units_available": "", "new_units": "", "checks": checks,
        "notice_ids": "",
    }


def period(number, index, start, end, reason="scheduled"):
    return {"season": number, "period": index, "start_at": start, "end_at": end,
            "start_after_maintenance": 0, "end_reason": reason}


@pytest.fixture()
def timeline(tmp_path):
    write(tmp_path / "roster.csv", [
        unit("010", "라피", "Fire", "2022-11-04", "launch", confidence="medium"),
        unit("511", "신데렐라", "Electric", "2024-10-31", "patchnote", "2024-10-31T00:00:00+09:00"),
        unit("514", "그레이브", "Water", "2024-11-07", "patchnote", "2024-11-07T05:00:00+09:00"),
        unit("193", "네베", "Water", "2022-12-08", "datafile", confidence="low"),
    ])
    write(tmp_path / "unit_releases.csv", [
        {"unit_id": "514", "release_at": "2024-11-07T05:00:00+09:00", "release_date": "2024-11-07",
         "release_after_maintenance": 0, "banner_kind": "special", "notice_id": "n",
         "notice_title": "10월 31일 업데이트 공지", "notice_published_at": "2024-10-30T07:00:00+09:00", "evidence": ""},
    ])
    write(tmp_path / "banners.csv", [
        {"unit_id": "511", "kind": "special", "debut": 1, "start_at": "2024-10-31T00:00:00+09:00",
         "end_at": "2024-11-21T04:59:59+09:00", "start_after_maintenance": 1, "notice_id": "n",
         "notice_title": "t", "notice_published_at": "2024-10-30T07:00:00+09:00", "label": "특수 모집 기간", "evidence": ""},
    ])
    write(tmp_path / "soloraid_seasons.csv", [
        season(18, "Land Eater", "Fire", "Water"),
        season(19, "Behemoth", "Water", "Electric", disrupted=1, reset=1),
        season(20, "White Ice Dragon", "Water", "Electric"),
        season(21, "Modernia", "Wind", "Fire", checks="no_notice"),
    ])
    write(tmp_path / "soloraid_periods.csv", [
        period(18, 1, "2024-10-03T12:00:00+09:00", "2024-10-10T04:59:59+09:00"),
        period(19, 1, "2024-10-31T12:00:00+09:00", "2024-11-01T22:00:00+09:00", "suspended"),
        period(19, 2, "2024-11-08T12:00:00+09:00", "2024-11-12T18:00:00+09:00", "suspended"),
        period(19, 3, "2024-11-13T12:00:00+09:00", "2024-11-17T05:00:00+09:00", "extended"),
        period(20, 1, "2024-12-12T12:00:00+09:00", "2024-12-19T04:59:59+09:00"),
    ])
    write(tmp_path / "notices.csv", [
        {"notice_id": "n", "source": "official", "published_at": "2024-10-30T07:00:00+09:00", "updated_at": "",
         "kind": "update", "title": "10월 31일 업데이트 공지", "url": "u", "chars": 1},
    ])
    return Timeline.load(tmp_path)


def test_the_second_anniversary(timeline):
    view = timeline.at("2주년")
    assert view.moment == datetime(2024, 11, 4, 12, 0, tzinfo=KST)
    assert view.season.number == 19 and view.season.status_at(view.moment) == "suspended"
    assert view.previous_season.number == 18
    assert view.next_season.number == 20
    assert [u.unit_id for u in view.units] == ["010", "193", "511"]
    # Announced on 10/30 for 11/07: known then, not yet playable.
    assert [u.unit_id for u in view.announced_units] == ["514"]
    assert [b.unit_id for b in view.banners] == ["511"]
    assert view.latest_update["title"] == "10월 31일 업데이트 공지"


def test_season_status_follows_the_periods(timeline):
    behemoth = timeline.season(19)
    assert behemoth.status_at(resolve_moment("2024-10-30")) == "upcoming"
    assert behemoth.status_at(resolve_moment("2024-11-01T21:00")) == "open"
    assert behemoth.status_at(resolve_moment("2024-11-12T20:00")) == "suspended"
    assert behemoth.status_at(resolve_moment("2024-11-16")) == "open"
    assert behemoth.status_at(resolve_moment("2024-11-18")) == "closed"
    assert timeline.season(21).status_at(resolve_moment("2024-11-18")) == "unscheduled"


def test_between_seasons_there_is_no_current_one(timeline):
    view = timeline.at("2024-11-25")
    assert view.season is None
    assert (view.previous_season.number, view.next_season.number) == (19, 20)
    assert len(view.units) == 4


def test_rendering_names_the_state_in_korean(timeline):
    text = render(timeline.at("2주년"), list_units=True)
    assert "시즌 19" in text and "일시 중단 중" in text
    assert "공지됐지만 미출시  그레이브" in text
    assert "출시일 신뢰도 낮음 1명: 네베" in text
    listing = render_seasons(timeline)
    assert "3구간" in listing and "기록 초기화" in listing and "일정 미공지" in listing


def test_json_view_is_complete(timeline):
    payload = timeline.at("2주년").to_dict()
    assert payload["soloraid"]["current"]["status"] == "suspended"
    assert len(payload["soloraid"]["current"]["periods"]) == 3
    assert payload["units"]["count"] == 3
