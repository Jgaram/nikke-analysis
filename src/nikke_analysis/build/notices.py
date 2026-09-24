"""Official announcements as one table, whichever channel they came from.

Both notice collectors store what their API returned: the official site an HTML
body, the Naver lounge a SmartEditor document. This module turns both into the
same thing - a title, a publication time in KST and the body as plain text, one
logical line per line - so the parsers downstream never need to know where a
notice was posted.

Output: ``notices.csv``, one row per notice (the text itself is not stored; the
raw snapshots are the record, and the parsers quote the lines they used).
"""

from __future__ import annotations

import csv
import html as html_lib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..collect.notices import NAVER_SOURCE, OFFICIAL_SOURCE
from ..paths import processed_dir
from ..util.kdate import KST
from ..util.snapshot import list_runs

log = logging.getLogger(__name__)

NOTICES_CSV = "notices.csv"

# A numbered section heading: "1. 신규 니케", "1.1 SSR 니케 [...]", "2-1. ...", "1) ...".
HEADING_RE = re.compile(r"^\s*(?P<num>\d{1,2}(?:[.\-]\d{1,2})*)(?:\s*[.)）]\s*|\s+)(?P<rest>\S.*)$")

_BLOCK_TAGS = (
    "p", "div", "li", "ul", "ol", "table", "tr", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
)
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿"), None)
_SPACES_RE = re.compile(r"[ \t 　]+")

# Title keywords, checked in order. Operational Solo Raid notices come first:
# they are the ones that overrule an update notice's schedule.
KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("soloraid", ("솔로 레이드", "솔로레이드")),
    ("known_issue", ("알려진 이슈",)),
    ("patch_fix", ("개선사항", "개선 사항")),
    ("update", ("업데이트 공지", "업데이트 사전 공지", "업데이트 정기점검", "신규 추가 콘텐츠", "신규 추가 컨텐츠")),
    ("maintenance", ("점검",)),
    ("devnote", ("개발자 노트", "개발자노트")),
    ("sanction", ("제재", "차단", "불법 프로그램", "부정행위")),
    ("event", ("이벤트",)),
)


@dataclass
class Notice:
    notice_id: str
    source: str
    published_at: datetime
    updated_at: datetime | None
    title: str
    url: str
    text: str

    @property
    def kind(self) -> str:
        return classify(self.title)

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


# "12/23(금) 업데이트 안내" is a game update; "공식 MMD 모델 업데이트 안내" is not.
_DATED_UPDATE_RE = re.compile(r"\d{1,2}\s*(?:월|/)\s*\d{1,2}\s*일?\s*(?:[(（][월화수목금토일][)）])?\s*업데이트\s*안내")


def classify(title: str) -> str:
    for kind, markers in KIND_RULES:
        if any(marker in title for marker in markers):
            return kind
        if kind == "update" and _DATED_UPDATE_RE.search(title):
            return kind
    return "other"


def clean_line(value: str) -> str:
    return _SPACES_RE.sub(" ", html_lib.unescape(value).translate(_INVISIBLE)).strip()


def html_to_text(markup: str) -> str:
    """Block elements become line breaks; inline markup joins its text.

    The notices wrap single digits in their own ``<span>``s ("1<span>1</span>.
    신규 콘텐츠"), so inline elements must be joined without a separator or the
    section numbers fall apart.
    """
    from bs4 import BeautifulSoup  # local import: only notice parsing needs it

    soup = BeautifulSoup(markup or "", "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for element in soup.find_all(_BLOCK_TAGS):
        element.insert_before("\n")
        element.insert_after("\n")
    for cell in soup.find_all(["td", "th"]):
        cell.insert_after(" | ")
    lines = (clean_line(line) for line in soup.get_text("").split("\n"))
    return "\n".join(line for line in lines if line)


def _text_nodes(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        if node.get("@ctype") == "textNode" and "value" in node:
            yield str(node["value"])
        for value in node.values():
            yield from _text_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _text_nodes(value)


def _paragraphs(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        if node.get("@ctype") == "paragraph":
            yield "".join(_text_nodes(node))
            return
        for value in node.values():
            yield from _paragraphs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _paragraphs(value)


def smart_editor_to_text(contents: str) -> str:
    """Naver's SmartEditor document (a JSON string) as plain text, one paragraph per line."""
    try:
        document = json.loads(contents or "{}")
    except json.JSONDecodeError:
        return clean_line(contents or "")
    components = (document.get("document") or {}).get("components") or []
    lines = (clean_line(paragraph) for paragraph in _paragraphs(components))
    return "\n".join(line for line in lines if line)


def _naver_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def parse_official(payload: bytes, url: str = "") -> Notice | None:
    data = (json.loads(payload.decode("utf-8")).get("data")) or {}
    content_id = str(data.get("content_id") or "")
    if not content_id:
        return None
    published = datetime.fromtimestamp(int(data.get("pub_timestamp") or 0), tz=KST)
    return Notice(
        notice_id=f"official:{content_id}",
        source="official",
        published_at=published,
        updated_at=None,
        title=clean_line(str(data.get("title") or "")),
        url=url,
        text=html_to_text(str(data.get("content") or "")),
    )


def parse_naver(payload: bytes, url: str = "") -> Notice | None:
    item = json.loads(payload.decode("utf-8"))
    feed = item.get("feed") or {}
    feed_id = str(feed.get("feedId") or "")
    published = _naver_time(str(feed.get("createdDate") or ""))
    if not feed_id or published is None:
        return None
    return Notice(
        notice_id=f"naver:{feed_id}",
        source="naver",
        published_at=published,
        updated_at=_naver_time(str(feed.get("updatedDate") or "")),
        title=clean_line(str(feed.get("title") or "")),
        url=url,
        text=smart_editor_to_text(str(feed.get("contents") or "")),
    )


def load_notices(root: Path | None = None) -> list[Notice]:
    """The newest stored copy of every notice, oldest publication first."""
    latest: dict[str, Notice] = {}
    for source, parser in ((OFFICIAL_SOURCE, parse_official), (NAVER_SOURCE, parse_naver)):
        for run in list_runs(source, root=root):  # oldest run first, so later copies win
            for entry in run.entries:
                try:
                    notice = parser(run.read(entry["filename"]), entry.get("url", ""))
                except (OSError, ValueError, KeyError) as exc:
                    log.warning("unreadable notice %s/%s: %s", run.run_id, entry.get("filename"), exc)
                    continue
                if notice is not None:
                    latest[notice.notice_id] = notice
    return sorted(latest.values(), key=lambda n: (n.published_at, n.notice_id))


def build(*, notices: list[Notice] | None = None, out_dir: Path | None = None) -> dict[str, Any]:
    notices = notices if notices is not None else load_notices()
    if not notices:
        raise RuntimeError("no notice snapshots found; run `nikke collect notices` first")
    target = (out_dir or processed_dir()) / NOTICES_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["notice_id", "source", "published_at", "updated_at", "kind", "title", "url", "chars"],
        )
        writer.writeheader()
        for notice in notices:
            writer.writerow(
                {
                    "notice_id": notice.notice_id,
                    "source": notice.source,
                    "published_at": notice.published_at.isoformat(),
                    "updated_at": notice.updated_at.isoformat() if notice.updated_at else "",
                    "kind": notice.kind,
                    "title": notice.title,
                    "url": notice.url,
                    "chars": len(notice.text),
                }
            )
    kinds: dict[str, int] = {}
    for notice in notices:
        kinds[notice.kind] = kinds.get(notice.kind, 0) + 1
    return {
        "notices": len(notices),
        "by_source": {s: sum(1 for n in notices if n.source == s) for s in ("official", "naver")},
        "by_kind": dict(sorted(kinds.items())),
        "range": [notices[0].published_at.date().isoformat(), notices[-1].published_at.date().isoformat()],
        "notices_csv": str(target),
    }
