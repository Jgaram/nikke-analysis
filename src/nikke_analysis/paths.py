"""Canonical filesystem layout.

Every path used by the pipeline is resolved here so that tests can redirect the
whole tree with a single environment variable (``NIKKE_DATA_ROOT``).
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent


def data_root() -> Path:
    override = os.environ.get("NIKKE_DATA_ROOT")
    return Path(override).resolve() if override else REPO_ROOT / "data"


def raw_dir() -> Path:
    """Immutable network snapshots. Never edited by hand, never committed."""
    return data_root() / "raw"


def interim_dir() -> Path:
    """Scratch space for multi-step builds. Safe to delete at any time."""
    return data_root() / "interim"


def processed_dir() -> Path:
    """Tidy tables that the analysis reads. Committed, reviewable as a diff."""
    return data_root() / "processed"


def manual_dir() -> Path:
    """Hand-maintained overrides that win over scraped values.

    This is the only place a human is expected to edit data by hand, and every
    row carries a reason so the override can be retired once upstream is fixed.
    """
    return data_root() / "manual"


def icons_dir() -> Path:
    """Unit, element and class icons the charts draw instead of names. Committed.

    Unlike ``raw/`` this is not a dated snapshot: one file per unit, fetched once
    and kept, so a fresh clone draws the same charts without the network.
    """
    return data_root() / "assets" / "icons"


def unit_icon_path(unit_id: str, directory: Path | None = None) -> Path:
    """A unit's face, by its three-digit roster id (``010`` is Rapi)."""
    return (directory or icons_dir()) / "units" / f"{unit_id}.webp"


def element_icon_path(element: str, directory: Path | None = None) -> Path:
    """An element's icon, by the roster's spelling (``Fire`` ... ``Electric``)."""
    return (directory or icons_dir()) / "elements" / f"{element.lower()}.png"


def class_icon_path(unit_class: str, directory: Path | None = None) -> Path:
    """A class's icon, by the roster's spelling (``Attacker`` ...)."""
    return (directory or icons_dir()) / "classes" / f"{unit_class.lower()}.png"


def reports_dir() -> Path:
    override = os.environ.get("NIKKE_REPORTS_DIR")
    return Path(override).resolve() if override else REPO_ROOT / "reports"


def ensure_dirs() -> None:
    for path in (raw_dir(), interim_dir(), processed_dir(), manual_dir(), reports_dir()):
        path.mkdir(parents=True, exist_ok=True)
