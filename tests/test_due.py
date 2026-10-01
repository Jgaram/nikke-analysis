from datetime import datetime

from nikke_analysis.due import decide
from nikke_analysis.util.kdate import KST

SEASON = {"season": "41", "start_at": "2026-09-24T12:00:00+09:00", "end_at": "2026-10-01T04:59:59+09:00"}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(KST)


def test_a_season_being_played_is_read_once_a_day():
    stored = {41: {"lastupdated": "2026-09-28T12:45:00.000Z", "fetched_at": "2026-09-28T13:16:43+00:00"}}
    listed = {41: "2026-09-29T01:00:00.000Z"}
    assert not decide(at("2026-09-29T12:00:00+09:00"), [SEASON], stored, listed).due  # read 13 h ago
    assert decide(at("2026-09-29T19:00:00+09:00"), [SEASON], stored, listed).due  # 21 h ago
    # nothing newer on enikk: nothing to read, however long ago
    assert not decide(at("2026-09-30T18:00:00+09:00"), [SEASON], stored, {41: "2026-09-28T12:45:00.000Z"}).due


def test_an_ended_season_is_asked_about_until_its_final_ranking_is_in():
    before_end = {41: {"lastupdated": "2026-09-28T12:45:00.000Z", "fetched_at": "2026-09-28T13:16:43+00:00"}}
    # enikk has not moved since: wait
    assert not decide(at("2026-10-01T06:23:00+09:00"), [SEASON], before_end, {41: "2026-09-28T12:45:00.000Z"}).due
    # enikk posted after the end: due at once, even an hour after the last read
    answer = decide(at("2026-10-01T06:23:00+09:00"), [SEASON], before_end, {41: "2026-09-30T21:01:00.000Z"})
    assert answer.due and "종료" in answer.reasons[0]
    # the final ranking is on disk: done, whatever enikk does later
    final = {41: {"lastupdated": "2026-09-30T21:01:00.000Z", "fetched_at": "2026-09-30T21:30:00+00:00"}}
    assert not decide(at("2026-10-01T09:23:00+09:00"), [SEASON], final, {41: "2026-10-01T03:00:00.000Z"}).due
    # a week on, the hourly check gives up (nikke check reports it)
    assert not decide(at("2026-10-08T06:00:00+09:00"), [SEASON], before_end, {41: "2026-10-05T00:00:00.000Z"}).due


def test_a_season_not_started_or_not_listed_is_not_due():
    upcoming = {"season": "42", "start_at": "2026-10-22T12:00:00+09:00", "end_at": "2026-10-29T04:59:59+09:00"}
    assert not decide(at("2026-10-15T12:00:00+09:00"), [upcoming], {}, {42: ""}).due
    assert decide(at("2026-10-23T12:00:00+09:00"), [upcoming], {}, {42: "2026-10-23T02:00:00.000Z"}).due
