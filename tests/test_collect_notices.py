"""Incremental notice collection against fake APIs: new and edited notices only."""

import json
from datetime import datetime, timezone

import pytest

from nikke_analysis.collect import notices
from nikke_analysis.util.http import Response
from nikke_analysis.util.snapshot import list_runs


def response(url, payload):
    return Response(url, 200, json.dumps(payload, ensure_ascii=False).encode(), "application/json", {})


class FakeLounge:
    def __init__(self, feeds):
        self.feeds = feeds  # newest first

    def get(self, url, params=None, headers=None, allow_status=None):
        page, size = params["offset"], params["limit"]
        chunk = self.feeds[page * size:(page + 1) * size]
        return response(url, {"content": {"feeds": chunk, "totalCount": len(self.feeds)}})


def feed(feed_id, title, updated):
    return {"feed": {"feedId": feed_id, "title": title, "createdDate": "20260901120000", "updatedDate": updated,
                     "contents": "{}"}}


class FakeCms:
    def __init__(self, items):
        self.items = items  # content_id -> (title, pub_timestamp, html)
        self.detail_calls = 0

    def post_json(self, url, body, headers=None, allow_status=None):
        if url.endswith("/GetLabelList"):
            return response(url, {"data": {"primary_label_list": [{
                "label_id": 309, "raw_label_name": "official_news",
                "secondary_label_list": [{"label_id": 892, "raw_label_name": "NOTICE"},
                                         {"label_id": 496, "raw_label_name": "NEWS"}]}]}})
        if url.endswith("/GetContentByLabel"):
            listed = [
                {"content_id": cid, "title": title, "pub_timestamp": str(ts)}
                for cid, (title, ts, _) in self.items.items()
            ] if body["secondary_label_id"] == 892 else []
            chunk = listed[body["offset"]:body["offset"] + body["get_num"]]
            return response(url, {"data": {"info_content": chunk, "total_num": len(listed),
                                           "next_offset": body["offset"] + len(chunk)}})
        if url.endswith("/GetContentInfoById"):
            self.detail_calls += 1
            title, ts, html = self.items[body["content_id"]]
            return response(url, {"data": {"content_id": body["content_id"], "title": title,
                                           "pub_timestamp": str(ts), "content": html, "view_num": self.detail_calls}})
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NIKKE_DATA_ROOT", str(tmp_path))


def test_the_lounge_is_read_until_nothing_is_new():
    lounge = FakeLounge([feed(i, f"notice {i}", "20260901120000") for i in range(30, 0, -1)])
    first = notices.collect_naver(fetcher=lounge)
    assert first.written == 30

    again = notices.collect_naver(fetcher=lounge)
    assert (again.written, again.snapshot_dir) == (0, "")
    assert len(list_runs(notices.NAVER_SOURCE)) == 1  # an idle run leaves nothing behind

    lounge.feeds[0] = feed(30, "notice 30 (수정)", "20260902090000")
    edited = notices.collect_naver(fetcher=lounge)
    assert edited.written == 1


def test_official_notices_are_refetched_only_when_new_edited_or_recent():
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    old, recent = 1_700_000_000, int(now.timestamp()) - 86_400
    cms = FakeCms({"a": ("9월 17일 업데이트 공지", old, "<p>본문</p>"), "b": ("공지", recent, "<p>x</p>")})

    first = notices.collect_official(fetcher=cms, now=now)
    assert (first.listed, first.written) == (2, 2)

    cms.detail_calls = 0
    again = notices.collect_official(fetcher=cms, now=now)
    # Only the recent notice is re-read, and unchanged content is not stored again.
    assert (cms.detail_calls, again.written, again.snapshot_dir) == (1, 0, "")

    cms.items["a"] = ("9월 17일 업데이트 공지(9월 23일 공지 수정)", old, "<p>본문 수정</p>")
    edited = notices.collect_official(fetcher=cms, now=now)
    assert edited.written == 1
