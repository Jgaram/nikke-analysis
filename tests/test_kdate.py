from datetime import date, datetime

from nikke_analysis.util.kdate import KST, find_points, find_spans, find_until, parse_moment


def iso(stamp):
    return stamp.iso() if stamp else None


def test_full_korean_range_with_seconds():
    [span] = find_spans("*오픈 시간: 2026년 9월 24일 12:00:00 ~ 2026년 10월 1일 4:59:59 (UTC+9)", date(2026, 9, 14))
    assert iso(span.start) == "2026-09-24T12:00:00+09:00"
    assert iso(span.end) == "2026-10-01T04:59:59+09:00"
    assert not span.start.after_maintenance


def test_maintenance_anchored_start_is_flagged_not_guessed():
    [span] = find_spans(
        "*특수 모집 기간: 2022년 11월 10일(목) 서버 점검 종료 이후 ~ 2022년 11월 24일(목) 4:59:59", date(2022, 11, 9)
    )
    assert iso(span.start) == "2022-11-10T00:00:00+09:00"
    assert span.start.after_maintenance and not span.start.has_time


def test_yearless_dates_take_the_year_of_the_notice():
    [span] = find_spans("- 6/24(화) 점검 완료 후 ~ 7/1(화) 4:59", date(2025, 6, 24))
    assert iso(span.start) == "2025-06-24T00:00:00+09:00"
    assert span.start.after_maintenance
    # "4:59" as an end means through that minute.
    assert iso(span.end) == "2025-07-01T04:59:59+09:00"


def test_a_time_only_end_shares_the_start_day():
    [span] = find_spans("솔로 레이드 시즌 28 일시 중단 기간: 8/26일(화) 17:00 ~ 21:00", date(2025, 8, 26))
    assert (iso(span.start), iso(span.end)) == ("2025-08-26T17:00:00+09:00", "2025-08-26T21:00:00+09:00")


def test_to_be_announced_leaves_the_end_open():
    [span] = find_spans("일시: 6월 20일(금) 00:00 ~  추후 안내", date(2025, 6, 19))
    assert iso(span.start) == "2025-06-20T00:00:00+09:00"
    assert span.end is None


def test_fullwidth_punctuation_and_missing_spaces():
    [span] = find_spans("*기간 한정 모집 기간: 2023년 9월 8일 5:00:00～2023년 9월 28일 4:59:59（UTC+9）", date(2023, 8, 28))
    assert iso(span.start) == "2023-09-08T05:00:00+09:00"
    [span] = find_spans("*오픈 시간: 2023년 5월11일 12:00:00 ~ 2023년 5월 18일 4:59:59", date(2023, 4, 25))
    assert iso(span.start) == "2023-05-11T12:00:00+09:00"


def test_a_yearless_range_across_new_year():
    [span] = find_spans("12월 30일 ~ 1월 5일", date(2025, 12, 29))
    assert iso(span.start) == "2025-12-30T00:00:00+09:00"
    assert iso(span.end) == "2026-01-05T23:59:59+09:00"


def test_until_and_points():
    assert iso(find_until("진행 기간 연장: 11/17(일) 5:00까지", date(2024, 11, 12))) == "2024-11-17T05:00:00+09:00"
    [point] = find_points("솔로 레이드 시즌 19가 11월 12일(화) 18:00에 일시 중단됩니다.", date(2024, 11, 12))
    assert iso(point) == "2024-11-12T18:00:00+09:00"


def test_section_numbers_are_not_dates():
    assert find_points("1.1 SSR 니케 [길티 : 마이티 바니]", date(2026, 9, 14)) == []


def test_a_bare_date_means_noon_kst():
    assert parse_moment("2024-11-04") == datetime(2024, 11, 4, 12, 0, tzinfo=KST)
    assert parse_moment("2024-11-04T09:30").hour == 9
