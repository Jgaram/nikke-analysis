"""Collect official announcements: update notices, patch notes, operational notices.

NIKKE is not on Steam - the only Steam entry is a Stellar Blade collaboration
DLC - so announcements come from the publisher's own channels. Two of them cover
the whole service, both in Korean, which is also the language the game files use
for the ``name_ko`` column, so unit names in a notice match the roster verbatim.

``official``  nikke-kr.com's news section. The page is a shell; the notices come
              from Level Infinite's information-feeds CMS, which answers JSON
              POSTs. Every regular update notice since the 2022-11-04 launch is
              here, with the full HTML body: new units and their recruitment
              windows, and the Solo Raid season that the update schedules.

``naver``     the official Naver Game Lounge notice board. It repeats the update
              notices and, more importantly, carries the operational ones the
              official site never gets: a Solo Raid suspended mid-season, its
              reopening on different dates, a postponement. Those are exactly the
              cases where the schedule in a patch note stops being true.

``naver_raid`` the lounge's in-game event board, its Solo Raid posts only. Every
              season since the second has one ("솔로 레이드 시즌 41이 곧 오픈될
              예정입니다 ... 랩쳐는 「리버렐리오 바디」입니다"), and it is the one
              place that names each season's boss in Korean: the update notices
              leave the boss to a picture.

Both collectors are incremental. Notices are edited after publication (titles
grow a "(9월 23일 공지 수정)" suffix), so a run re-reads anything new, anything
whose title changed and anything recent, and writes a notice only when its
content differs from the newest copy already on disk. Every stored file is the
object exactly as the API returned it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from ..util.http import Fetcher
from ..util.snapshot import SnapshotWriter, list_runs
from .base import CollectorError

log = logging.getLogger(__name__)

OFFICIAL_SOURCE = "notices_official"
NAVER_SOURCE = "notices_naver"
NAVER_RAID_SOURCE = "notices_naver_raid"

OFFICIAL_API = "https://na-community.playerinfinite.com/api/gpts.information_feeds_svr.InformationFeedsSvr"
OFFICIAL_ORIGIN = "https://www.nikke-kr.com"
OFFICIAL_GAME_ID = "16"
OFFICIAL_LANGUAGE = "ko"
OFFICIAL_AREA = "na"

# Column names as the CMS reports them (``raw_label_name``). Ids are looked up
# at run time; the numbers below are only a fallback for when the label list
# cannot be read.
OFFICIAL_PRIMARY_LABEL = "official_news"
OFFICIAL_SECONDARY_LABELS = ("NOTICE", "NEWS")
OFFICIAL_FALLBACK_IDS = {"official_news": 309, "NOTICE": 892, "NEWS": 496}
OFFICIAL_PAGE_SIZE = 50

NAVER_FEED_API = "https://comm-api.game.naver.com/nng_main/v1/community/lounge/nikke/feed"
NAVER_NOTICE_BOARD = 11
NAVER_EVENT_BOARD = 56
NAVER_RAID_TITLE_RE = re.compile(r"솔로\s*레이드")
NAVER_PAGE_SIZE = 25
NAVER_MAX_PAGES = 200

# Notices edited after this many days are rare enough to accept missing; a
# full re-read is one flag away.
RECHECK_DAYS = 45


def official_headers() -> dict[str, str]:
    """The headers the site's own CMS SDK sends; the API answers "no data" without them."""
    return {
        "Content-Type": "application/json;charset=utf-8",
        "X-GameId": OFFICIAL_GAME_ID,
        "X-AreaId": OFFICIAL_AREA,
        "X-Source": "pc_web",
        "X-Language": OFFICIAL_LANGUAGE,
        "Origin": OFFICIAL_ORIGIN,
        "Referer": OFFICIAL_ORIGIN + "/",
    }


def official_digest(detail: dict[str, Any]) -> str:
    """Hash of the parts of a notice that carry meaning.

    The raw response also holds a view counter and a request id, which change
    on every read; hashing the bytes would make every notice look edited.
    """
    stable = json.dumps(
        [detail.get("title", ""), detail.get("pub_timestamp", ""), detail.get("content", "")],
        ensure_ascii=False,
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


@dataclass
class NoticeCollectResult:
    source: str
    snapshot_dir: str
    listed: int
    fetched: int
    written: int
    notes: list[str] = field(default_factory=list)


def _known_versions(source: str, id_key: str) -> dict[str, dict[str, Any]]:
    """The newest stored copy of every notice, from the manifests of earlier runs."""
    known: dict[str, dict[str, Any]] = {}
    for run in list_runs(source):
        for entry in run.entries:
            meta = entry.get("meta") or {}
            notice_id = str(meta.get(id_key, ""))
            if notice_id:
                known[notice_id] = meta  # runs are oldest-first, so later wins
    return known


# --------------------------------------------------------------------------
# official site
# --------------------------------------------------------------------------

def resolve_official_labels(fetcher: Fetcher) -> tuple[int, dict[str, int], list[str]]:
    """Look up the notice columns by name, falling back to the known ids."""
    notes: list[str] = []
    try:
        response = fetcher.post_json(f"{OFFICIAL_API}/GetLabelList", {}, headers=official_headers())
        primaries = response.json().get("data", {}).get("primary_label_list") or []
    except (RuntimeError, ValueError) as exc:
        primaries = []
        notes.append(f"label list unavailable ({exc}); using fallback ids")

    primary = next((p for p in primaries if p.get("raw_label_name") == OFFICIAL_PRIMARY_LABEL), None)
    if primary is None:
        if primaries:
            notes.append(f"column {OFFICIAL_PRIMARY_LABEL!r} not found; using fallback ids")
        return (
            OFFICIAL_FALLBACK_IDS[OFFICIAL_PRIMARY_LABEL],
            {name: OFFICIAL_FALLBACK_IDS[name] for name in OFFICIAL_SECONDARY_LABELS},
            notes,
        )

    secondary: dict[str, int] = {}
    for wanted in OFFICIAL_SECONDARY_LABELS:
        match = next(
            (s for s in primary.get("secondary_label_list") or [] if s.get("raw_label_name") == wanted),
            None,
        )
        if match is None:
            notes.append(f"column {wanted!r} not found; using fallback id")
            secondary[wanted] = OFFICIAL_FALLBACK_IDS[wanted]
        else:
            secondary[wanted] = int(match["label_id"])
    return int(primary["label_id"]), secondary, notes


def list_official(
    fetcher: Fetcher, primary_id: int, secondary_id: int, *, page_size: int = OFFICIAL_PAGE_SIZE
) -> list[dict[str, Any]]:
    """Every item in one column, newest first."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = fetcher.post_json(
            f"{OFFICIAL_API}/GetContentByLabel",
            {
                "gameid": OFFICIAL_GAME_ID,
                "language": [OFFICIAL_LANGUAGE],
                "offset": offset,
                "get_num": page_size,
                "primary_label_id": primary_id,
                "secondary_label_id": secondary_id,
            },
            headers=official_headers(),
        )
        data = response.json().get("data") or {}
        batch = data.get("info_content") or []
        items.extend(batch)
        total = int(data.get("total_num") or 0)
        next_offset = data.get("next_offset")
        if not batch or len(items) >= total or next_offset in (None, offset):
            break
        offset = int(next_offset)
    return items


def collect_official(
    *,
    full: bool = False,
    recheck_days: int = RECHECK_DAYS,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> NoticeCollectResult:
    """Snapshot every new or edited notice from the official site."""
    fetcher = fetcher or Fetcher(delay=1.0)
    now = now or datetime.now(timezone.utc)
    known = _known_versions(OFFICIAL_SOURCE, "content_id")
    primary_id, secondary_ids, notes = resolve_official_labels(fetcher)

    listed: dict[str, dict[str, Any]] = {}
    columns: dict[str, list[str]] = {}
    for name, secondary_id in secondary_ids.items():
        for item in list_official(fetcher, primary_id, secondary_id):
            content_id = str(item.get("content_id", ""))
            if not content_id:
                continue
            listed.setdefault(content_id, item)
            columns.setdefault(content_id, []).append(name)
    if not listed:
        raise CollectorError("the official notice list came back empty; the CMS contract may have changed")

    cutoff = int((now - timedelta(days=recheck_days)).timestamp())
    writer = SnapshotWriter(OFFICIAL_SOURCE)
    fetched = written = 0
    for content_id, item in sorted(listed.items(), key=lambda kv: int(kv[1].get("pub_timestamp") or 0)):
        previous = known.get(content_id)
        recent = int(item.get("pub_timestamp") or 0) >= cutoff
        retitled = previous is not None and previous.get("title") != item.get("title")
        if not (full or previous is None or retitled or recent):
            continue

        response = fetcher.post_json(
            f"{OFFICIAL_API}/GetContentInfoById",
            {"content_id": content_id, "gameid": OFFICIAL_GAME_ID, "language": [OFFICIAL_LANGUAGE]},
            headers=official_headers(),
        )
        fetched += 1
        detail = response.json().get("data") or {}
        if not detail.get("content_id"):
            notes.append(f"{content_id}: detail request returned no content")
            continue
        digest = official_digest(detail)
        if previous is not None and previous.get("digest") == digest:
            continue
        writer.write(
            f"detail/{content_id}.json",
            response.content,
            url=f"{OFFICIAL_ORIGIN}/newsdetail.html?content_id={content_id}",
            status=response.status,
            content_type=response.content_type,
            meta={
                "content_id": content_id,
                "title": detail.get("title", ""),
                "pub_timestamp": str(detail.get("pub_timestamp", "")),
                "columns": columns.get(content_id, []),
                "digest": digest,
            },
        )
        written += 1

    if written == 0:
        writer.discard()
        log.info("official notices: %s listed, %s re-read, nothing new", len(listed), fetched)
        return NoticeCollectResult(OFFICIAL_SOURCE, "", len(listed), fetched, 0, notes)

    writer.seal(
        {
            "api": OFFICIAL_API,
            "game_id": OFFICIAL_GAME_ID,
            "language": OFFICIAL_LANGUAGE,
            "primary_label_id": primary_id,
            "secondary_label_ids": secondary_ids,
            "listed": len(listed),
            "fetched": fetched,
            "written": written,
            "full": full,
            "notes": notes,
        }
    )
    log.info("official notices: %s listed, %s fetched, %s new/changed -> %s", len(listed), fetched, written, writer.dir)
    return NoticeCollectResult(OFFICIAL_SOURCE, str(writer.dir), len(listed), fetched, written, notes)


# --------------------------------------------------------------------------
# Naver lounge
# --------------------------------------------------------------------------

def iter_naver_pages(
    fetcher: Fetcher, *, board_id: int = NAVER_NOTICE_BOARD, max_pages: int = NAVER_MAX_PAGES
) -> Iterable[list[dict[str, Any]]]:
    """Pages of the board, newest first.

    The lounge API's ``offset`` is a page index, not an item offset - asking for
    offset 25 returns the 26th *page*.
    """
    for page in range(max_pages):
        response = fetcher.get(
            NAVER_FEED_API,
            params={
                "boardId": board_id,
                "buffFilteringYN": "N",
                "limit": NAVER_PAGE_SIZE,
                "offset": page,
                "order": "NEW",
            },
            headers={"Referer": "https://game.naver.com/"},
        )
        content = response.json().get("content") or {}
        feeds = content.get("feeds") or []
        if not feeds:
            return
        yield feeds


def collect_naver(
    *,
    full: bool = False,
    board_id: int = NAVER_NOTICE_BOARD,
    source: str = NAVER_SOURCE,
    keep: Callable[[dict[str, Any]], bool] | None = None,
    fetcher: Fetcher | None = None,
) -> NoticeCollectResult:
    """Snapshot every new or edited post on one lounge board (the notice board by default).

    Paging stops at the first page with nothing new, unless ``full`` is set. Posts
    carry an ``updatedDate``, so an edit shows up as a new version rather than
    being missed. ``keep`` (a post's ``feed`` -> bool) stores only some of a
    board's posts; a page with none of them says nothing about what is new, so
    paging goes on past it.
    """
    fetcher = fetcher or Fetcher(delay=1.0)
    known = _known_versions(source, "feed_id")
    writer = SnapshotWriter(source)
    listed = written = 0

    for feeds in iter_naver_pages(fetcher, board_id=board_id):
        fresh_on_page = kept_on_page = 0
        for item in feeds:
            feed = item.get("feed") or {}
            feed_id = str(feed.get("feedId", ""))
            if not feed_id or (keep is not None and not keep(feed)):
                continue
            kept_on_page += 1
            listed += 1
            updated = str(feed.get("updatedDate") or feed.get("createdDate") or "")
            previous = known.get(feed_id)
            if previous is not None and previous.get("updated") == updated:
                continue
            fresh_on_page += 1
            writer.write(
                f"feed/{feed_id}.json",
                json.dumps(item, ensure_ascii=False).encode("utf-8"),
                url=f"https://game.naver.com/lounge/nikke/board/detail/{feed_id}",
                content_type="application/json",
                meta={
                    "feed_id": feed_id,
                    "title": feed.get("title", ""),
                    "created": feed.get("createdDate", ""),
                    "updated": updated,
                    "board_id": board_id,
                },
            )
            known[feed_id] = {"updated": updated}
            written += 1
        if not full and kept_on_page and fresh_on_page == 0:
            break

    if written == 0:
        writer.discard()
        log.info("%s: %s listed, nothing new", source, listed)
        return NoticeCollectResult(source, "", listed, listed, 0)

    writer.seal({"api": NAVER_FEED_API, "board_id": board_id, "listed": listed, "written": written, "full": full})
    log.info("%s: %s listed, %s new/changed -> %s", source, listed, written, writer.dir)
    return NoticeCollectResult(source, str(writer.dir), listed, listed, written)


def collect_naver_raid(*, full: bool = False, fetcher: Fetcher | None = None) -> NoticeCollectResult:
    """Snapshot the Solo Raid posts of the lounge's in-game event board: each season's boss, by its Korean name."""
    return collect_naver(
        full=full,
        board_id=NAVER_EVENT_BOARD,
        source=NAVER_RAID_SOURCE,
        keep=lambda feed: bool(NAVER_RAID_TITLE_RE.search(str(feed.get("title") or ""))),
        fetcher=fetcher,
    )
