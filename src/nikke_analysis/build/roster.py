"""Build the unit roster: one row per Nikke, with names, attributes and a date.

The roster is the spine of the whole project. Pick rates are meaningless without
it, because a unit that did not exist yet must not be counted as "not picked" -
it has to be excluded from the denominator. That makes the release date a
load-bearing number rather than a nice-to-have, so this module is explicit about
where each date came from and how much to trust it.

Date provenance, strongest first:

``manual``      an entry in data/manual/release_overrides.csv, with a reason.
``patchnote``   the update that announced the unit (see build/patches.py).
``datafile``    the ``dateAdded`` field from the nikke-utils dataset.

``datafile`` is the weakest by a wide margin: it records when a unit turned up in
the game's data, which for launch units is a beta build months before release
(Rapi reads 2022-04-11, half a year before the game shipped) and for later units
is usually the datamine, one or two patches early. It is a placeholder that keeps
the pipeline runnable, and every row using it is flagged ``low`` confidence so
the gap is visible in the output rather than buried.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..paths import manual_dir, processed_dir
from ..util.names import normalize_unit_id, variant_suffix
from ..util.snapshot import SnapshotRun, latest_run
from .jsobj import extract_array_literal

log = logging.getLogger(__name__)

ROSTER_CSV = "roster.csv"
ALIAS_CSV = "unit_aliases.csv"
OVERRIDES_CSV = "release_overrides.csv"

_NAME_KEY_RE = re.compile(r"^(\d+)_name$")
_FILENAME_ID_RE = re.compile(r"^\[(\d+)\]")

# The game shipped globally on this date, so nothing can have released before
# it. The data-file dates for the launch roster are beta-build dates from April
# 2022, seven months early; clamping them to launch does not make them right, but
# it removes an error large enough to distort "how long has this unit existed".
GLOBAL_LAUNCH_DATE = "2022-11-04"

CONFIDENCE_BY_SOURCE = {
    "manual": "high",
    "patchnote": "high",
    "datafile": "low",
    "datafile_floored": "low",
    "": "none",
}


@dataclass
class RosterRow:
    unit_id: str
    name_en: str = ""
    name_ko: str = ""
    name_ja: str = ""
    rarity: str = ""
    burst: str = ""
    element: str = ""
    manufacturer: str = ""
    unit_class: str = ""
    weapon: str = ""
    squad: str = ""
    is_variant: int = 0
    base_name_en: str = ""
    datafile_added: str = ""
    release_date: str = ""
    release_date_source: str = ""
    release_date_confidence: str = "none"
    in_gamefiles: int = 0
    in_nikkeutils: int = 0


# --------------------------------------------------------------------------
# parsing individual sources
# --------------------------------------------------------------------------

def parse_gamefiles_role(filename: str, payload: bytes) -> dict[str, str] | None:
    """Parse one ``roledata/[NNN] Name.yaml`` into ids and localised names.

    The unit id comes from the filename's ``[NNN]`` prefix, which is the only
    part of these files guaranteed to be present; the in-file key drops leading
    zeros (``16_name`` for unit ``016``) so it is used only as a cross-check.
    """
    stem = Path(filename).name
    match = _FILENAME_ID_RE.match(stem)
    if not match:
        return None
    unit_id = normalize_unit_id(match.group(1))

    try:
        document = yaml.safe_load(payload.decode("utf-8"))
    except yaml.YAMLError as exc:
        log.warning("unparseable roledata file %s: %s", stem, exc)
        return None
    if not isinstance(document, dict):
        return None

    names: dict[str, str] = {}
    for key, value in document.items():
        key_match = _NAME_KEY_RE.match(str(key))
        if key_match and isinstance(value, dict):
            if normalize_unit_id(key_match.group(1)) != unit_id:
                continue
            names = {lang: str(text) for lang, text in value.items() if text}
            break
    if not names:
        return None

    return {
        "unit_id": unit_id,
        "name_en": names.get("en", ""),
        "name_ko": names.get("ko", ""),
        "name_ja": names.get("ja", ""),
    }


def parse_gamefiles_run(run: SnapshotRun) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for filename, payload in run.iter_files():
        if not filename.endswith((".yaml", ".yml")):
            continue
        parsed = parse_gamefiles_role(filename, payload)
        if parsed:
            rows.append(parsed)
    rows.sort(key=lambda r: r["unit_id"])
    return rows


def parse_nikkeutils(source_js: str) -> list[dict[str, Any]]:
    """Normalise the nikke-utils character table onto our field names."""
    out: list[dict[str, Any]] = []
    for row in extract_array_literal(source_js, "characters"):
        raw_id = row.get("character_id") or row.get("id")
        try:
            unit_id = normalize_unit_id(str(raw_id))
        except ValueError:
            log.warning("skipping nikke-utils row with unusable id %r", raw_id)
            continue
        out.append(
            {
                "unit_id": unit_id,
                "name_en": str(row.get("name", "")),
                "rarity": str(row.get("rarity", "")),
                "burst": str(row.get("burst", "")),
                "element": str(row.get("element", "")),
                "manufacturer": str(row.get("manufacturer", "")),
                "unit_class": str(row.get("class", "")),
                "weapon": str(row.get("weapon", "")),
                "squad": str(row.get("squad", "")),
                "datafile_added": str(row.get("dateAdded", "")),
            }
        )
    out.sort(key=lambda r: r["unit_id"])
    return out


def parse_nikkeutils_run(run: SnapshotRun) -> list[dict[str, Any]]:
    return parse_nikkeutils(run.read_text("characters.js"))


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------

def load_release_overrides(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Hand-curated release dates. One row per unit, each with a reason."""
    target = path or (manual_dir() / OVERRIDES_CSV)
    if not target.is_file():
        return {}
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row.get("unit_id") or not row.get("release_date"):
            continue
        out[normalize_unit_id(row["unit_id"])] = {
            "release_date": row["release_date"].strip(),
            "reason": (row.get("reason") or "").strip(),
        }
    return out


def merge_roster(
    gamefiles: Iterable[dict[str, str]],
    nikkeutils: Iterable[dict[str, Any]],
    *,
    overrides: dict[str, dict[str, str]] | None = None,
    patch_releases: dict[str, str] | None = None,
) -> list[RosterRow]:
    """Full outer join on ``unit_id``, then resolve one release date per unit.

    A unit present in only one source is still emitted: units appear in the game
    files before the community tables catch up, and dropping them would make the
    roster silently lag every new release.
    """
    overrides = overrides or {}
    patch_releases = patch_releases or {}

    merged: dict[str, RosterRow] = {}
    for row in gamefiles:
        unit = merged.setdefault(row["unit_id"], RosterRow(unit_id=row["unit_id"]))
        unit.name_en = row.get("name_en") or unit.name_en
        unit.name_ko = row.get("name_ko") or unit.name_ko
        unit.name_ja = row.get("name_ja") or unit.name_ja
        unit.in_gamefiles = 1

    for row in nikkeutils:
        unit = merged.setdefault(row["unit_id"], RosterRow(unit_id=row["unit_id"]))
        # Game files win on names: they are the game's own localisation table.
        unit.name_en = unit.name_en or row.get("name_en", "")
        for attribute in (
            "rarity",
            "burst",
            "element",
            "manufacturer",
            "unit_class",
            "weapon",
            "squad",
            "datafile_added",
        ):
            if row.get(attribute):
                setattr(unit, attribute, row[attribute])
        unit.in_nikkeutils = 1

    for unit_id, unit in merged.items():
        display = unit.name_en or unit.name_ko
        suffix = variant_suffix(display)
        unit.is_variant = 1 if suffix else 0
        unit.base_name_en = display.split(":")[0].strip() if suffix else display

        if unit_id in overrides:
            unit.release_date = overrides[unit_id]["release_date"]
            unit.release_date_source = "manual"
        elif unit_id in patch_releases:
            unit.release_date = patch_releases[unit_id]
            unit.release_date_source = "patchnote"
        elif unit.datafile_added:
            if unit.datafile_added < GLOBAL_LAUNCH_DATE:
                unit.release_date = GLOBAL_LAUNCH_DATE
                unit.release_date_source = "datafile_floored"
            else:
                unit.release_date = unit.datafile_added
                unit.release_date_source = "datafile"
        else:
            unit.release_date = ""
            unit.release_date_source = ""
        unit.release_date_confidence = CONFIDENCE_BY_SOURCE.get(unit.release_date_source, "none")

    return [merged[key] for key in sorted(merged)]


def build_alias_rows(roster: Iterable[RosterRow]) -> list[dict[str, str]]:
    """Every spelling we know for each unit, as a reviewable table.

    Emitted so that a name appearing in ranking data can be traced to a unit by
    reading a CSV, without running the resolver.
    """
    rows: list[dict[str, str]] = []
    for unit in roster:
        for field_name, language in (("name_en", "en"), ("name_ko", "ko"), ("name_ja", "ja")):
            value = getattr(unit, field_name)
            if value:
                rows.append(
                    {"unit_id": unit.unit_id, "alias": value, "language": language, "kind": "full"}
                )
                suffix = variant_suffix(value)
                if suffix:
                    rows.append(
                        {
                            "unit_id": unit.unit_id,
                            "alias": suffix,
                            "language": language,
                            "kind": "variant_suffix",
                        }
                    )
    return rows


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build(
    *,
    gamefiles_run: SnapshotRun | None = None,
    nikkeutils_run: SnapshotRun | None = None,
    out_dir: Path | None = None,
    patch_releases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build roster.csv and unit_aliases.csv from the newest snapshots."""
    gamefiles_run = gamefiles_run or latest_run("roster_gamefiles")
    nikkeutils_run = nikkeutils_run or latest_run("roster_nikkeutils")
    if gamefiles_run is None and nikkeutils_run is None:
        raise RuntimeError("no roster snapshots found; run `nikke collect roster` first")

    gamefile_rows = parse_gamefiles_run(gamefiles_run) if gamefiles_run else []
    nikkeutils_rows = parse_nikkeutils_run(nikkeutils_run) if nikkeutils_run else []
    roster = merge_roster(
        gamefile_rows,
        nikkeutils_rows,
        overrides=load_release_overrides(),
        patch_releases=patch_releases,
    )

    target_dir = out_dir or processed_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    roster_path = target_dir / ROSTER_CSV
    alias_path = target_dir / ALIAS_CSV

    fieldnames = list(asdict(roster[0]).keys()) if roster else [f.name for f in RosterRow.__dataclass_fields__.values()]
    with roster_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for unit in roster:
            writer.writerow(asdict(unit))

    alias_rows = build_alias_rows(roster)
    with alias_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["unit_id", "alias", "language", "kind"])
        writer.writeheader()
        writer.writerows(alias_rows)

    summary = {
        "units": len(roster),
        "from_gamefiles": sum(u.in_gamefiles for u in roster),
        "from_nikkeutils": sum(u.in_nikkeutils for u in roster),
        "variants": sum(u.is_variant for u in roster),
        "release_date_confidence": {
            level: sum(1 for u in roster if u.release_date_confidence == level)
            for level in ("high", "low", "none")
        },
        "roster_csv": str(roster_path),
        "alias_csv": str(alias_path),
        "alias_rows": len(alias_rows),
    }
    log.info("roster built: %s units -> %s", len(roster), roster_path)
    return summary
