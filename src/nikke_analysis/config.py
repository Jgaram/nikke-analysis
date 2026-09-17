"""Declarative source configuration.

The ranking site's URL shape and JSON layout live in ``config/enikk.yaml``, not
in Python. When the site changes, the fix is a YAML edit and a re-run against the
snapshots we already hold - no code change, no lost history. That is also what
makes "reflect a new patch without a model in the loop" achievable: the only
moving parts are a config file and a season number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import REPO_ROOT

DEFAULT_ENIKK_CONFIG = REPO_ROOT / "config" / "enikk.yaml"


@dataclass
class FieldMapping:
    """Where each field sits inside one ranking record.

    Paths are dotted, with ``[]`` for "every element of this list", e.g.
    ``data.rankers[].team[].name``. Kept as data so a layout change is a config
    edit; see ``build/raids.py`` for the resolver.
    """

    entries: str = ""
    rank: str = ""
    score: str = ""
    player: str = ""
    team: str = ""
    unit_name: str = ""
    unit_id: str = ""
    boss: str = ""
    season: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.entries and self.team)


@dataclass
class EnikkConfig:
    base_url: str = "https://enikk.app"
    endpoint_template: str = ""
    seasons: list[str] = field(default_factory=list)
    bosses: list[str] = field(default_factory=list)
    extra_params: dict[str, Any] = field(default_factory=dict)
    mapping: FieldMapping = field(default_factory=FieldMapping)

    @property
    def ready(self) -> bool:
        return bool(self.endpoint_template) and self.mapping.configured


def load_enikk_config(path: Path | None = None) -> EnikkConfig:
    target = path or DEFAULT_ENIKK_CONFIG
    if not target.is_file():
        return EnikkConfig()
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    mapping_doc = document.get("mapping") or {}
    return EnikkConfig(
        base_url=document.get("base_url", "https://enikk.app"),
        endpoint_template=document.get("endpoint_template", "") or "",
        seasons=[str(s) for s in document.get("seasons", []) or []],
        bosses=[str(b) for b in document.get("bosses", []) or []],
        extra_params=document.get("extra_params", {}) or {},
        mapping=FieldMapping(**{k: str(v) for k, v in mapping_doc.items() if v is not None}),
    )
