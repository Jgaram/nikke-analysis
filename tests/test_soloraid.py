"""The Solo Raid calendar, checked against the disrupted seasons as they really happened.

Every notice below is trimmed from the real one; the expected periods are the
ones the game actually ran.
"""

from datetime import datetime

from nikke_analysis.build import soloraid
from nikke_analysis.build.enikk_meta import EnikkSeason
from nikke_analysis.build.notices import Notice
from nikke_analysis.util.kdate import KST


def at(*parts):
    return datetime(*parts, tzinfo=KST)


def official(title, published, text):
    return Notice(f"official:{title}", "official", published, None, title, "", "\n".join(
        line.strip() for line in text.strip().splitlines()
    ))


def lounge(title, published, text, updated=None):
    return Notice(f"naver:{title}", "naver", published, updated, title, "", "\n".join(
        line.strip() for line in text.strip().splitlines()
    ))


def periods(notices, enikk=None):
    events = soloraid.extract_all(notices)
    seasons = soloraid.group_seasons(events)
    for season in seasons:
        season.periods = soloraid.replay(season.events)
    soloraid.number_seasons(seasons, enikk or {})
    return {
        s.number: [(p.start.iso()[:16], p.end.iso()[:16] if p.end else None, p.end_reason) for p in s.periods]
        for s in seasons
    }


def update(title, published, sentence, window, *, element=""):
    return official(title, published, f"""
        업데이트 주요 내용:
        8. 솔로 레이드
        {sentence}
        *오픈 시간: {window}
        {element}
        9. 협동 작전
        *이벤트 진행 기간: 2026년 9월 25일 12:00:00 ~ 2026년 9월 27일 23:59:59 (UTC+9)
    """)


def test_a_plain_season_with_element():
    notice = update(
        "9월 17일 업데이트 공지", at(2026, 9, 14, 18),
        "솔로 레이드 시즌 41이 2026년 9월 24일 12:00:00에 오픈됩니다.",
        "2026년 9월 24일 12:00:00 ~ 2026년 10월 1일 4:59:59 (UTC+9)",
        element="*보스 속성: 작열 코드 (약점 : 수냉 코드)",
    )
    [opened] = soloraid.extract_events(notice)
    assert (opened.kind, opened.season, opened.element, opened.weak_element) == ("open", 41, "Fire", "Water")
    assert periods([notice]) == {41: [("2026-09-24T12:00", "2026-10-01T04:59", "scheduled")]}


def test_season_8_postponed_before_it_opened():
    notices = [
        update("12월 7일 업데이트 공지", at(2023, 12, 4, 16, 42),
               "솔로 레이드는 12월 8일 12:00:00(UTC+9)에 오픈됩니다.",
               "2023년 12월 8일 12:00:00 ~ 2023년 12월 15일 4:59:59 (UTC+9)"),
        lounge("솔로 레이드 연기 안내", at(2023, 12, 8, 0, 12), """
            현재 일부 상황에서 캐릭터 대미지가 비정상적으로 작동되는 현상이 확인되어
            12월 8일(금) 오픈 예정이었던 솔로 레이드가 연기될 예정입니다.
        """),
        update("12월 13일 업데이트 공지", at(2023, 12, 12, 16, 30),
               "솔로 레이드는 12월 14일 12:00:00(UTC+9)에 오픈됩니다.",
               "2023년 12월 14일 12:00:00 ~ 2023년 12월 21일 4:59:59 (UTC+9)"),
    ]
    enikk = {8: EnikkSeason(8, observed_first="2023-12-15T09:00:00+09:00", observed_last="2023-12-21T09:55:00+09:00")}
    assert periods(notices, enikk) == {8: [("2023-12-14T12:00", "2023-12-21T04:59", "scheduled")]}


SEASON_19 = [
    update("10월 31일 업데이트 공지", at(2024, 10, 30, 7),
           "솔로 레이드가 2024년 10월 31일 서버 점검 종료 이후에 오픈됩니다.",
           "2024년 10월 31일 12:00:00 ~ 2024년 11월 7일 4:59:59 (UTC+9)"),
    lounge("솔로 레이드 일시 중단 안내(11/1 내용 추가)", at(2024, 11, 1, 22, 8), """
        솔로 레이드 중단으로 인한 보상을 게임 내 메일함을 통해 지급해 드렸습니다.
        📢 솔로 레이드 일시 중단 안내
        ✔️ 일시
        - 11월 1일(금) 22:00
        일부 이슈로 인하여 솔로 레이드 시즌 19가
        11월 1일(금) 22:00부터 일시적으로 중단될 예정입니다.
        ✔️ 일시
        - 11월 1일(금) 22:00 ~  추후 안내
    """),
    update("11월 7일 업데이트 공지", at(2024, 11, 7, 4, 2),
           "솔로 레이드가 2024년 11월 8일 12:00:00 (UTC+9)에 오픈됩니다.",
           "2024년 11월 8일 12:00:00 ~ 2024년 11월 15일 4:59:59 (UTC+9)"),
    lounge("솔로 레이드 시즌 19 일시 중단 및 챌린지 모드 기록 초기화 사전 안내", at(2024, 11, 12, 16, 38), """
        일부 이슈로 인해 솔로 레이드 시즌 19가
        11월 12일(화) 18:00에 일시 중단됩니다.
        솔로 레이드 챌린지 모드의 기록이 초기화되며
        ✔️ 일시
        - 11월 12일(화)
        ✔️ 솔로 레이드 시즌 19 일시 중단 기간
        11/12일(화) 18:00 ~ 11/13(수) 12:00
        ✔️ 솔로 레이드 시즌 19 진행 기간 연장
        - 11/17(일) 5:00까지
    """),
]


def test_season_19_suspended_twice_and_extended():
    enikk = {19: EnikkSeason(19, observed_first="2024-11-14T08:12:00+09:00", observed_last="2024-11-17T07:00:00+09:00")}
    assert periods(SEASON_19, enikk) == {
        19: [
            ("2024-10-31T12:00", "2024-11-01T22:00", "suspended"),
            ("2024-11-08T12:00", "2024-11-12T18:00", "suspended"),
            ("2024-11-13T12:00", "2024-11-17T05:00", "extended"),
        ]
    }
    events = soloraid.extract_all(SEASON_19)
    assert any(e.kind == "reset" for e in events)
    # The date-only "일시 - 11월 12일(화)" is not a second, midnight suspension.
    assert not any(e.kind == "suspend" and e.start.iso().endswith("T00:00:00+09:00") for e in events)


def test_season_26_reopened_suspended_again_then_rescheduled():
    notices = [
        update("6월 12일 업데이트 공지", at(2025, 6, 9, 18),
               "솔로 레이드가 2025년 6월 19일 12:00:00에 오픈됩니다.",
               "2025년 6월 19일 12:00:00 ~ 2025년 6월 26일 4:59:59 (UTC+9)"),
        # Posted as a suspension notice, edited into a reopening notice on 6/24.
        lounge("솔로 레이드 시즌 26 재오픈 안내(6/24 내용 추가)", at(2025, 6, 19, 21, 18), """
            【솔로 레이드 재오픈 안내】
            솔로 레이드 시즌 26의 일정이 변경되어 재오픈되었습니다.
            ✅ 진행 기간
            - 6/24(화) 점검 완료 후 ~ 7/1(화) 4:59
            📢 솔로 레이드 시즌 26 일시 중단 보상 안내
            ✔️ 일시
            - 6월 20일(금)
            일부 이슈로 인하여 솔로 레이드 시즌 26이
            6월 20일(금) 00:00부터 일시적으로 중단될 예정입니다.
        """, updated=at(2025, 6, 24, 16, 56)),
        lounge("솔로 레이드 시즌 26 일시 중단 안내(6/26 내용 추가)", at(2025, 6, 25, 19, 2), """
            ✔️ 중단 일시
            - 6월 26일(목) 00:00 ~ 추후 안내
        """),
        official("7월 1일 업데이트 공지", at(2025, 7, 1, 13, 25), """
            3. 솔로 레이드 시즌26의 진행 기간이 아래와 같이 변경됩니다.
            └ 2025년 7월 3일 서버 점검 종료 이후 ~ 2025년 7월 10일 4:59:59 (UTC+9)
        """),
    ]
    assert periods(notices) == {
        26: [
            ("2025-06-19T12:00", "2025-06-20T00:00", "suspended"),
            ("2025-06-24T00:00", "2025-06-26T00:00", "suspended"),
            ("2025-07-03T00:00", "2025-07-10T04:59", "scheduled"),
        ]
    }


def test_season_28_suspended_for_hours_and_extended():
    notices = [
        update("8월 7일 업데이트 공지", at(2025, 8, 4, 17, 57),
               "솔로 레이드 시즌 28이 2025년 8월 21일 12:00:00에 오픈됩니다.",
               "2025년 8월 21일 12:00:00 ~ 2025년 8월 28일 4:59:59 (UTC+9)"),
        lounge("솔로 레이드 시즌 28 일시 중단 및 챌린지 모드 기록 초기화 사전 안내", at(2025, 8, 26, 1, 7), """
            ✔️ 솔로 레이드 시즌 28 일시 중단 기간
            - 8/26일(화) 17:00 ~ 21:00
            ✔️ 솔로 레이드 시즌 28 연장 기간
            - 8/26(화) 21:00 ~ 9/1(월) 4:59
        """),
    ]
    assert periods(notices) == {
        28: [
            ("2025-08-21T12:00", "2025-08-26T17:00", "suspended"),
            ("2025-08-26T21:00", "2025-09-01T04:59", "extended"),
        ]
    }


def test_season_38_reopen_and_season_39_in_one_notice():
    notices = [
        update("6월 11일 업데이트 공지", at(2026, 6, 8, 18, 56),
               "솔로 레이드 시즌 38이 2026년 6월 18일 12:00:00에 오픈됩니다.",
               "2026년 6월 18일 12:00:00 ~ 2026년 6월 25일 4:59:59 (UTC+9)"),
        lounge("솔로 레이드 중단 및 분배 대미지 관련 이슈 안내", at(2026, 6, 23, 0, 47), """
            솔로 레이드 - 애니힐리오를 6월 23일(화) 4:59:59에 중단할 예정입니다.
            ✔️ 중단 일시
            - 6/23(화) 4:59:59
        """),
        official("7월 2일 업데이트 공지", at(2026, 6, 29, 19, 15), """
            10. 솔로 레이드 재오픈
            솔로 레이드 시즌 38이 2026년 7월 3일 12:00:00에 재오픈됩니다.
            *오픈 시간: 2026년 7월 3일 12:00:00 ~ 2026년 7월 8일 4:59:59 (UTC+9)
            11. 솔로 레이드
            솔로 레이드 시즌 39가 2026년 7월 16일 12:00:00에 오픈됩니다.
            *오픈 시간: 2026년 7월 16일 12:00:00 ~ 2026년 7월 23일 4:59:59 (UTC+9)
            12. 신규 상품
            *판매 기간: 2026년 7월 2일 서버 점검 종료 이후 ~ 2026년 7월 23일 4:59:59 (UTC+9)
        """),
    ]
    assert periods(notices) == {
        38: [
            ("2026-06-18T12:00", "2026-06-23T04:59", "suspended"),
            ("2026-07-03T12:00", "2026-07-08T04:59", "scheduled"),
        ],
        39: [("2026-07-16T12:00", "2026-07-23T04:59", "scheduled")],
    }
    boss = {e.boss_ko for e in soloraid.extract_all(notices) if e.boss_ko}
    assert boss == {"애니힐리오"}


def test_unnumbered_seasons_take_their_number_from_enikk():
    notices = [
        update("5월 30일 업데이트 공지", at(2024, 5, 30, 19), "솔로 레이드가 2024년 6월 6일 12:00:00 (UTC+9)에 오픈됩니다.",
               "2024년 6월 6일 12:00:00 ~ 2024년 6월 13일 4:59:59 (UTC+9)"),
        update("7월 4일 업데이트 공지", at(2024, 7, 4, 6, 54), "솔로 레이드가 2024년 7월 11일 12:00:00 (UTC+9)에 오픈됩니다.",
               "2024년 7월 11일 12:00:00 ~ 2024년 7월 18일 4:59:59 (UTC+9)"),
    ]
    enikk = {
        14: EnikkSeason(14, observed_first="2024-06-09T06:50:00+09:00", observed_last="2024-06-13T05:01:00+09:00"),
        15: EnikkSeason(15, observed_first="2024-07-14T19:56:00+09:00", observed_last="2024-07-18T06:00:00+09:00"),
    }
    assert sorted(periods(notices, enikk)) == [14, 15]


def test_checks_flag_disagreement_with_enikk():
    season = soloraid.Season()
    notice = update("x", at(2026, 8, 10, 17), "솔로 레이드 시즌 40이 2026년 8월 20일 12:00:00에 오픈됩니다.",
                    "2026년 8월 20일 12:00:00 ~ 2026년 8월 27일 4:59:59 (UTC+9)",
                    element="*보스 속성: 풍압 코드 (약점 : 작열 코드)")
    season.events = soloraid.extract_events(notice)
    season.periods = soloraid.replay(season.events)
    agree = EnikkSeason(40, boss_en="Luxurious Spider", boss_element="Wind", weak_element="Fire",
                        observed_first="2026-08-22T10:09:00+09:00", observed_last="2026-08-29T00:52:00+09:00")
    assert soloraid.season_checks(season, agree) == []

    late = EnikkSeason(40, boss_en="Luxurious Spider", boss_element="Fire", weak_element="Water",
                       observed_first="2026-09-10T10:00:00+09:00", observed_last="2026-09-12T00:00:00+09:00")
    checks = soloraid.season_checks(season, late)
    assert "element_mismatch:notice=Wind,enikk=Fire" in checks
    assert "enikk_after_periods" in checks and "enikk_outside_periods" in checks
    assert soloraid.season_checks(None, agree) == ["no_notice"]


def test_a_boss_named_by_a_notice_is_named_wherever_enikk_has_it(tmp_path):
    """Season 41's notice names its boss; season 12, the same boss by enikk's name, takes that name too, and a
    boss no notice names keeps boss_ko empty. The picture comes from enikk."""
    import csv

    notice = update("9월 17일 업데이트 공지", at(2026, 9, 14, 18),
                    "솔로 레이드 시즌 41 - 리버렐리오 바디가 2026년 9월 24일에 오픈될 예정입니다.",
                    "2026년 9월 24일 12:00:00 ~ 2026년 10월 1일 4:59:59 (UTC+9)")
    enikk = {
        12: EnikkSeason(12, boss_en="Liberalio Body", boss_image="full_eba002"),
        41: EnikkSeason(41, boss_en="Liberalio Body", boss_image="full_eba002_hsta"),
        42: EnikkSeason(42, boss_en="Altruia", boss_image="full_xbg004_psid"),
    }
    soloraid.build([notice], enikk, out_dir=tmp_path)
    with (tmp_path / soloraid.SEASONS_CSV).open(encoding="utf-8") as handle:
        rows = {int(r["season"]): r for r in csv.DictReader(handle)}
    assert (rows[41]["boss_ko"], rows[41]["boss_image"]) == ("리버렐리오 바디", "full_eba002_hsta")
    assert rows[12]["boss_ko"] == "리버렐리오 바디"
    assert (rows[42]["boss_ko"], rows[42]["boss_image"]) == ("", "full_xbg004_psid")


def test_the_lounge_raid_posts_name_each_seasons_boss(tmp_path):
    """The in-game event board's post for a season names its boss, a phrase between at times. The first season's
    post has no number and season 5's name is a number puzzle: neither names anything. The name reaches the season
    table, and every season enikk gives the same English name."""
    import csv

    posts = [
        lounge("【솔로 레이드 오픈 예정】", at(2023, 5, 10, 19), """
            솔로 레이드가 곧 오픈될 예정입니다.
            ✅ 진행 기간
            - 5/11(목) 12:00 ~ 5/18(목) 4:59
        """),
        lounge("【솔로 레이드 오픈 안내】", at(2023, 9, 14, 12), """
            솔로 레이드 시즌 5가 오픈됩니다.
            이번 시즌에 등장하는 랩쳐는
            「9810811510911663」입니다.
        """),
        lounge("【솔로 레이드 오픈 안내】", at(2023, 12, 14, 12), """
            솔로 레이드 시즌 8이 오픈되었습니다!
            이번 시즌에 등장하는 랩쳐는
            인간과 같이 사고하고 말을 할 수 있는
            「토커티브」입니다.
        """),
        lounge("솔로 레이드 오픈 예정", at(2025, 9, 16, 12), """
            솔로 레이드 시즌 29가 곧 오픈될 예정입니다.
            이번에 등장할 예정인 랩쳐는
            「마더 웨일」입니다.
            ✅ 진행 기간
            - 9/16(화) 12:00 ~ 9/23(화) 4:59
        """),
    ]
    named = soloraid.announced_bosses(posts)
    assert named == {8: "토커티브", 29: "마더 웨일"}

    enikk = {
        1: EnikkSeason(1, boss_en="Mother Whale"),
        5: EnikkSeason(5, boss_en="", boss_element="Wind"),
        8: EnikkSeason(8, boss_en="Chatterbox"),
        29: EnikkSeason(29, boss_en="Mother Whale"),
    }
    soloraid.build([], enikk, bosses=named, out_dir=tmp_path)
    with (tmp_path / soloraid.SEASONS_CSV).open(encoding="utf-8") as handle:
        rows = {int(r["season"]): r["boss_ko"] for r in csv.DictReader(handle)}
    assert rows == {1: "마더 웨일", 5: "", 8: "토커티브", 29: "마더 웨일"}
