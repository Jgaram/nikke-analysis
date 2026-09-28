"""Icons from blablalink, the official NIKKE companion site.

The charts draw a unit's face instead of its name, and an element or class icon
instead of the word. Three kinds of file, all public and unauthenticated:

``units/<unit_id>.webp``    the 128x128 face (``si_c<id>_00_s``) from the game
                            resource CDN. The roster's unit id *is* the game's
                            resource id (``010`` is Rapi), so no lookup table.
``elements/<element>.png``  the coloured hexagon the site shows for each element.
``classes/<class>.png``     the class glyph. One flat colour; charts tint it.

The CDN hides its paths: every directory becomes a short hash token and the file
name the md5 of the whole plain path. ``obfuscate`` is the site front end's own
``obfuscatedPath()``, so the plain path alone gives the URL and no browser is
needed (the same rule nikke-calc uses for its portraits).

Unlike the other collectors this writes to ``data/assets/icons/``, not a dated
snapshot under ``data/raw/``: an icon is a lookup, not evidence, and one file
per unit is all the charts need. Collection is incremental - a file already on
disk is never fetched again, so a run downloads only the units that are new
since the last one. A unit the CDN does not have yet (in the game files, not yet
on the site) is skipped rather than failed and tried again next run.
"""

from __future__ import annotations

import csv
import ctypes
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..paths import class_icon_path, element_icon_path, icons_dir, processed_dir, unit_icon_path
from ..util.http import Fetcher
from .base import CollectorError

log = logging.getLogger(__name__)

CDN_BASE = "https://sg-tools-cdn.blablalink.com"
SITE_IMAGES = "https://www.blablalink.com/assets/nikke/version/default/shiftysassets/images"

UNIT_ICON = "/character/si/si_c{rid:03d}_00_s.webp"

# The roster's spelling -> the site's file names.
ELEMENT_FILES = {
    "Fire": "icon-code-fire.png",
    "Water": "icon-code-water.png",
    "Wind": "icon-code-wind.png",
    "Iron": "icon-code-iron.png",
    "Electric": "icon-code-electronic.png",
}
CLASS_FILES = {
    "Attacker": "icon-job-attacker.png",
    "Defender": "icon-job-defender.png",
    "Supporter": "icon-job-supporter.png",
}

# The front end's LARGE_PRIMES, one per directory depth.
LARGE_PRIMES = (224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291)

# The CDN answers a missing object with one of these; the site's own asset
# path answers anything with its HTML shell, which the magic check catches.
NOT_THERE = {403, 404}


def _djb2(text: str, seed: int) -> int:
    """djb2 with JavaScript's 32-bit integer arithmetic."""
    value = seed
    for ch in text:
        value = ctypes.c_int32((value * 33 + ord(ch)) & 0xFFFFFFFF).value
    return value


def _dir_token(path: str, prime: int) -> str:
    r = (_djb2(path, prime) % prime + prime) % prime
    letters = chr(97 + (r // 26) % 26) + chr(97 + r % 26)
    return f"{letters}-{r % 99:02d}"


def obfuscate(path: str) -> str:
    """Plain CDN path -> the path the CDN actually serves."""
    plain = path.lstrip("/")
    segments = [s for s in plain.split("/") if s]
    out = []
    for depth, segment in enumerate(segments):
        if depth == len(segments) - 1:
            extension = ".".join(segment.split(".")[1:])
            out.append(f"{hashlib.md5(plain.encode()).hexdigest()}.{extension}")
        else:
            out.append(_dir_token(plain, LARGE_PRIMES[depth]))
    return "/".join(out)


def unit_icon_url(unit_id: str) -> str:
    return f"{CDN_BASE}/{obfuscate(UNIT_ICON.format(rid=int(unit_id)))}"


def site_image_url(name: str) -> str:
    return f"{SITE_IMAGES}/{name}"


def is_image(payload: bytes) -> bool:
    """PNG or WebP by magic number - never an HTML page served with status 200."""
    return payload.startswith(b"\x89PNG\r\n\x1a\n") or (payload[:4] == b"RIFF" and payload[8:12] == b"WEBP")


@dataclass
class IconResult:
    directory: str
    fetched: list[str] = field(default_factory=list)
    present: int = 0
    not_yet: list[str] = field(default_factory=list)


def roster_unit_ids(directory: Path | None = None) -> list[str]:
    path = (directory or processed_dir()) / "roster.csv"
    if not path.is_file():
        raise CollectorError(f"{path} missing; run `nikke build timeline` first")
    with path.open(encoding="utf-8", newline="") as handle:
        return [row["unit_id"] for row in csv.DictReader(handle) if row.get("unit_id", "").isdigit()]


def targets(unit_ids: Iterable[str], directory: Path) -> list[tuple[str, str, Path]]:
    """(label, url, destination) for every icon the charts can ask for."""
    out = [(f"element:{e}", site_image_url(name), element_icon_path(e, directory)) for e, name in ELEMENT_FILES.items()]
    out += [(f"class:{c}", site_image_url(name), class_icon_path(c, directory)) for c, name in CLASS_FILES.items()]
    out += [(unit_id, unit_icon_url(unit_id), unit_icon_path(unit_id, directory)) for unit_id in sorted(set(unit_ids))]
    return out


def collect_icons(
    unit_ids: Iterable[str] | None = None,
    *,
    directory: Path | None = None,
    fetcher: Fetcher | None = None,
    force: bool = False,
) -> IconResult:
    """Fetch every icon not on disk yet: each roster unit's face, every element and class.

    ``unit_ids`` defaults to every unit in ``roster.csv``. ``force`` re-fetches
    files that exist. Raises when an icon could not be fetched for any reason
    other than the CDN not having it yet - after trying all the others.
    """
    target_dir = directory or icons_dir()
    ids = list(unit_ids) if unit_ids is not None else roster_unit_ids()
    fetcher = fetcher or Fetcher(delay=0.1)
    result = IconResult(directory=str(target_dir))
    failed: list[str] = []
    for label, url, path in targets(ids, target_dir):
        if path.is_file() and not force:
            result.present += 1
            continue
        try:
            response = fetcher.get(url, allow_status=NOT_THERE)
        except Exception as exc:  # retries exhausted, a changed host
            failed.append(f"{label}: {exc}")
            continue
        if response.status in NOT_THERE:
            # Only a unit can be "not there yet"; a missing element or class
            # icon means the site moved its assets.
            if ":" in label:
                failed.append(f"{label}: {url} -> HTTP {response.status}")
            else:
                result.not_yet.append(label)
            continue
        if not is_image(response.content):
            failed.append(f"{label}: {url} answered {response.content_type or 'something'} that is not an image")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        partial.write_bytes(response.content)
        partial.replace(path)
        result.fetched.append(label)
    log.info("icons: %s fetched, %s already present, %s not on the CDN yet -> %s",
             len(result.fetched), result.present, len(result.not_yet), target_dir)
    if failed:
        raise CollectorError(f"{len(failed)} icon(s) failed: " + "; ".join(failed[:5]))
    return result
