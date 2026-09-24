from datetime import datetime

from nikke_analysis.build import releases
from nikke_analysis.build.notices import Notice
from nikke_analysis.util.kdate import KST
from nikke_analysis.util.names import build_name_index

ROSTER = [
    {"unit_id": "100", "name_ko": "라플라스"},
    {"unit_id": "104", "name_ko": "드레이크 : 그레이트 빌런"},
    {"unit_id": "121", "name_ko": "앤 : 미라클 페어리"},
    {"unit_id": "260", "name_ko": "모더니아"},
    {"unit_id": "282", "name_ko": "사쿠라"},
    {"unit_id": "836", "name_ko": "사쿠라"},
    {"unit_id": "361", "name_ko": "킬로"},
    {"unit_id": "404", "name_ko": "길티 : 마이티 바니"},
    {"unit_id": "405", "name_ko": "신 : 스위프트 바니"},
]
KNOWN_SINCE = {"282": "2023-03-30", "836": "2025-02-20"}


def notice(text, title, published):
    return Notice(f"official:{title}", "official", published, None, title, "", text.strip())


def extract(text, title="업데이트 공지", published=datetime(2026, 9, 14, 18, 0, tzinfo=KST)):
    matcher = releases.UnitMatcher(build_name_index(ROSTER), KNOWN_SINCE)
    return releases.extract_banners(notice(text, title, published), matcher)


CURRENT_FORMAT = """
존경하는 지휘관님,
SSR 니케 [드레이크 : 그레이트 빌런]은 일반 모집, 소셜 포인트 모집, 몰드 아이템을 통해 모집 가능합니다.
업데이트 주요 내용:
1. 신규 니케
1.1 SSR 니케 [길티 : 마이티 바니]
괴력에 첨단 슈트를 더한 초강화 SF 바니, SSR 니케 [길티 : 마이티 바니]가 특수 모집에 합류합니다.
- 클래스: 화력형
*특수 모집 기간: 2026년 9월 17일 서버 점검 종료 이후 ~ 2026년 10월 8일 4:59:59 (UTC+9)
② 특수 모집의 경우 SSR 니케 획득 확률은 4%이며, 그중 SSR [길티 : 마이티 바니]의 획득 확률은 2%입니다.
1.2 SSR 니케 [신 : 스위프트 바니]
귓가를 홀리는 목소리와 눈을 속이는 질주, SSR 니케 [신 : 스위프트 바니]가 특수 모집에 합류합니다.
*특수 모집 기간: 2026년 9월 24일 5:00:00 ~ 2026년 10월 15일 4:59:59 (UTC+9)
1.3 니케 임시 합류 기능
*임시 합류 가능 기간:
① [길티 : 마이티 바니]: 2026년 9월 17일 서버 점검 종료 이후 ~ 2026년 10월 8일 4:59:59 (UTC+9)
2. 기간 한정 선택 모집
2.1 SSR 니케 [앤 : 미라클 페어리]
어제를 기억할 수 있는 기적을 맞이한 소녀, SSR 니케 [앤 : 미라클 페어리]가 기간 한정 선택 모집으로 재합류합니다.
*기간 한정 선택 모집 기간: 2026년 9월 17일 서버 점검 종료 이후 ~ 2026년 10월 8일 4:59:59 (UTC+9)
3. 신규 코스튬
3.1 한정 코스튬: 슈가 - 킬러 래빗
"""


def test_each_new_unit_gets_its_own_window():
    banners, unresolved = extract(CURRENT_FORMAT, "9월 17일 업데이트 공지")
    debuts = {b.unit_id: b for b in banners if b.debut}
    assert set(debuts) == {"404", "405"}
    assert debuts["404"].start_at == "2026-09-17T00:00:00+09:00" and debuts["404"].start_after_maintenance
    # The second unit of a patch opens a week later - not on the notice date.
    assert debuts["405"].start_at == "2026-09-24T05:00:00+09:00"
    assert unresolved == []


def test_a_selection_rerun_is_a_banner_but_never_a_release():
    banners, _ = extract(CURRENT_FORMAT, "9월 17일 업데이트 공지")
    rerun = [b for b in banners if b.unit_id == "121"]
    assert len(rerun) == 1 and rerun[0].kind == "limited_selection" and not rerun[0].debut
    assert {r.unit_id for r in releases.first_debuts(banners)} == {"404", "405"}


def test_the_2022_format_without_headings_or_brackets():
    banners, _ = extract(
        """
        업데이트 주요 내용:
        1. 신규 캐릭터
        방주의 히어로, SSR 니케 라플라스가 특수 모집에 합류합니다.
        특수 모집 기간: 2022년 11월 24일 서버 점검 종료 이후 ~ 2022년 12월 8일 4:59:59 (UTC+9)
        """.replace("        ", ""),
        "11월 24일 업데이트 공지",
        datetime(2022, 11, 21, 16, 30, tzinfo=KST),
    )
    assert [(b.unit_id, b.start_at[:10], b.debut) for b in banners] == [("100", "2022-11-24", 1)]


def test_a_step_up_recruit_in_its_own_section_does_not_inherit_the_unit():
    banners, _ = extract(
        """
        1. 신규 캐릭터
        1.1 SSR 필그림 [모더니아]
        예전의 순수함을 아직 가슴속에 간직하고 있는, SSR 필그림 [모더니아]가 특수 모집에 합류합니다.
        *특수 모집 기간: 2023년 1월 1일 00:00:00 ～ 2023년 1월 19일 4:59:59(UTC+9)
        1.2 신년 특별 스텝업 모집
        *모집 기간: 2023년 1월 1일 00:00:00 ～ 2023년 1월 11일 23:59:59(UTC+9)
        """.replace("        ", ""),
        "12월 29일 업데이트 공지",
        datetime(2022, 12, 26, 16, 0, tzinfo=KST),
    )
    assert [(b.unit_id, b.end_at[:10]) for b in banners] == [("260", "2023-01-19")]


def test_a_free_unit_without_a_window_arrives_with_the_update():
    banners, _ = extract(
        """
        1. 신규 캐릭터
        1.1 SSR 니케 [킬로]
        인간형 병기 T.A.L.O.S.와 함께 싸우는 SSR 니케 [킬로]가 전장에 합류합니다.
        [킬로]는 스토리 이벤트 LAST KINGDOM, 14 Days Login 이벤트에서 획득할 수 있습니다.
        2. 신규 코스튬
        """.replace("        ", ""),
        "4월 25일 업데이트 공지",
        datetime(2024, 4, 24, 18, 0, tzinfo=KST),
    )
    [banner] = banners
    assert (banner.unit_id, banner.kind, banner.debut) == ("361", "introduced", 1)
    assert banner.start_at == "2024-04-25T00:00:00+09:00"


def test_a_shared_name_resolves_to_the_unit_that_existed_then():
    text = """
    1. 신규 캐릭터
    1.1 SSR 캐릭터 [사쿠라]
    지하세계의 여왕, SSR 니케 [사쿠라]가 특수 모집에 합류합니다.
    *특수 모집 기간: 2023년 3월 30일 서버 점검 종료 이후 ~ 2023년 4월 13일 4:59:59 (UTC+9)
    """.replace("    ", "")
    banners, _ = extract(text, "3월 30일 업데이트 공지", datetime(2023, 3, 27, 18, 30, tzinfo=KST))
    assert [b.unit_id for b in banners] == ["282"]

    # Two years later both units exist, so the same wording is reported, not guessed.
    banners, unresolved = extract(text, "3월 30일 업데이트 공지", datetime(2025, 3, 27, 18, 30, tzinfo=KST))
    assert banners == []
    assert [u.name for u in unresolved] == ["사쿠라"]


def test_an_unknown_new_unit_is_reported():
    banners, unresolved = extract(
        """
        1. 신규 니케
        1.1 SSR 니케 [미지의 니케]
        *특수 모집 기간: 2026년 10월 1일 서버 점검 종료 이후 ~ 2026년 10월 22일 4:59:59 (UTC+9)
        """.replace("        ", ""),
    )
    assert banners == []
    assert [u.name for u in unresolved] == ["미지의 니케"]


def test_first_debuts_prefers_a_real_window_on_a_tie():
    window = releases.Banner("040", "special", 1, "2023-04-13T00:00:00+09:00", "2023-04-27T04:59:59+09:00", 1,
                             "a", "a", "2023-04-11T19:42:00+09:00", "특수 모집 기간", "")
    introduced = releases.Banner("040", "introduced", 1, "2023-04-13T00:00:00+09:00", "", 1,
                                 "b", "b", "2023-04-10T19:42:00+09:00", "", "")
    [release] = releases.first_debuts([introduced, window])
    assert release.banner_kind == "special"
