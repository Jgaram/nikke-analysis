"""Turning the many spellings of a Nikke into one stable id.

Every source spells units differently: the game files say ``Rapi: Red Hood`` /
``라피 : 레드 후드``, patch notes say ``Red Hood``, and a ranking site may use
community shorthand. Analysis is worthless if ``Red Hood`` and ``레드후드`` land
in different rows, so all of it funnels through one identifier.

The identifier is the unit id baked into the game's own data (``c016_00`` ->
``016``). It never changes, it is language independent, and it already
distinguishes alternate versions of a character from the original - ``010`` Rapi
and ``016`` Rapi: Red Hood are separate units, which is exactly how the meta
treats them.

Resolution is strictly deterministic and fails loudly. An unknown spelling is
reported, never guessed at - a silently mis-joined name would corrupt the pick
rates that everything else is built on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Characters that carry no identity: separators, honorific punctuation and the
# full-width variants Korean/Japanese sources use.
_STRIP_RE = re.compile(r"[\s:：・·.,\-–—_'\"()\[\]{}!?/\\]+")


def normalize_name(value: str) -> str:
    """Fold a display name down to a comparison key.

    ``"Rapi: Red Hood"``, ``"rapi red hood"`` and ``"라피 : 레드 후드"`` each fold
    to a single stable token, while genuinely different names stay distinct.
    """
    if value is None:
        return ""
    folded = unicodedata.normalize("NFKC", str(value)).casefold()
    return _STRIP_RE.sub("", folded)


def normalize_unit_id(value: str | int) -> str:
    """Accept ``16``, ``"016"``, ``"c016_00"`` or ``"[016]"`` -> ``"016"``."""
    if isinstance(value, int):
        return f"{value:03d}"
    text = str(value).strip()
    match = re.search(r"(\d{2,4})", text)
    if not match:
        raise ValueError(f"no unit id found in {value!r}")
    return f"{int(match.group(1)):03d}"


def variant_suffix(display_name: str) -> str | None:
    """``"Rapi: Red Hood"`` -> ``"Red Hood"``; a base unit -> ``None``.

    Used to generate secondary aliases, because both patch notes and players
    routinely drop the base name of an alternate version.
    """
    for sep in (":", "："):
        if sep in display_name:
            tail = display_name.split(sep, 1)[1].strip()
            if tail:
                return tail
    return None


@dataclass
class NameIndex:
    """Deterministic name -> unit id lookup with a two-tier fallback.

    Primary tier: full names from the game files plus curated aliases. A
    collision here is a data bug and raises at build time.

    Secondary tier: auto-derived variant suffixes (``Red Hood`` from
    ``Rapi: Red Hood``). Only consulted when the primary tier misses, and only
    when the suffix maps to exactly one unit - ambiguous suffixes such as
    ``Summer`` are dropped instead of guessed.
    """

    primary: dict[str, str] = field(default_factory=dict)
    secondary: dict[str, str] = field(default_factory=dict)
    _ambiguous: set[str] = field(default_factory=set)

    def add_primary(self, name: str, unit_id: str, *, origin: str = "") -> None:
        key = normalize_name(name)
        if not key:
            return
        existing = self.primary.get(key)
        if existing is not None and existing != unit_id:
            raise ValueError(
                f"name collision on {name!r} ({origin}): "
                f"already mapped to unit {existing}, now unit {unit_id}"
            )
        self.primary[key] = unit_id

    def add_secondary(self, name: str, unit_id: str) -> None:
        key = normalize_name(name)
        if not key or key in self.primary:
            return
        existing = self.secondary.get(key)
        if existing is not None and existing != unit_id:
            # Two different units answer to this shorthand; refuse to guess.
            self._ambiguous.add(key)
            self.secondary.pop(key, None)
            return
        if key in self._ambiguous:
            return
        self.secondary[key] = unit_id

    def resolve(self, name: str) -> str | None:
        key = normalize_name(name)
        if not key:
            return None
        hit = self.primary.get(key)
        if hit is not None:
            return hit
        return self.secondary.get(key)

    def resolve_all(self, names: list[str]) -> tuple[dict[str, str], list[str]]:
        """Returns ``(resolved, unresolved)`` - callers are expected to surface
        the unresolved list rather than drop it."""
        resolved: dict[str, str] = {}
        unresolved: list[str] = []
        for name in names:
            unit = self.resolve(name)
            if unit is None:
                unresolved.append(name)
            else:
                resolved[name] = unit
        return resolved, unresolved

    @property
    def ambiguous(self) -> set[str]:
        return set(self._ambiguous)


def build_name_index(
    rows: list[dict[str, str]],
    *,
    aliases: list[dict[str, str]] | None = None,
    name_fields: tuple[str, ...] = ("name_en", "name_ko", "name_ja"),
) -> NameIndex:
    """Build the index from roster rows plus an optional curated alias table.

    ``rows`` need ``unit_id`` and any of ``name_fields``. ``aliases`` rows need
    ``unit_id`` and ``alias``; they are added to the primary tier so a curated
    entry always beats an auto-derived suffix.
    """
    index = NameIndex()
    for row in rows:
        unit_id = normalize_unit_id(row["unit_id"])
        for field_name in name_fields:
            value = row.get(field_name)
            if value:
                index.add_primary(value, unit_id, origin=field_name)

    for row in aliases or []:
        if row.get("alias"):
            index.add_primary(row["alias"], normalize_unit_id(row["unit_id"]), origin="manual alias")

    # Secondary tier last, so it can see the finished primary tier.
    for row in rows:
        unit_id = normalize_unit_id(row["unit_id"])
        for field_name in name_fields:
            value = row.get(field_name)
            if not value:
                continue
            suffix = variant_suffix(value)
            if suffix:
                index.add_secondary(suffix, unit_id)
    return index
