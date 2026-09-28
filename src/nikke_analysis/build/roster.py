"""Build the unit roster: one row per Nikke, with names, attributes and a date.

The roster is the spine of the whole project. "Which units existed at the time"
is meaningless without it, and pick rates later on are too, because a unit that
did not exist yet must not be counted as "not picked". That makes the release
date a load-bearing number rather than a nice-to-have, so this module is
explicit about where each date came from and how much to trust it.

Date provenance, strongest first:

``manual``      an entry in data/manual/release_overrides.csv, with a reason.
``patchnote``   the start of the unit's first recruitment window in the update
                notice that introduced it (see build/releases.py).
``launch``      no notice ever introduced the unit and it was already in the
                game's data before the global launch: it shipped with the game.
                Only claimed when the notice history reaches back past launch.
``datafile``    the ``dateAdded`` field from the nikke-utils dataset.

``datafile`` is the weakest by a wide margin: it records when a unit turned up in
the game's data, which for launch units is a beta build months before release
(Rapi reads 2022-04-11, half a year before the game shipped) and for later units
is usually the datamine, one or two patches early. Every row using it is flagged
``low`` confidence so the gap is visible in the output rather than buried.

Names come from the game files, attributes from nikke-utils with enikk's copy of
the game tables filling whatever nikke-utils has not caught up with yet - a unit
released this week has a row, a name and its attributes on the next refresh.

``extra_elements`` is the one attribute no source has: the element(s) whose
weakness advantage (우월 코드) a unit's skill adds to its own, kept by hand in
data/manual/extra_elements.csv. Such a unit is tiered in each of its elements.

``treasure_at`` is when the unit's treasure (애장품) came out, from the update
notices (build/treasures.py). From then on it plays with it, and its tiers are
reckoned on the seasons since (analyze/tiers.py).
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
from ..timeline import parse_element
from ..util.names import NameIndex, build_name_index, normalize_name, normalize_unit_id, variant_suffix
from ..util.snapshot import SnapshotRun, latest_run
from .jsobj import extract_array_literal

log = logging.getLogger(__name__)

ROSTER_CSV = "roster.csv"
ALIAS_CSV = "unit_aliases.csv"
OVERRIDES_CSV = "release_overrides.csv"
MANUAL_ALIAS_CSV = "unit_aliases.csv"
EXTRA_ELEMENTS_CSV = "extra_elements.csv"

_NAME_KEY_RE = re.compile(r"^(\d+)_name$")
_DESCRIPTION_KEY_RE = re.compile(r"^c?(\d+)_description$")
_FILENAME_ID_RE = re.compile(r"^\[(\d+)\]")

# Collaboration units carry their full name in the unit description ("풀네임은
# 스즈하라 사쿠라."), and that full name is what update notices call them.
_FULL_NAME_PATTERNS = {
    "ko": re.compile(r"(?:풀네임|본명)[은는]\s*([^.。\n]+?)\s*[.。]"),
    "en": re.compile(r"(?:full|real) name is\s+([^.\n]+?)\s*\.", re.IGNORECASE),
    "ja": re.compile(r"(?:フルネーム|本名)は\s*([^。\n]+?)\s*。"),
}

# The game shipped globally on this date, so nothing can have released before
# it. The data-file dates for the launch roster are beta-build dates from April
# 2022, seven months early; clamping them to launch does not make them right, but
# it removes an error large enough to distort "how long has this unit existed".
GLOBAL_LAUNCH_DATE = "2022-11-04"

CONFIDENCE_BY_SOURCE = {
    "manual": "high",
    "patchnote": "high",
    "launch": "medium",
    "datafile": "low",
    "datafile_floored": "low",
    "": "none",
}

ATTRIBUTES = ("rarity", "burst", "element", "manufacturer", "unit_class", "weapon", "squad")


@dataclass
class RosterRow:
    unit_id: str
    name_en: str = ""
    name_ko: str = ""
    name_ja: str = ""
    rarity: str = ""
    burst: str = ""
    element: str = ""
    extra_elements: str = ""  # elements its skill adds, "Iron" or "Iron;Water"
    manufacturer: str = ""
    unit_class: str = ""
    weapon: str = ""
    squad: str = ""
    is_variant: int = 0
    base_name_en: str = ""
    full_name_en: str = ""
    full_name_ko: str = ""
    full_name_ja: str = ""
    datafile_added: str = ""
    release_date: str = ""
    release_at: str = ""
    release_date_source: str = ""
    release_date_confidence: str = "none"
    treasure_at: str = ""  # when its treasure (애장품) came out; empty while it has none
    in_gamefiles: int = 0
    in_nikkeutils: int = 0
    in_enikk: int = 0


# --------------------------------------------------------------------------
# parsing individual sources
# --------------------------------------------------------------------------

def parse_gamefiles_role(filename: str, payload: bytes) -> dict[str, str] | None:
    """Parse one ``roledata/[NNN] Name.yaml`` into ids and localised names.

    The unit id comes from the filename's ``[NNN]`` prefix, which is the only
    part of these files guaranteed to be present; the in-file key drops leading
    zeros (``16_name`` for unit ``016``) so it is used only as a cross-check.
    A full name stated in the unit's description is returned too, as
    ``full_name_<lang>``, when there is one.
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
    descriptions: dict[str, str] = {}
    for key, value in document.items():
        if not isinstance(value, dict):
            continue
        key_match = _NAME_KEY_RE.match(str(key))
        if key_match and not names and normalize_unit_id(key_match.group(1)) == unit_id:
            names = {lang: str(text) for lang, text in value.items() if text}
            continue
        desc_match = _DESCRIPTION_KEY_RE.match(str(key))
        if desc_match and not descriptions and normalize_unit_id(desc_match.group(1)) == unit_id:
            descriptions = {lang: str(text) for lang, text in value.items() if text}
    if not names:
        return None

    row = {
        "unit_id": unit_id,
        "name_en": names.get("en", ""),
        "name_ko": names.get("ko", ""),
        "name_ja": names.get("ja", ""),
    }
    for lang, pattern in _FULL_NAME_PATTERNS.items():
        found = pattern.search(descriptions.get(lang, ""))
        if found and normalize_name(found.group(1)) != normalize_name(row[f"name_{lang}"]):
            row[f"full_name_{lang}"] = found.group(1).strip()
    return row


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


def load_extra_elements(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Elements a unit's skill adds, from data/manual/extra_elements.csv (``unit_id``,
    ``element``, ``reason``; one row per unit and element, the element in English
    or Korean). A row naming no unit or no element is skipped with a warning."""
    target = path or (manual_dir() / EXTRA_ELEMENTS_CSV)
    if not target.is_file():
        return {}
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    out: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if not row.get("unit_id") or not row.get("element"):
            continue
        try:
            unit_id = normalize_unit_id(row["unit_id"])
            element = parse_element(row["element"])
        except (LookupError, ValueError) as exc:
            log.warning("%s: %s", target.name, exc)
            continue
        if element not in out.get(unit_id, ()):
            out[unit_id] = out.get(unit_id, ()) + (element,)
    return out


def merge_roster(
    gamefiles: Iterable[dict[str, str]],
    nikkeutils: Iterable[dict[str, Any]],
    *,
    overrides: dict[str, dict[str, str]] | None = None,
    extra_elements: dict[str, tuple[str, ...]] | None = None,
    patch_releases: dict[str, str] | None = None,
    release_times: dict[str, str] | None = None,
    enikk: Iterable[dict[str, Any]] | None = None,
    launch_covered: bool = False,
    treasures: dict[str, dict[str, str]] | None = None,
) -> list[RosterRow]:
    """Full outer join on ``unit_id``, then resolve one release date per unit.

    A unit present in only one source is still emitted: units appear in the game
    files before the community tables catch up, and dropping them would make the
    roster silently lag every new release.

    ``launch_covered`` says the notice history reaches back past the global
    launch, which is what makes "never introduced by any notice" evidence of
    having shipped with the game rather than of a gap in the history.

    ``treasures`` (unit id -> its ``treasures.csv`` row) gives ``treasure_at``.
    """
    overrides = overrides or {}
    extra_elements = extra_elements or {}
    patch_releases = patch_releases or {}
    release_times = release_times or {}

    merged: dict[str, RosterRow] = {}
    for row in gamefiles:
        unit = merged.setdefault(row["unit_id"], RosterRow(unit_id=row["unit_id"]))
        for field_name in ("name_en", "name_ko", "name_ja", "full_name_en", "full_name_ko", "full_name_ja"):
            setattr(unit, field_name, row.get(field_name) or getattr(unit, field_name))
        unit.in_gamefiles = 1

    for row in nikkeutils:
        unit = merged.setdefault(row["unit_id"], RosterRow(unit_id=row["unit_id"]))
        # Game files win on names: they are the game's own localisation table.
        unit.name_en = unit.name_en or row.get("name_en", "")
        for attribute in (*ATTRIBUTES, "datafile_added"):
            if row.get(attribute):
                setattr(unit, attribute, row[attribute])
        unit.in_nikkeutils = 1

    for row in enikk or []:
        unit = merged.setdefault(row["unit_id"], RosterRow(unit_id=row["unit_id"]))
        unit.name_en = unit.name_en or row.get("name_en", "")
        for attribute in ATTRIBUTES:
            if row.get(attribute) and not getattr(unit, attribute):
                setattr(unit, attribute, row[attribute])
        unit.in_enikk = 1

    for unit_id, unit in merged.items():
        display = unit.name_en or unit.name_ko
        suffix = variant_suffix(display)
        unit.is_variant = 1 if suffix else 0
        unit.base_name_en = display.split(":")[0].strip() if suffix else display
        unit.extra_elements = ";".join(e for e in extra_elements.get(unit_id, ()) if e != unit.element)

        if unit_id in overrides:
            unit.release_date = overrides[unit_id]["release_date"]
            unit.release_date_source = "manual"
        elif unit_id in patch_releases:
            unit.release_date = patch_releases[unit_id]
            unit.release_at = release_times.get(unit_id, "")
            unit.release_date_source = "patchnote"
        elif launch_covered and unit.datafile_added and unit.datafile_added <= GLOBAL_LAUNCH_DATE:
            unit.release_date = GLOBAL_LAUNCH_DATE
            unit.release_date_source = "launch"
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

    for unit_id, treasure in (treasures or {}).items():
        if unit_id in merged:
            merged[unit_id].treasure_at = treasure.get("treasure_at", "")
        else:
            log.warning("treasure for unit %s, which the roster does not have", unit_id)

    return [merged[key] for key in sorted(merged)]


def _name_tail(name: str, base: str) -> str | None:
    """What follows ``base`` in ``name`` when ``name`` is ``base`` plus a qualifier."""
    if not base or not name.startswith(base) or name == base:
        return None
    tail = name[len(base):]
    return tail if tail[:1] in (" ", ":", "：", "(", "（") else None


def build_alias_rows(roster: Iterable[RosterRow]) -> list[dict[str, str]]:
    """Every spelling we know for each unit, as a reviewable table.

    Kinds: ``full`` (the game's name), ``variant_suffix`` (``Red Hood`` for
    ``Rapi: Red Hood``), ``full_name`` (a collaboration unit's full name from
    its description) and ``full_name_variant`` (that full name carried over to
    a later version of the character: the notice calls ``레이 (가칭)``
    "아야나미 레이 (가칭)").
    """
    units = list(roster)
    rows: list[dict[str, str]] = []
    for unit in units:
        for language in ("en", "ko", "ja"):
            value = getattr(unit, f"name_{language}")
            if value:
                rows.append({"unit_id": unit.unit_id, "alias": value, "language": language, "kind": "full"})
                suffix = variant_suffix(value)
                if suffix:
                    rows.append(
                        {"unit_id": unit.unit_id, "alias": suffix, "language": language, "kind": "variant_suffix"}
                    )
            full = getattr(unit, f"full_name_{language}")
            if full:
                rows.append({"unit_id": unit.unit_id, "alias": full, "language": language, "kind": "full_name"})

    for owner in units:
        for language in ("en", "ko", "ja"):
            full = getattr(owner, f"full_name_{language}")
            base = getattr(owner, f"name_{language}")
            if not full or not base:
                continue
            # "퀸(마코토)" is announced as "퀸(니지마 마코토)": the short name
            # inside the game name expands to the full name.
            tokens = full.split()
            for token in {tokens[0], tokens[-1]} if len(tokens) > 1 else ():
                expanded = base.replace(token, full, 1)
                if token in base and full not in base and expanded != full:
                    rows.append(
                        {"unit_id": owner.unit_id, "alias": expanded, "language": language, "kind": "full_name_variant"}
                    )
            for other in units:
                if other.unit_id == owner.unit_id:
                    continue
                tail = _name_tail(getattr(other, f"name_{language}"), base)
                if tail is not None:
                    rows.append(
                        {
                            "unit_id": other.unit_id,
                            "alias": f"{full}{tail}",
                            "language": language,
                            "kind": "full_name_variant",
                        }
                    )
    return rows


def load_manual_aliases(path: Path | None = None) -> list[dict[str, str]]:
    """Curated spellings from data/manual/unit_aliases.csv (unit_id, alias, reason)."""
    target = path or (manual_dir() / MANUAL_ALIAS_CSV)
    if not target.is_file():
        return []
    with target.open(encoding="utf-8", newline="") as handle:
        return [
            {"unit_id": normalize_unit_id(row["unit_id"]), "alias": row["alias"].strip()}
            for row in csv.DictReader(handle)
            if row.get("unit_id") and row.get("alias")
        ]


def load_alias_index(path: Path | None = None) -> NameIndex | None:
    """The name index behind every name lookup, built from ``unit_aliases.csv``.

    Game names and full names go in the primary tier, together with the curated
    aliases; variant suffixes are re-derived as the secondary tier by
    :func:`build_name_index` itself.
    """
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
        kind = row.get("kind")
        if kind == "full" and row.get("language"):
            record[f"name_{row['language']}"] = row["alias"]
        elif kind in ("full_name", "full_name_variant"):
            aliases.append({"unit_id": unit_id, "alias": row["alias"]})
    aliases.extend(load_manual_aliases())
    index = build_name_index(list(by_unit.values()), aliases=aliases)
    if index.ambiguous:
        log.debug("names shared by more than one unit (resolved by context only): %s", sorted(index.ambiguous))
    return index


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build(
    *,
    gamefiles_run: SnapshotRun | None = None,
    nikkeutils_run: SnapshotRun | None = None,
    out_dir: Path | None = None,
    patch_releases: dict[str, str] | None = None,
    release_times: dict[str, str] | None = None,
    enikk: list[dict[str, Any]] | None = None,
    launch_covered: bool = False,
    treasures: dict[str, dict[str, str]] | None = None,
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
        extra_elements=load_extra_elements(),
        patch_releases=patch_releases,
        release_times=release_times,
        enikk=enikk,
        launch_covered=launch_covered,
        treasures=treasures,
    )

    target_dir = out_dir or processed_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    roster_path = target_dir / ROSTER_CSV
    alias_path = target_dir / ALIAS_CSV

    fieldnames = list(RosterRow.__dataclass_fields__)
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
        "with_treasure": sum(1 for u in roster if u.treasure_at),
        "from_gamefiles": sum(u.in_gamefiles for u in roster),
        "from_nikkeutils": sum(u.in_nikkeutils for u in roster),
        "from_enikk": sum(u.in_enikk for u in roster),
        "variants": sum(u.is_variant for u in roster),
        "release_date_source": {
            source: sum(1 for u in roster if u.release_date_source == source)
            for source in ("manual", "patchnote", "launch", "datafile", "datafile_floored", "")
        },
        "release_date_confidence": {
            level: sum(1 for u in roster if u.release_date_confidence == level)
            for level in ("high", "medium", "low", "none")
        },
        "missing_attributes": [u.unit_id for u in roster if not (u.element and u.unit_class)],
        "roster_csv": str(roster_path),
        "alias_csv": str(alias_path),
        "alias_rows": len(alias_rows),
    }
    log.info("roster built: %s units -> %s", len(roster), roster_path)
    return summary
