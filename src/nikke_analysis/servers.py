"""The servers a ranking comes from, and choosing some of them.

enikk ranks six servers: GLOBAL, JP, KR, NA, SEA and TW-HK (seasons 5 and 6
only the first four it tracked then). Every server runs the same game version,
the same boss and the same patches, so the metrics pool all of them: six
servers' top 50 is six times the evidence for the same meta.

Pooling is the default, not a rule. A narrower sample is a choice made in one of
two places:

* ``population.servers`` / ``population.exclude_servers`` in config/tiers.yaml -
  the sample the committed metric tables are computed on;
* ``--server`` / ``--exclude`` on ``nikke tier``, ``raid``, ``analyze`` and
  ``viz`` - one look at another sample, which replaces the configured choice and
  leaves the committed tables alone.

Names are forgiving: case does not matter, and Korean names and the obvious
short forms work (``한국``, ``글로벌``, ``tw``). A name that is none of these is
kept as written (upper-cased), so a server enikk adds later can be chosen before
anyone teaches this module its name; the data then decides whether it exists.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable

SERVERS = ("GLOBAL", "JP", "KR", "NA", "SEA", "TW-HK")

SERVER_KO = {
    "GLOBAL": "글로벌",
    "JP": "일본",
    "KR": "한국",
    "NA": "북미",
    "SEA": "동남아",
    "TW-HK": "대만·홍콩",
}

_ALIASES = {
    "global": "GLOBAL", "gl": "GLOBAL", "글로벌": "GLOBAL", "글섭": "GLOBAL",
    "jp": "JP", "japan": "JP", "일본": "JP", "일섭": "JP",
    "kr": "KR", "korea": "KR", "한국": "KR", "한섭": "KR",
    "na": "NA", "northamerica": "NA", "북미": "NA",
    "sea": "SEA", "southeastasia": "SEA", "동남아": "SEA", "동남아시아": "SEA",
    "twhk": "TW-HK", "tw": "TW-HK", "hk": "TW-HK", "taiwan": "TW-HK", "hongkong": "TW-HK",
    "대만": "TW-HK", "홍콩": "TW-HK", "대만홍콩": "TW-HK", "대홍": "TW-HK",
}

# Separators that do not change which server a name means: "TW-HK", "tw/hk",
# "대만·홍콩" and "North America" all fold to one key.
_FOLD = str.maketrans("", "", " -_/·.")


class ServerError(LookupError):
    """A server name the data does not have, or a choice that leaves no server."""


def normalize(name: str) -> str:
    """enikk's spelling of a server: ``kr``, ``한국`` -> ``KR``; ``tw`` -> ``TW-HK``.

    A name this module does not know is returned upper-cased, unchanged otherwise.
    """
    text = unicodedata.normalize("NFKC", str(name)).strip()
    return _ALIASES.get(text.casefold().translate(_FOLD), text.upper())


def split(values: Iterable[str] | str | None) -> tuple[str, ...]:
    """Server names from repeated and/or comma-separated values, normalized and
    deduplicated, in the order given: ``["kr,jp", "KR"]`` -> ``("KR", "JP")``."""
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    names: list[str] = []
    for value in values:
        for part in str(value).split(","):
            if part.strip() and normalize(part) not in names:
                names.append(normalize(part))
    return tuple(names)


def ordered(servers: Iterable[str]) -> list[str]:
    """The known servers in their usual order, anything else after them alphabetically."""
    return sorted(set(servers), key=lambda s: (SERVERS.index(s) if s in SERVERS else len(SERVERS), s))


@dataclass(frozen=True)
class ServerFilter:
    """Which servers a sample keeps: ``include`` (empty = every server) minus ``exclude``."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @classmethod
    def of(cls, include: Iterable[str] | str | None = (), exclude: Iterable[str] | str | None = ()) -> "ServerFilter":
        return cls(split(include), split(exclude))

    def __bool__(self) -> bool:
        return bool(self.include or self.exclude)

    def keeps(self, server: str) -> bool:
        return (not self.include or server in self.include) and server not in self.exclude

    def keep(self, servers: Iterable[str]) -> list[str]:
        """Those of ``servers`` this filter keeps, in the usual order."""
        return [s for s in ordered(servers) if self.keeps(s)]

    def check(self, known: Iterable[str]) -> list[str]:
        """The servers kept out of ``known`` (the servers the data has).

        Raises ServerError for a name the data does not have - a typo must not
        quietly leave the sample as it was - and for a choice that keeps nothing.
        """
        known = ordered(known)
        unknown = [s for s in (*self.include, *self.exclude) if s not in known]
        if unknown:
            raise ServerError(f"없는 서버: {', '.join(unknown)} (있는 서버: {', '.join(known)})")
        kept = self.keep(known)
        if not kept:
            raise ServerError(f"고른 서버가 하나도 남지 않는다: {self.label}")
        return kept

    @property
    def label(self) -> str:
        """``KR·JP``, ``NA·SEA 제외``, ``KR·JP·NA 중 NA 제외``; empty when every server counts."""
        chosen = "·".join(self.include)
        if not self.exclude:
            return chosen
        dropped = "·".join(self.exclude) + " 제외"
        return f"{chosen} 중 {dropped}" if chosen else dropped

    @property
    def caption(self) -> str:
        """The same for chart captions: ``KR·JP 서버만``, ``NA·SEA 제외 전 서버``; empty when every server counts."""
        if self.include and not self.exclude:
            return f"{self.label} 서버만"
        if self.exclude and not self.include:
            return f"{self.label} 전 서버"
        return self.label

    @property
    def slug(self) -> str:
        """A directory name for this choice: ``KR+JP``, ``excl-NA+SEA``, ``KR+JP_excl-JP``."""
        parts = []
        if self.include:
            parts.append("+".join(self.include))
        if self.exclude:
            parts.append("excl-" + "+".join(self.exclude))
        return "_".join(parts) or "all"

    def to_dict(self) -> dict[str, list[str]]:
        return {"include": list(self.include), "exclude": list(self.exclude)}


def describe(chosen: ServerFilter, servers: Iterable[str]) -> str:
    """How a sample reads in a header: ``6개 서버``, ``KR·JP``, ``NA·SEA 제외 4개 서버``.

    ``servers`` are the servers actually in the sample.
    """
    count = len(set(servers))
    if not chosen:
        return f"{count}개 서버"
    if chosen.exclude:
        return f"{chosen.label} {count}개 서버"
    return chosen.label
