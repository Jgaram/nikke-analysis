"""Declarative source configuration.

The ranking site's query and JSON layout live in ``config/enikk.yaml``, not in
Python. When the site changes, the fix is a YAML edit and a re-run against the
snapshots we already hold - no code change, no lost history. That is also what
makes "reflect a new patch without a model in the loop" achievable: the only
moving parts are a config file and a season number.

Every field has a default that matches enikk as of 2026-09, so a missing or
partial config file still collects and parses.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .paths import REPO_ROOT

DEFAULT_ENIKK_CONFIG = REPO_ROOT / "config" / "enikk.yaml"

# One request per season. Without ``all: true`` the site answers with the top 50
# of every server, which is the population the metrics are defined on.
DEFAULT_RANKINGS_QUERY = (
    "query SoloRaidRankings($raid: Float!) { SRRankings(raid: $raid) "
    "{ rank playerid server damage cp collectionTime firstAppeared teams } }"
)


@dataclass
class RankingMapping:
    """Where each field sits inside the rankings response.

    Paths are dotted, with ``[]`` for "every element of this list". ``entries``
    and ``decks`` are lists that get walked; ``deck_units``, ``deck_unit_cp`` and
    ``deck_unit_cores`` are parallel lists inside one deck, read slot by slot.
    """

    entries: str = "data.SRRankings[]"
    rank: str = "rank"
    score: str = "damage"
    player: str = "playerid"
    server: str = "server"
    collected_at: str = "collectionTime"
    decks: str = "teams[]"
    deck_score: str = "damage"
    deck_units: str = "characters"
    deck_unit_cp: str = "cpc"
    deck_unit_cores: str = "cores"


@dataclass
class EnikkConfig:
    base_url: str = "https://enikk.app"
    rankings_query: str = DEFAULT_RANKINGS_QUERY
    mapping: RankingMapping = field(default_factory=RankingMapping)
    # Seconds between requests. enikk is run by one person; do not lower this.
    delay: float = 1.5


def load_enikk_config(path: Path | None = None) -> EnikkConfig:
    target = path or DEFAULT_ENIKK_CONFIG
    if not target.is_file():
        return EnikkConfig()
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    rankings = document.get("rankings") or {}
    known = {f.name for f in fields(RankingMapping)}
    mapping_doc = {k: str(v) for k, v in (rankings.get("mapping") or {}).items() if k in known and v}
    return EnikkConfig(
        base_url=str(document.get("base_url") or "https://enikk.app"),
        rankings_query=" ".join(str(rankings.get("query") or DEFAULT_RANKINGS_QUERY).split()),
        mapping=RankingMapping(**mapping_doc),
        delay=float(document.get("delay", 1.5)),
    )
