"""enikk snapshots -> season metadata and unit attributes.

Two readers over what ``collect.enikk.collect_seasons`` and
``collect.enikk.collect_characters`` stored:

``load_seasons``     per Solo Raid season: the boss, its picture, its element, the
                     element it is weak to, and the window in which enikk actually
                     collected rankings (first and last point of the damage chart).
``load_characters``  per unit: attributes from enikk's copy of the game tables,
                     mapped onto the roster's vocabulary.

enikk's collection window is evidence that a season was being played, not its
schedule: collection starts a day or two after opening and the last point often
lands a few days after the close. The schedule comes from the notices; this is
what the notices are checked against.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..collect.enikk import CHARACTERS_SOURCE, SEASONS_SOURCE, extract_characters
from ..util.kdate import KST
from ..util.names import normalize_unit_id
from ..util.snapshot import latest_run, list_runs

log = logging.getLogger(__name__)

ELEMENTS = {"Fire": "Fire", "Water": "Water", "Wind": "Wind", "Iron": "Iron", "Electronic": "Electric", "Electric": "Electric"}
BURSTS = {"Step1": "I", "Step2": "II", "Step3": "III", "AllStep": "I-II-III"}
MANUFACTURERS = {
    "ELYSION": "Elysion",
    "MISSILIS": "Missilis Industry",
    "TETRA": "Tetra Line",
    "PILGRIM": "Pilgrim",
    "ABNORMAL": "Abnormal",
}
WEAPONS = {
    "AR": "Assault Rifle",
    "SMG": "Sub Machine Gun",
    "SG": "Shotgun",
    "SR": "Sniper Rifle",
    "RL": "Rocket Launcher",
    "MG": "Machine Gun",
}


@dataclass
class EnikkSeason:
    season: int
    boss_en: str = ""
    boss_image: str = ""  # enikk's name for the boss picture, ``full_eba002_hsta`` (/bosses/<name>.png)
    boss_element: str = ""
    weak_element: str = ""
    last_updated: str = ""
    observed_first: str = ""
    observed_last: str = ""
    collections: int = 0


def _boss_name(value: Any) -> str:
    """enikk's name for the boss; a bare number (season 5 has one) is not a name."""
    name = str(value or "").strip()
    return "" if name.isdigit() else name


_IMAGE_RE = re.compile(r"^[a-z0-9_]+$")


def boss_image(value: Any) -> str:
    """enikk's name for a boss picture, or "" when it is not a plain file name."""
    name = str(value or "").strip()
    return name if _IMAGE_RE.fullmatch(name) else ""


def _kst_iso(value: str) -> str:
    if not value:
        return ""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.astimezone(KST).isoformat()


def load_seasons(root: Path | None = None) -> dict[int, EnikkSeason]:
    """Newest stored record of every season, keyed by season number."""
    seasons: dict[int, EnikkSeason] = {}

    def season(number: int) -> EnikkSeason:
        return seasons.setdefault(number, EnikkSeason(season=number))

    for run in list_runs(SEASONS_SOURCE, root=root):  # oldest first; later wins
        for entry in run.entries:
            meta = entry.get("meta") or {}
            try:
                document = run.read_json(entry["filename"])
            except (OSError, ValueError) as exc:
                log.warning("unreadable enikk file %s/%s: %s", run.run_id, entry.get("filename"), exc)
                continue
            data = document.get("data") or {}
            kind = meta.get("kind")
            if kind == "summaries":
                for row in data.get("soloRaidSummaries") or []:
                    number = int(row.get("raid_number") or 0)
                    if number <= 0:
                        continue
                    record = season(number)
                    record.boss_en = _boss_name(row.get("wave_name")) or record.boss_en
                    record.boss_image = boss_image(row.get("monster_image")) or record.boss_image
                    record.weak_element = ELEMENTS.get(str(row.get("weakness") or ""), record.weak_element)
                    record.last_updated = _kst_iso(str((row.get("data") or {}).get("lastupdated") or "")) or record.last_updated
            elif kind == "season":
                raid = data.get("soloRaid") or {}
                number = int(meta.get("raid") or raid.get("raid_number") or 0)
                if number <= 0:
                    continue
                record = season(number)
                record.boss_en = _boss_name(raid.get("wave_name")) or record.boss_en
                record.boss_image = boss_image(raid.get("monster_image")) or record.boss_image
                element = ((raid.get("monster_obj") or {}).get("element_id")) or {}
                record.boss_element = ELEMENTS.get(str(element.get("element") or ""), record.boss_element)
                weak = element.get("weak_element_id")
                if isinstance(weak, str) and weak in ELEMENTS:
                    record.weak_element = record.weak_element or ELEMENTS[weak]
            elif kind == "damage_chart":
                number = int(meta.get("raid") or 0)
                chart = data.get("SRDamageChart") or {}
                times = sorted(
                    {point.get("collectionTime") for points in chart.values() for point in points or [] if point.get("collectionTime")}
                )
                if number <= 0:
                    continue
                record = season(number)
                record.collections = len(times)
                record.observed_first = _kst_iso(times[0]) if times else ""
                record.observed_last = _kst_iso(times[-1]) if times else ""
    return dict(sorted(seasons.items()))


def normalize_character(record: dict[str, Any]) -> dict[str, Any] | None:
    """One enikk unit record in the roster's field names and vocabulary."""
    try:
        unit_id = normalize_unit_id(str(record.get("resource_id")))
    except ValueError:
        return None
    element = (record.get("element_id") or {}).get("element")
    squad = (record.get("squadInfo") or {}).get("name") or record.get("squad") or ""
    return {
        "unit_id": unit_id,
        "name_en": str(record.get("name_localkey") or ""),
        "rarity": str(record.get("original_rare") or ""),
        "burst": BURSTS.get(str(record.get("use_burst_skill") or ""), ""),
        "element": ELEMENTS.get(str(element or ""), ""),
        "manufacturer": MANUFACTURERS.get(str(record.get("corporation") or ""), ""),
        "unit_class": str(record.get("class") or ""),
        "weapon": WEAPONS.get(str(record.get("weapon") or ""), ""),
        "squad": str(squad),
        "first_seen": str(record.get("firstSeen") or ""),
    }


def load_characters(root: Path | None = None) -> list[dict[str, Any]]:
    run = latest_run(CHARACTERS_SOURCE, root=root)
    if run is None:
        return []
    rows = []
    for entry in run.entries:
        for record in extract_characters(run.read_text(entry["filename"])):
            normalized = normalize_character(record)
            if normalized:
                rows.append(normalized)
    return rows
