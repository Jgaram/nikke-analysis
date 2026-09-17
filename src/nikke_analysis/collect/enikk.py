"""Collect Solo Raid top-N rankings from enikk.

enikk (https://enikk.app/soloraid) publishes the global Solo Raid leaderboard
with each ranker's five-unit team, which is the single richest public signal for
"what is actually winning right now". Rankings are also *perishable*: once a
season rotates the previous top-50 is no longer served, so the collector's job is
to snapshot aggressively and ask questions later.

Two entry points:

``probe``    - one-off reconnaissance. Walks the app's own asset graph looking
               for the JSON the page renders from, saves every response (404s
               included) and writes a report naming the endpoints that returned
               structured data. Run this once, then fill in config/enikk.yaml.

``collect``  - the routine path. Reads endpoint templates from config, expands
               them over the requested seasons/bosses, and snapshots the raw
               responses without interpreting them.

Keeping endpoint shape in config rather than code is the point: when enikk
changes its API, the fix is a config edit plus a re-run, and every previously
captured season stays parseable from its snapshot.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

from ..util.http import Fetcher
from ..util.snapshot import SnapshotWriter

log = logging.getLogger(__name__)

SOURCE = "enikk_soloraid"
PROBE_SOURCE = "enikk_probe"

DEFAULT_BASE_URL = "https://enikk.app"

# Paths worth trying blind on a modern SPA. Cheap, and a hit saves a lot of
# reverse-engineering. Ordered most- to least-likely.
CANDIDATE_PATHS: tuple[str, ...] = (
    "/api/soloraid",
    "/api/soloraid/ranker",
    "/api/soloraid/rankers",
    "/api/soloraid/seasons",
    "/api/seasons",
    "/api/raid/solo",
    "/api/rank/solo",
    "/soloraid",
    "/soloraid/ranker",
)

_NEXT_BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')
_SCRIPT_SRC_RE = re.compile(r'<script[^>]+src="([^"]+)"', re.IGNORECASE)
_JSON_URL_RE = re.compile(r'["\'](/(?:api|data)/[A-Za-z0-9_\-/\.]+)["\']')


def _looks_like_json(body: bytes, content_type: str) -> bool:
    if "json" in content_type.lower():
        return True
    head = body.lstrip()[:1]
    return head in (b"{", b"[")


@dataclass
class ProbeFinding:
    url: str
    status: int
    content_type: str
    bytes: int
    is_json: bool
    note: str = ""


@dataclass
class ProbeReport:
    base_url: str
    snapshot_dir: str
    next_build_id: str | None = None
    findings: list[ProbeFinding] = field(default_factory=list)

    @property
    def json_endpoints(self) -> list[ProbeFinding]:
        return [f for f in self.findings if f.is_json and 200 <= f.status < 300]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "snapshot_dir": self.snapshot_dir,
            "next_build_id": self.next_build_id,
            "json_endpoint_count": len(self.json_endpoints),
            "findings": [f.__dict__ for f in self.findings],
        }


def probe(
    *,
    base_url: str = DEFAULT_BASE_URL,
    entry_paths: Iterable[str] = ("/soloraid", "/soloraid/ranker"),
    candidate_paths: Iterable[str] = CANDIDATE_PATHS,
    fetcher: Fetcher | None = None,
    max_scripts: int = 12,
) -> ProbeReport:
    """Map out where the Solo Raid data actually comes from.

    Strategy, in order of how much it tells us:

    1. Fetch the rendered pages. If the app is Next.js, the embedded
       ``__NEXT_DATA__`` often *contains the rankings outright*, and always
       contains the ``buildId`` needed for ``/_next/data/<id>/<route>.json``.
    2. Scrape the page's own JS bundles for literal ``/api/...`` strings. This is
       how the real endpoint is usually found, since the app has to name it.
    3. Try the blind candidate list.

    Every response is snapshotted, so even a failed probe leaves evidence to read.
    """
    fetcher = fetcher or Fetcher(delay=1.0)
    writer = SnapshotWriter(PROBE_SOURCE)
    report = ProbeReport(base_url=base_url, snapshot_dir="")
    discovered: list[str] = []
    seen: set[str] = set()

    def record(url: str, note: str = "") -> bytes | None:
        if url in seen:
            return None
        seen.add(url)
        try:
            response = fetcher.get(url, allow_status={301, 302, 400, 401, 403, 404, 405, 500})
        except RuntimeError as exc:
            report.findings.append(ProbeFinding(url, 0, "", 0, False, f"error: {exc}"))
            return None
        is_json = _looks_like_json(response.content, response.content_type)
        safe = re.sub(r"[^A-Za-z0-9]+", "_", urlparse(url).path.strip("/") or "root")[:80]
        ext = "json" if is_json else "txt"
        writer.write(
            f"{len(seen):03d}-{safe}.{ext}",
            response.content,
            url=response.url,
            status=response.status,
            content_type=response.content_type,
        )
        report.findings.append(
            ProbeFinding(url, response.status, response.content_type, len(response.content), is_json, note)
        )
        return response.content

    # 1. entry pages
    for path in entry_paths:
        body = record(urljoin(base_url, path), note="entry page")
        if body is None:
            continue
        text = body.decode("utf-8", errors="replace")
        build_match = _NEXT_BUILD_ID_RE.search(text)
        if build_match and not report.next_build_id:
            report.next_build_id = build_match.group(1)
        for script in _SCRIPT_SRC_RE.findall(text)[:max_scripts]:
            discovered.append(urljoin(base_url, script))
        for api_path in set(_JSON_URL_RE.findall(text)):
            discovered.append(urljoin(base_url, api_path))

    # 2. the app's own bundles, mined for endpoint literals
    for script_url in list(dict.fromkeys(discovered))[:max_scripts]:
        body = record(script_url, note="bundle")
        if body is None:
            continue
        text = body.decode("utf-8", errors="replace")
        for api_path in sorted(set(_JSON_URL_RE.findall(text)))[:30]:
            record(urljoin(base_url, api_path), note="found in bundle")

    # 3. Next.js data routes, now that we may know the build id
    if report.next_build_id:
        for path in entry_paths:
            route = path.strip("/") or "index"
            record(
                urljoin(base_url, f"/_next/data/{report.next_build_id}/{route}.json"),
                note="next data route",
            )

    # 4. blind guesses
    for path in candidate_paths:
        record(urljoin(base_url, path), note="candidate")

    writer.seal(report.to_dict())
    report.snapshot_dir = str(writer.dir)
    (writer.dir / "probe-report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "probe finished: %s responses, %s JSON endpoints -> %s",
        len(report.findings),
        len(report.json_endpoints),
        writer.dir,
    )
    return report


def expand_template(template: str, values: Mapping[str, Any]) -> str:
    """``"/api/x?season={season}&boss={boss}"`` -> a concrete URL."""
    try:
        return template.format(**values)
    except KeyError as exc:
        raise ValueError(f"template {template!r} needs a value for {exc.args[0]!r}") from exc


def collect(
    *,
    base_url: str,
    endpoint_template: str,
    seasons: Iterable[int | str],
    bosses: Iterable[str] = ("",),
    extra_params: Mapping[str, Any] | None = None,
    fetcher: Fetcher | None = None,
) -> str:
    """Snapshot one response per (season, boss) pair.

    Nothing here knows what a ranking looks like; that contract lives in
    ``build/raids.py`` and config/enikk.yaml.
    """
    fetcher = fetcher or Fetcher(delay=1.5)
    writer = SnapshotWriter(SOURCE)
    requested = 0
    saved = 0

    for season in seasons:
        for boss in bosses:
            values = {"season": season, "boss": boss, **(extra_params or {})}
            url = urljoin(base_url, expand_template(endpoint_template, values))
            requested += 1
            try:
                response = fetcher.get(url)
            except RuntimeError as exc:
                log.warning("season=%s boss=%s -> %s", season, boss, exc)
                continue
            slug = re.sub(r"[^A-Za-z0-9]+", "-", f"s{season}-{boss}").strip("-")
            is_json = _looks_like_json(response.content, response.content_type)
            writer.write(
                f"{slug}.{'json' if is_json else 'html'}",
                response.content,
                url=response.url,
                status=response.status,
                content_type=response.content_type,
                meta={"season": str(season), "boss": str(boss)},
            )
            saved += 1

    writer.seal(
        {
            "base_url": base_url,
            "endpoint_template": endpoint_template,
            "requested": requested,
            "saved": saved,
        }
    )
    log.info("enikk snapshot: %s/%s responses -> %s", saved, requested, writer.dir)
    return str(writer.dir)
