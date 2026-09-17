"""A small, polite HTTP client shared by every collector.

Deliberately thin: retries, a real User-Agent, a request delay, and an on-disk
response cache. Anything fancier belongs in the collector that needs it.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "nikke-analysis/0.1 (+https://github.com/jgaram/nikke-analysis) "
    "research scraper; contact via repository issues"
)

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    content_type: str
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class Fetcher:
    """Synchronous fetcher with backoff, rate limiting and an optional cache.

    ``delay`` is applied *between* requests to the same Fetcher, which keeps us
    well under any sane rate limit for the small number of pages this project
    touches (a few hundred per full backfill).
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_UA,
        delay: float = 1.0,
        timeout: float = 30.0,
        max_retries: int = 4,
        cache_dir: Path | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "ko,en;q=0.8"})
        if headers:
            self.session.headers.update(dict(headers))
        self._last_request = 0.0

    def _cache_path(self, url: str, params: Mapping[str, Any] | None) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(f"{url}|{sorted((params or {}).items())}".encode()).hexdigest()
        return self.cache_dir / f"{key}.bin"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_status: set[int] | None = None,
    ) -> Response:
        """GET with retry/backoff.

        ``allow_status`` lists non-2xx codes the caller wants returned instead of
        raised - the API probe uses it to record 404s as evidence.
        """
        cache_path = self._cache_path(url, params)
        if cache_path is not None and cache_path.exists():
            log.debug("cache hit %s", url)
            return Response(url, 200, cache_path.read_bytes(), "", {})

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, headers=dict(headers or {}), timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                wait = 2.0**attempt
                log.warning("GET %s failed (%s); retry in %.0fs", url, exc, wait)
                time.sleep(wait)
                continue

            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries - 1:
                wait = 2.0**attempt
                log.warning("GET %s -> %s; retry in %.0fs", url, resp.status_code, wait)
                time.sleep(wait)
                continue

            ok = resp.ok or (allow_status is not None and resp.status_code in allow_status)
            if not ok:
                raise RuntimeError(f"GET {url} -> HTTP {resp.status_code}")

            out = Response(
                url=resp.url,
                status=resp.status_code,
                content=resp.content,
                content_type=resp.headers.get("Content-Type", ""),
                headers=dict(resp.headers),
            )
            if cache_path is not None and resp.ok:
                cache_path.write_bytes(resp.content)
            return out

        raise RuntimeError(f"GET {url} failed after {self.max_retries} attempts") from last_error
