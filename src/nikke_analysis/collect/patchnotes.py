"""Collect patch notes / update announcements.

Three sources, deliberately ordered by how mechanical they are to parse:

1. ``steam``    - Steam's ISteamNews web API. Plain JSON, no markup churn, goes
                  back to the PC launch, and every NIKKE update is posted there
                  as an official announcement. This is the backbone.
2. ``official`` - the publisher's own news list. Needed because Steam
                  announcements are occasionally trimmed versions of the full
                  notice, and because the pre-Steam history only exists here.
3. ``fansite``  - a community patch-note archive, used only as a cross-check for
                  dates the first two disagree on.

Only ``steam`` runs by default; the other two need their base URLs allowlisted
in the environment's network policy (see docs/network-policy.md).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

from ..util.http import Fetcher
from ..util.snapshot import SnapshotWriter
from .base import CollectorError

log = logging.getLogger(__name__)

STEAM_SOURCE = "patchnotes_steam"
OFFICIAL_SOURCE = "patchnotes_official"

STEAM_NEWS_ENDPOINT = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
STEAM_APP_SEARCH_ENDPOINT = "https://steamcommunity.com/actions/SearchApps/"

# Steam app ids are not derivable from a title, and the game has several
# entries (global client, regional editions, a Stellar Blade collaboration page).
# Rather than bake in an id that might quietly collect the wrong history, the
# default is to look it up and fail loudly on an ambiguous match. Pin a known-good
# id in config/sources.yaml or via `nikke collect patchnotes --steam-appid`.
STEAM_APP_TITLE = "GODDESS OF VICTORY"

# The API caps `count` per call, so we page backwards through `enddate`.
STEAM_PAGE_SIZE = 100
STEAM_MAX_PAGES = 40


def resolve_steam_appid(
    term: str = "GODDESS OF VICTORY",
    *,
    endpoint: str = STEAM_APP_SEARCH_ENDPOINT,
    fetcher: Fetcher | None = None,
) -> list[dict[str, str]]:
    """Ask Steam which app ids match a title.

    Steam ids are not guessable and the game has several entries (global client,
    regional editions, collaboration pages). Rather than hard-coding one and
    silently collecting the wrong history, the pipeline can look it up and record
    the answer. Returns ``[{"appid": ..., "name": ...}, ...]``.
    """
    fetcher = fetcher or Fetcher(delay=0.5)
    response = fetcher.get(f"{endpoint}{term}")
    return [
        {"appid": str(row.get("appid", "")), "name": str(row.get("name", ""))}
        for row in response.json()
    ]


@dataclass
class SteamCollectResult:
    snapshot_dir: str
    page_count: int
    item_count: int


def pick_steam_appid(candidates: list[dict[str, str]], title: str = STEAM_APP_TITLE) -> int:
    """Choose one app id from a Steam app-search result, or refuse.

    An exact (case-insensitive) title match wins. Anything else - no match, or
    several equally-good matches - raises with the candidates listed, because
    collecting another game's announcements would poison the patch timeline in a
    way no downstream check would catch.
    """
    wanted = title.strip().casefold()
    exact = [c for c in candidates if c["name"].strip().casefold() == wanted]
    if len(exact) == 1:
        return int(exact[0]["appid"])
    listed = ", ".join(f"{c['appid']}:{c['name']}" for c in candidates) or "<none>"
    raise CollectorError(
        f"cannot resolve a single Steam app id for {title!r}; candidates: {listed}. "
        "Pin one with --steam-appid or config/sources.yaml."
    )


def collect_steam(
    *,
    appid: int | None = None,
    title: str = STEAM_APP_TITLE,
    endpoint: str = STEAM_NEWS_ENDPOINT,
    page_size: int = STEAM_PAGE_SIZE,
    max_pages: int = STEAM_MAX_PAGES,
    fetcher: Fetcher | None = None,
) -> SteamCollectResult:
    """Page through the full announcement history, newest first.

    ISteamNews has no cursor; it takes an ``enddate`` upper bound instead. We
    walk backwards by setting ``enddate`` to one second before the oldest item
    of the previous page, and stop when a page comes back empty or repeats.
    """
    fetcher = fetcher or Fetcher(delay=1.0)
    candidates: list[dict[str, str]] = []
    if appid is None:
        candidates = resolve_steam_appid(title, fetcher=fetcher)
        appid = pick_steam_appid(candidates, title)
        log.info("resolved Steam appid %s for %r", appid, title)
    writer = SnapshotWriter(STEAM_SOURCE)
    enddate: int | None = None
    seen_gids: set[str] = set()
    total = 0
    page = 0

    while page < max_pages:
        params: dict[str, object] = {
            "appid": appid,
            "count": page_size,
            "maxlength": 0,  # 0 = full body, not a truncated blurb
            "format": "json",
        }
        if enddate is not None:
            params["enddate"] = enddate

        response = fetcher.get(endpoint, params=params)
        payload = response.json()
        items = payload.get("appnews", {}).get("newsitems", [])
        fresh = [item for item in items if item.get("gid") not in seen_gids]
        if not fresh:
            break

        writer.write(
            f"news-{page:03d}.json",
            response.content,
            url=response.url,
            status=response.status,
            content_type=response.content_type,
            meta={"appid": appid, "enddate": enddate, "items": len(items)},
        )
        seen_gids.update(item.get("gid", "") for item in items)
        total += len(fresh)
        page += 1

        oldest = min(int(item.get("date", 0)) for item in items)
        if oldest <= 0:
            break
        enddate = oldest - 1

    writer.seal(
        {
            "appid": appid,
            "endpoint": endpoint,
            "pages": page,
            "items": total,
            "appid_candidates": candidates,
        }
    )
    log.info("steam news snapshot: %s items over %s pages -> %s", total, page, writer.dir)
    return SteamCollectResult(str(writer.dir), page, total)


def collect_official(
    *,
    index_url: str,
    detail_link_selector: str = "a[href]",
    max_pages: int = 30,
    fetcher: Fetcher | None = None,
) -> str:
    """Snapshot the publisher's news index and every notice it links to.

    Kept intentionally generic: the collector records raw HTML and leaves every
    selector decision to ``build/patches.py``, so a site redesign is a parser
    fix against existing snapshots rather than lost data.
    """
    from bs4 import BeautifulSoup  # local import: only this collector needs it

    fetcher = fetcher or Fetcher(delay=1.5)
    writer = SnapshotWriter(OFFICIAL_SOURCE)

    index_response = fetcher.get(index_url)
    writer.write(
        "index-000.html",
        index_response.content,
        url=index_response.url,
        status=index_response.status,
        content_type=index_response.content_type,
    )

    soup = BeautifulSoup(index_response.text, "lxml")
    hrefs: list[str] = []
    for anchor in soup.select(detail_link_selector):
        href = anchor.get("href")
        if href and not href.startswith(("#", "javascript:", "mailto:")):
            absolute = urljoin(index_response.url, href)
            if absolute not in hrefs:
                hrefs.append(absolute)

    saved = 0
    for i, url in enumerate(hrefs[:max_pages]):
        try:
            detail = fetcher.get(url)
        except RuntimeError as exc:
            log.warning("skipping %s: %s", url, exc)
            continue
        writer.write(
            f"detail-{i:03d}.html",
            detail.content,
            url=detail.url,
            status=detail.status,
            content_type=detail.content_type,
        )
        saved += 1

    writer.seal({"index_url": index_url, "links_found": len(hrefs), "details_saved": saved})
    log.info("official news snapshot: %s details -> %s", saved, writer.dir)
    return str(writer.dir)
