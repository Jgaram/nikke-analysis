"""Reading data out of a server-rendered Next.js (App Router) page.

Such pages carry no ``__NEXT_DATA__`` blob. The props the server rendered are
streamed as "flight" chunks - ``self.__next_f.push([1,"..."])`` calls whose
string arguments, joined, form the React Server Components payload. Records the
page displays appear in that payload as plain JSON objects.

Nothing here knows which page it is reading: callers name the keys that make an
object interesting, and every JSON object carrying all of them is returned. That
keeps a site redesign from mattering as long as the records themselves survive.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

_FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)\s*</script>', re.S)


def flight_payload(html: str) -> str:
    """The concatenated RSC payload of a page ("" when there is none)."""
    parts = []
    for literal in _FLIGHT_RE.findall(html):
        try:
            parts.append(json.loads(f'"{literal}"'))
        except json.JSONDecodeError:
            continue  # a chunk we cannot decode cannot hold the records either
    return "".join(parts)


def find_objects(payload: str, required_keys: Iterable[str], *, anchor: str = '{"id":') -> list[dict[str, Any]]:
    """Every JSON object in ``payload`` that has all of ``required_keys``.

    Objects are located by ``anchor`` (the literal text they start with) and
    decoded in place, so wrapper structure around them is irrelevant.
    """
    wanted = tuple(required_keys)
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    start = payload.find(anchor)
    while start != -1:
        try:
            value, _ = decoder.raw_decode(payload, start)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict) and all(key in value for key in wanted):
            found.append(value)
        start = payload.find(anchor, start + 1)
    return found
