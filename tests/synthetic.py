"""A deterministic fake Solo Raid in the real data's shape, for testing offline.

Every season a boss is weak to one element (cycling through all five), and each
ranked player fields five decks of five distinct units. Players pick their 25
strongest units for the season and deck them strongest first, so the first deck
does the most damage - the structure the metrics are built on.

The world has properties the tests can check the metrics recover:

* ``element_dps``  one damage dealer per element, strong only when the boss is
                   weak to it -> a specialist whose best element is its own;
* ``universal``    two supports strong everywhere -> universal;
* ``partner``      a Water support that only matters next to the Wind dealer,
                   i.e. in Wind-weak seasons -> best element Wind, not Water;
* ``newcomer``     a dominant unit released mid-run -> shows up at once, and
                   nobody could field it before its release;
* ``core_pair``    two units always decked together -> the top synergy pair;
* fillers, the weakest of which nobody fields -> zero rows, tier D.

Everything is driven by a seeded RNG, so a failing test fails the same way twice.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import pandas as pd

ELEMENTS = ("Fire", "Water", "Wind", "Iron", "Electric")
DECKS = 5
DECK_SIZE = 5


@dataclass
class SyntheticWorld:
    entries: pd.DataFrame
    roster: pd.DataFrame
    seasons: pd.DataFrame
    periods: pd.DataFrame
    element_dps: dict[str, str]
    universal: list[str]
    partner: str
    newcomer: str
    newcomer_season: int
    core_pair: tuple[str, str]
    live_season: int
    never_used: list[str] = field(default_factory=list)


def make_world(*, seasons: int = 10, servers: int = 2, rankers: int = 20, fillers: int = 30, seed: int = 7) -> SyntheticWorld:
    rng = random.Random(seed)
    base = pd.Timestamp("2025-01-02T12:00:00+09:00")
    starts = {s: base + pd.Timedelta(days=35 * (s - 1)) for s in range(1, seasons + 1)}
    ends = {s: starts[s] + pd.Timedelta(days=7) - pd.Timedelta(hours=7, seconds=1) for s in starts}
    weak = {s: ELEMENTS[(s - 1) % len(ELEMENTS)] for s in starts}
    launch = "2024-11-04"

    units: dict[str, dict] = {}

    def add(unit_id: str, name: str, element: str, unit_class: str, burst: str, release: str) -> str:
        units[unit_id] = {
            "unit_id": unit_id, "name_en": name, "name_ko": f"{name}(ko)", "element": element, "burst": burst,
            "unit_class": unit_class, "rarity": "SSR", "release_date": release, "release_at": "",
        }
        return unit_id

    element_dps = {e: add(f"1{i}0", f"{e} Dealer", e, "Attacker", "III", launch) for i, e in enumerate(ELEMENTS)}
    universal = [add("200", "Anywhere Support", "Iron", "Supporter", "I", launch),
                 add("201", "Anywhere Defender", "Fire", "Defender", "II", launch)]
    partner = add("300", "Wind Partner", "Water", "Supporter", "II", launch)
    newcomer_season = 6
    newcomer = add("400", "Newcomer", "Electric", "Attacker", "III",
                   (starts[newcomer_season] - pd.Timedelta(days=3)).date().isoformat())
    core_pair = (add("500", "Core A", "Wind", "Supporter", "I", launch), add("501", "Core B", "Wind", "Defender", "II", launch))
    filler_ids = [add(f"{600 + i}", f"Filler {i}", ELEMENTS[i % 5], "Supporter", ("I", "II", "III")[i % 3], launch)
                  for i in range(fillers)]
    filler_strength = {u: 0.4 + 1.1 * (fillers - i) / fillers for i, u in enumerate(filler_ids)}

    def strength(unit_id: str, season: int) -> float:
        if unit_id in element_dps.values():
            return 3.0 if units[unit_id]["element"] == weak[season] else 0.3
        if unit_id in universal:
            return 2.2
        if unit_id == partner:
            return 2.6 if weak[season] == "Wind" else 0.2
        if unit_id == newcomer:
            return 3.4
        if unit_id in core_pair:
            return 1.6
        return filler_strength[unit_id]

    live_season = seasons
    rows = []
    for season in starts:
        released = [u for u, info in units.items() if pd.Timestamp(info["release_date"], tz="Asia/Seoul") <= starts[season]]
        collected = ends[season] if season != live_season else starts[season] + pd.Timedelta(days=3)
        for s in range(servers):
            server = f"S{s + 1}"
            for rank in range(1, rankers + 1):
                noisy = {u: strength(u, season) + rng.gauss(0, 0.12) for u in released}
                picked = sorted(noisy, key=lambda u: -noisy[u])[: DECKS * DECK_SIZE]
                if core_pair[0] in picked and core_pair[1] in picked:
                    # Keep the pair together: move B next to A.
                    picked.remove(core_pair[1])
                    picked.insert(picked.index(core_pair[0]) + 1, core_pair[1])
                decks = [picked[i * DECK_SIZE:(i + 1) * DECK_SIZE] for i in range(DECKS)]
                skill = 1.0 + 0.5 * (rankers - rank) / rankers
                scores = [round(1e9 * skill * sum(strength(u, season) for u in deck) * rng.uniform(0.97, 1.03))
                          for deck in decks]
                player = f"{server}-{rank:03d}"
                for deck_number, (deck, deck_score) in enumerate(zip(decks, scores), start=1):
                    for slot, unit_id in enumerate(deck):
                        rows.append(
                            {
                                "content": "soloraid", "season": season, "server": server, "rank": rank,
                                "player": player, "score": sum(scores), "deck": deck_number, "deck_score": deck_score,
                                "slot": slot, "unit_id": unit_id, "unit_name_raw": units[unit_id]["name_en"],
                                "unit_cp": 100000 + 1000 * rank, "unit_cores": 10,
                                "collected_at": collected.tz_convert("UTC").date().isoformat(),
                            }
                        )

    entries = pd.DataFrame(rows)
    used = set(entries["unit_id"])
    season_rows = pd.DataFrame(
        [
            {
                "season": s, "boss_en": f"Boss {s}", "boss_ko": "", "element": ELEMENTS[s % 5], "weak_element": weak[s],
                "scheduled_start": starts[s].isoformat(), "scheduled_end": ends[s].isoformat(),
                "start_at": starts[s].isoformat(), "end_at": ends[s].isoformat(), "periods": 1, "disrupted": 0,
                "record_reset": 0, "numbered_by": "notice", "enikk_first_seen": starts[s].isoformat(),
                "enikk_last_seen": ends[s].isoformat(), "enikk_collections": 10, "units_available": "",
                "new_units": "", "checks": "", "notice_ids": "",
            }
            for s in starts
        ]
        + [
            {
                "season": seasons + 1, "boss_en": "Next Boss", "boss_ko": "", "element": "Water",
                "weak_element": ELEMENTS[seasons % 5], "scheduled_start": "", "scheduled_end": "", "start_at": "",
                "end_at": "", "periods": 0, "disrupted": 0, "record_reset": 0, "numbered_by": "enikk",
                "enikk_first_seen": "", "enikk_last_seen": "", "enikk_collections": 0, "units_available": "",
                "new_units": "", "checks": "no_notice", "notice_ids": "",
            }
        ]
    )
    periods = pd.DataFrame(
        [
            {"season": s, "period": 1, "start_at": starts[s].isoformat(), "end_at": ends[s].isoformat(),
             "start_after_maintenance": 0, "end_reason": "scheduled"}
            for s in starts
        ]
    )
    roster = pd.DataFrame(list(units.values()))
    roster["release_date_source"] = "patchnote"
    roster["release_date_confidence"] = "high"
    return SyntheticWorld(
        entries=entries,
        roster=roster,
        seasons=season_rows,
        periods=periods,
        element_dps=element_dps,
        universal=universal,
        partner=partner,
        newcomer=newcomer,
        newcomer_season=newcomer_season,
        core_pair=core_pair,
        live_season=live_season,
        never_used=sorted(set(units) - used),
    )


def write_processed(world: SyntheticWorld, directory) -> None:
    """Lay the world out as the processed tables the pipeline reads."""
    world.entries.to_csv(directory / "raid_entries.csv", index=False)
    world.roster.to_csv(directory / "roster.csv", index=False)
    world.seasons.to_csv(directory / "soloraid_seasons.csv", index=False)
    world.periods.to_csv(directory / "soloraid_periods.csv", index=False)
    pd.DataFrame(
        [{"notice_id": "official:p", "source": "official", "published_at": "2025-06-01T18:00:00+09:00",
          "updated_at": "", "kind": "update", "title": "6월 업데이트 공지", "url": "", "chars": 100}]
    ).to_csv(directory / "notices.csv", index=False)
    release = world.roster.set_index("unit_id").loc[world.newcomer, "release_date"]
    pd.DataFrame(
        [{"unit_id": world.newcomer, "kind": "special", "debut": 1, "start_at": f"{release}T05:00:00+09:00",
          "end_at": "", "start_after_maintenance": 0, "notice_id": "official:p", "notice_title": "New Nikke",
          "notice_published_at": "2025-06-01T18:00:00+09:00", "label": "특수 모집 기간", "evidence": ""}]
    ).to_csv(directory / "banners.csv", index=False)
    pd.DataFrame(
        [{"unit_id": world.newcomer, "release_at": f"{release}T05:00:00+09:00", "release_date": release,
          "release_after_maintenance": 0, "banner_kind": "special", "notice_id": "official:p",
          "notice_title": "New Nikke", "notice_published_at": "2025-06-01T18:00:00+09:00", "evidence": ""}]
    ).to_csv(directory / "unit_releases.csv", index=False)
