"""A deterministic fake Solo Raid, for testing the metrics offline.

The real ranking data cannot be committed (it is scraped, perishable and not
ours), and the metric code still has to be verifiable. So the tests build a
leaderboard with known properties and check that the metrics recover them:

* units have a latent strength that peaks at release and decays, so
  ``trajectories`` should find a peak near the debut season;
* a scripted unit is introduced mid-run, so ``meta_shift`` should spike on that
  transition and ``newcomer_share`` should be non-zero;
* two units are forced to appear together, so ``synergy`` should rank that pair
  near the top.

Everything is driven by a seeded RNG, so a failing test fails the same way twice.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pandas as pd

TEAM_SIZE = 5


@dataclass
class SyntheticWorld:
    entries: pd.DataFrame
    roster: pd.DataFrame
    calendar: pd.DataFrame
    core_pair: tuple[str, str]
    newcomer: str
    newcomer_season: str


def make_world(
    *,
    seasons: int = 6,
    bosses: int = 3,
    teams_per_boss: int = 50,
    units: int = 60,
    seed: int = 7,
) -> SyntheticWorld:
    rng = random.Random(seed)

    unit_ids = [f"{i:03d}" for i in range(10, 10 + units)]
    season_names = [str(i) for i in range(1, seasons + 1)]
    boss_names = [f"boss{i}" for i in range(1, bosses + 1)]

    # Release schedule: most units exist from the start, a few arrive later.
    base_day = pd.Timestamp("2024-01-01")
    release: dict[str, pd.Timestamp] = {}
    for index, unit in enumerate(unit_ids):
        if index < units - seasons:
            release[unit] = base_day
        else:
            later = index - (units - seasons)
            release[unit] = base_day + pd.Timedelta(days=60 * (later + 1))

    season_start = {
        name: base_day + pd.Timedelta(days=60 * i) for i, name in enumerate(season_names)
    }

    # A unit introduced mid-run that immediately dominates: the meta-shift test.
    newcomer = unit_ids[-2]
    newcomer_season = season_names[-2]
    release[newcomer] = season_start[newcomer_season] - pd.Timedelta(days=5)

    # A pair that is always run together when either is run: the synergy test.
    core_pair = (unit_ids[0], unit_ids[1])

    strength = {unit: rng.uniform(0.2, 1.0) for unit in unit_ids}

    rows = []
    for season in season_names:
        start = season_start[season]
        available = [u for u in unit_ids if release[u] <= start]
        for boss in boss_names:
            weights = []
            for unit in available:
                age = max((start - release[unit]).days, 0) / 60.0
                # Peak at release, then decay: power creep in one line.
                value = strength[unit] * math.exp(-0.22 * age)
                if unit == newcomer and season >= newcomer_season:
                    value *= 9.0
                weights.append(max(value, 1e-6))

            for rank in range(1, teams_per_boss + 1):
                team: list[str] = []
                pool, pool_weights = list(available), list(weights)
                while len(team) < TEAM_SIZE and pool:
                    pick = rng.choices(pool, weights=pool_weights, k=1)[0]
                    index = pool.index(pick)
                    pool.pop(index)
                    pool_weights.pop(index)
                    team.append(pick)
                    if pick in core_pair:
                        partner = core_pair[1] if pick == core_pair[0] else core_pair[0]
                        if partner in pool and len(team) < TEAM_SIZE:
                            index = pool.index(partner)
                            pool.pop(index)
                            pool_weights.pop(index)
                            team.append(partner)

                team_power = sum(strength[u] for u in team)
                score = 1e9 * team_power * (1.0 + 0.6 * (teams_per_boss - rank) / teams_per_boss)
                for slot, unit in enumerate(team):
                    rows.append(
                        {
                            "content": "soloraid",
                            "season": season,
                            "boss": boss,
                            "rank": rank,
                            "score": round(score, 2),
                            "player": f"p{rank:03d}",
                            "slot": slot,
                            "unit_id": unit,
                            "unit_name_raw": f"Unit {unit}",
                        }
                    )

    entries = pd.DataFrame(rows)
    roster = pd.DataFrame(
        {
            "unit_id": unit_ids,
            "name_en": [f"Unit {u}" for u in unit_ids],
            "name_ko": [f"유닛 {u}" for u in unit_ids],
            "burst": [["I", "II", "III"][i % 3] for i in range(len(unit_ids))],
            "unit_class": [["Attacker", "Supporter", "Defender"][i % 3] for i in range(len(unit_ids))],
            "element": [["Fire", "Water", "Wind", "Iron", "Electric"][i % 5] for i in range(len(unit_ids))],
            "release_date": [release[u].date().isoformat() for u in unit_ids],
        }
    )
    calendar = pd.DataFrame(
        {
            "season": season_names,
            "start_date": [season_start[s].date().isoformat() for s in season_names],
        }
    )
    return SyntheticWorld(entries, roster, calendar, core_pair, newcomer, newcomer_season)
