import json
from datetime import datetime

from nikke_analysis.build.notices import (
    Notice,
    classify,
    html_to_text,
    parse_naver,
    parse_official,
    smart_editor_to_text,
)
from nikke_analysis.util.kdate import KST


def notice(text, title="업데이트 공지", published=datetime(2026, 9, 14, 18, 0, tzinfo=KST), source="official"):
    return Notice(
        notice_id=f"{source}:x",
        source=source,
        published_at=published,
        updated_at=None,
        title=title,
        url="",
        text=text,
    )


def test_inline_markup_joins_and_blocks_break():
    """The site wraps single digits in spans: "1<span>1</span>." must stay "11."."""
    html = "<p>1<span>1</span>. 신규 콘텐츠</p><p><strong>SSR</strong> 니케 [길티]</p><div>a<br>b</div>"
    assert html_to_text(html).split("\n") == ["11. 신규 콘텐츠", "SSR 니케 [길티]", "a", "b"]


def test_smart_editor_document_becomes_paragraph_lines():
    document = {
        "document": {
            "components": [
                {"@ctype": "text", "value": [
                    {"@ctype": "paragraph", "nodes": [{"@ctype": "textNode", "value": "✔️ 중단 일시"}]},
                    {"@ctype": "paragraph", "nodes": [{"@ctype": "textNode", "value": "- 6/23(화) 4:59:59​"}]},
                ]},
                {"@ctype": "image", "src": "x"},
            ]
        }
    }
    assert smart_editor_to_text(json.dumps(document)) == "✔️ 중단 일시\n- 6/23(화) 4:59:59"


def test_both_channels_parse_to_the_same_shape():
    official = parse_official(
        json.dumps({"data": {"content_id": "abc", "title": "9월 17일 업데이트 공지", "pub_timestamp": "1789376443",
                             "content": "<p>본문</p>"}}).encode(),
        "https://www.nikke-kr.com/newsdetail.html?content_id=abc",
    )
    assert official.notice_id == "official:abc"
    assert official.published_at.tzinfo is not None and official.text == "본문"

    naver = parse_naver(
        json.dumps({"feed": {"feedId": 42, "title": "솔로 레이드 연기 안내", "createdDate": "20231208001247",
                             "updatedDate": "20231208001247", "contents": "{}"}}).encode()
    )
    assert naver.notice_id == "naver:42"
    assert naver.published_at == datetime(2023, 12, 8, 0, 12, 47, tzinfo=KST)


def test_classify_puts_raid_operations_first():
    assert classify("솔로 레이드 시즌 26 일시 중단 안내") == "soloraid"
    assert classify("9월 17일 업데이트 공지") == "update"
    assert classify("9월 17일 업데이트 개선사항") == "patch_fix"
    assert classify("9월 17일 알려진 이슈 안내") == "known_issue"
    assert classify("부정행위 제재 명단 안내") == "sanction"
    assert classify("12/23(금) 업데이트 안내") == "update"
    assert classify("공식 MMD 모델 업데이트 안내") == "other"
