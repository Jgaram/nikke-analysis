"""Turn update announcements into a patch timeline, an event list, and the
release date of every unit.

Three outputs:

``patches.csv``       one row per announcement: id, date, title, url, kind.
``patch_events.csv``  one row per event/banner section found inside a patch.
``unit_releases.csv`` one row per unit: the patch that introduced it.

The release dates are the reason this module exists. Everything downstream
conditions on "was this unit available in this season", and getting that from the
announcement that introduced the unit is both accurate and, crucially,
*automatic* - a new patch drops, the collector picks it up, and the roster gains
a high-confidence date without anyone editing a table.

How a release is detected, deterministically:

* A unit is "mentioned" in a patch when one of its known spellings appears in the
  text (resolved through the alias table, so ``레드 후드`` and ``Red Hood`` are the
  same unit).
* Announcements are walked oldest-first; the *first* patch mentioning a unit is
  its candidate release.
* That candidate is promoted to a confirmed release when the surrounding text
  also carries new-unit or recruitment wording (``New Nikke``, ``신규 니케``,
  ``Pick Up``...). Otherwise it stays a candidate and is reported as such.

No fuzzy matching, no model: a spelling either resolves or it is listed as
unresolved for a human to add to the alias table.
"""

from __future__ import annotations

import csv
import html
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..paths import processed_dir
from ..util.names import NameIndex, build_name_index, normalize_name
from ..util.snapshot import SnapshotRun, list_runs

log = logging.getLogger(__name__)

PATCHES_CSV = "patches.csv"
EVENTS_CSV = "patch_events.csv"
RELEASES_CSV = "unit_releases.csv"
ALIAS_CSV = "unit_aliases.csv"

# Keyword tables. Deliberately multilingual and deliberately data, not code:
# announcements are published in Korean, English and Japanese and the wording is
# stable across years.
NEW_UNIT_MARKERS = (
    "new nikke",
    "new character",
    "신규 니케",
    "신규 캐릭터",
    "新キャラクター",
    "新ニケ",
    "pick up",
    "pick-up",
    "픽업",
    "ピックアップ",
    "recruit",
    "모집",
)

PATCH_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("maintenance", ("maintenance", "점검", "メンテナンス")),
    ("patchnote", ("patch note", "update note", "업데이트 안내", "패치 노트", "アップデート")),
    ("event", ("event", "이벤트", "イベント")),
    ("banner", ("pick up", "pick-up", "픽업", "ピックアップ", "recruit", "모집")),
    ("devnote", ("developer", "개발자", "開発者")),
)

EVENT_SECTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("banner", ("pick up", "픽업", "ピックアップ", "recruit", "모집")),
    ("story_event", ("event", "이벤트", "イベント")),
    ("raid", ("raid", "레이드", "レイド")),
    ("arena", ("arena", "아레나", "アリーナ")),
    ("shop", ("shop", "상점", "ショップ", "package", "패키지")),
    ("balance", ("balance", "밸런스", "バランス", "adjust", "조정")),
)

_TAG_RE = re.compile(r"<[^>]+>")
_BBCODE_RE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")
_WS_RE = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n{3,}")


@dataclass
class Patch:
    patch_id: str
    date: str
    timestamp: int
    title: str
    url: str
    source: str
    kind: str
    body_chars: int


@dataclass
class PatchEvent:
    patch_id: str
    date: str
    section: str
    category: str


@dataclass
class UnitRelease:
    unit_id: str
    release_date: str
    patch_id: str
    patch_title: str
    status: str  # "confirmed" when new-unit wording was present, else "candidate"
    matched_alias: str


# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------

def clean_body(raw: str) -> str:
    """Steam announcements mix HTML and BBCode; strip both to plain text."""
    text = html.unescape(raw or "")
    text = _TAG_RE.sub("\n", text)
    text = _BBCODE_RE.sub("\n", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def classify(title: str, body: str) -> str:
    haystack = f"{title}\n{body[:2000]}".casefold()
    for kind, markers in PATCH_KIND_RULES:
        if any(marker in haystack for marker in markers):
            return kind
    return "other"


def section_titles(body: str, *, max_len: int = 120) -> list[str]:
    """Short standalone lines, which is how these announcements mark sections."""
    out: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip(" \t*-–—•#[]")
        if 2 <= len(stripped) <= max_len and not stripped.endswith((".", "다.", "。")):
            out.append(stripped)
    return out


def categorise_section(title: str) -> str | None:
    lowered = title.casefold()
    for category, markers in EVENT_SECTION_RULES:
        if any(marker in lowered for marker in markers):
            return category
    return None


def has_new_unit_marker(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in NEW_UNIT_MARKERS)


# --------------------------------------------------------------------------
# parsing snapshots
# --------------------------------------------------------------------------

def parse_steam_run(run: SnapshotRun) -> list[dict[str, Any]]:
    """Flatten every ISteamNews page in a run into announcement records."""
    items: dict[str, dict[str, Any]] = {}
    for filename, payload in run.iter_files(".json"):
        try:
            document = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            log.warning("bad JSON in %s: %s", filename, exc)
            continue
        for item in document.get("appnews", {}).get("newsitems", []):
            gid = str(item.get("gid", "")) or f"{filename}:{len(items)}"
            body = clean_body(item.get("contents", ""))
            timestamp = int(item.get("date", 0))
            items[gid] = {
                "patch_id": f"steam-{gid}",
                "timestamp": timestamp,
                "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
                if timestamp
                else "",
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")),
                "source": "steam",
                "body": body,
            }
    return sorted(items.values(), key=lambda r: (r["timestamp"], r["patch_id"]))


def parse_official_run(run: SnapshotRun) -> list[dict[str, Any]]:
    """Parse saved news HTML into the same record shape as the Steam feed.

    Kept generic on purpose - it reads the document title and any ISO-ish date in
    the page, because every publisher redesign changes the class names but not
    those two things. A site-specific parser can be added later without
    invalidating the snapshots already collected.
    """
    from bs4 import BeautifulSoup

    records: list[dict[str, Any]] = []
    for filename, payload in run.iter_files(".html"):
        if filename.startswith("index-"):
            continue
        soup = BeautifulSoup(payload.decode("utf-8", errors="replace"), "lxml")
        title = (soup.title.get_text(strip=True) if soup.title else "") or filename
        body = clean_body(soup.get_text("\n"))
        date = ""
        match = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", body)
        if match:
            year, month, day = (int(g) for g in match.groups())
            try:
                date = datetime(year, month, day).date().isoformat()
            except ValueError:
                date = ""
        entry = next((e for e in run.entries if e["filename"] == filename), {})
        records.append(
            {
                "patch_id": f"official-{Path(filename).stem}",
                "timestamp": int(datetime.fromisoformat(date).timestamp()) if date else 0,
                "date": date,
                "title": title,
                "url": entry.get("url", ""),
                "source": "official",
                "body": body,
            }
        )
    return sorted(records, key=lambda r: (r["timestamp"], r["patch_id"]))


# --------------------------------------------------------------------------
# unit release extraction
# --------------------------------------------------------------------------

def load_alias_index(path: Path | None = None) -> NameIndex | None:
    """Build a name index from ``data/processed/unit_aliases.csv``."""
    target = path or (processed_dir() / ALIAS_CSV)
    if not target.is_file():
        return None
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return None
    by_unit: dict[str, dict[str, str]] = {}
    aliases: list[dict[str, str]] = []
    for row in rows:
        unit_id = row["unit_id"]
        record = by_unit.setdefault(unit_id, {"unit_id": unit_id})
        if row.get("kind") == "full" and row.get("language"):
            record[f"name_{row['language']}"] = row["alias"]
        else:
            aliases.append({"unit_id": unit_id, "alias": row["alias"]})
    try:
        return build_name_index(list(by_unit.values()), aliases=aliases)
    except ValueError as exc:
        log.warning("alias index rejected: %s", exc)
        return build_name_index(list(by_unit.values()))


def _alias_lookup(index: NameIndex) -> list[tuple[str, str]]:
    """Every alias as ``(normalized, unit_id)``, longest first.

    Longest-first matters: ``Rapi: Red Hood`` must win over ``Rapi`` when both
    appear in the same sentence, otherwise every Red Hood banner would be
    credited to the base unit.
    """
    combined = {**index.secondary, **index.primary}
    return sorted(combined.items(), key=lambda kv: len(kv[0]), reverse=True)


def find_units(text: str, alias_pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Which units are named in this text. Returns ``{unit_id: matched_alias}``.

    Matching runs against the normalised form of both sides, so spacing and
    punctuation differences between sources stop mattering. Short aliases (under
    three characters after folding) are skipped - they produce false hits inside
    unrelated words.
    """
    haystack = normalize_name(text)
    found: dict[str, str] = {}
    for alias, unit_id in alias_pairs:
        if len(alias) < 3 or unit_id in found:
            continue
        if alias in haystack:
            found[unit_id] = alias
    return found


def extract_releases(
    records: Iterable[dict[str, Any]], index: NameIndex
) -> tuple[list[UnitRelease], dict[str, Any]]:
    """Walk announcements oldest-first and record each unit's first appearance."""
    alias_pairs = _alias_lookup(index)
    first_seen: OrderedDict[str, UnitRelease] = OrderedDict()
    scanned = 0

    for record in sorted(records, key=lambda r: (r["timestamp"], r["patch_id"])):
        if not record.get("date"):
            continue
        scanned += 1
        blob = f"{record['title']}\n{record['body']}"
        new_unit_context = has_new_unit_marker(blob)
        for unit_id, alias in find_units(blob, alias_pairs).items():
            existing = first_seen.get(unit_id)
            if existing is None:
                first_seen[unit_id] = UnitRelease(
                    unit_id=unit_id,
                    release_date=record["date"],
                    patch_id=record["patch_id"],
                    patch_title=record["title"],
                    status="confirmed" if new_unit_context else "candidate",
                    matched_alias=alias,
                )
            elif existing.status == "candidate" and new_unit_context:
                # An earlier passing mention is weaker evidence than the first
                # announcement that actually introduces the unit.
                first_seen[unit_id] = UnitRelease(
                    unit_id=unit_id,
                    release_date=record["date"],
                    patch_id=record["patch_id"],
                    patch_title=record["title"],
                    status="confirmed",
                    matched_alias=alias,
                )

    releases = sorted(first_seen.values(), key=lambda r: (r.release_date, r.unit_id))
    stats = {
        "announcements_scanned": scanned,
        "units_found": len(releases),
        "confirmed": sum(1 for r in releases if r.status == "confirmed"),
        "candidate": sum(1 for r in releases if r.status == "candidate"),
    }
    return releases, stats


def load_unit_releases(path: Path | None = None) -> dict[str, str]:
    """``{unit_id: release_date}`` for confirmed releases, for the roster build."""
    target = path or (processed_dir() / RELEASES_CSV)
    if not target.is_file():
        return {}
    with target.open(encoding="utf-8", newline="") as handle:
        return {
            row["unit_id"]: row["release_date"]
            for row in csv.DictReader(handle)
            if row.get("status") == "confirmed" and row.get("release_date")
        }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build(*, out_dir: Path | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for run in list_runs("patchnotes_steam"):
        records.extend(parse_steam_run(run))
    for run in list_runs("patchnotes_official"):
        records.extend(parse_official_run(run))

    if not records:
        raise RuntimeError(
            "no patch-note snapshots found; run `nikke collect patchnotes` first "
            "(needs the announcement host allowlisted - see docs/network-policy.md)"
        )

    # De-duplicate across runs, keeping the longest body for each announcement.
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        existing = by_id.get(record["patch_id"])
        if existing is None or len(record["body"]) > len(existing["body"]):
            by_id[record["patch_id"]] = record
    records = sorted(by_id.values(), key=lambda r: (r["timestamp"], r["patch_id"]))

    patches = [
        Patch(
            patch_id=r["patch_id"],
            date=r["date"],
            timestamp=r["timestamp"],
            title=r["title"],
            url=r["url"],
            source=r["source"],
            kind=classify(r["title"], r["body"]),
            body_chars=len(r["body"]),
        )
        for r in records
    ]

    events: list[PatchEvent] = []
    for record in records:
        seen: set[str] = set()
        for section in section_titles(record["body"]):
            category = categorise_section(section)
            if category and section not in seen:
                seen.add(section)
                events.append(
                    PatchEvent(
                        patch_id=record["patch_id"],
                        date=record["date"],
                        section=section,
                        category=category,
                    )
                )

    index = load_alias_index()
    releases: list[UnitRelease] = []
    release_stats: dict[str, Any] = {"skipped": "no alias table; run `nikke build roster` first"}
    if index is not None:
        releases, release_stats = extract_releases(records, index)

    target_dir = out_dir or processed_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(target_dir / PATCHES_CSV, [asdict(p) for p in patches])
    _write_csv(target_dir / EVENTS_CSV, [asdict(e) for e in events])
    _write_csv(target_dir / RELEASES_CSV, [asdict(r) for r in releases])

    summary = {
        "patches": len(patches),
        "kinds": {kind: sum(1 for p in patches if p.kind == kind) for kind in {p.kind for p in patches}},
        "events": len(events),
        "releases": release_stats,
        "date_range": [patches[0].date, patches[-1].date] if patches else [],
        "out_dir": str(target_dir),
    }
    log.info("patches built: %s announcements -> %s", len(patches), target_dir)
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
