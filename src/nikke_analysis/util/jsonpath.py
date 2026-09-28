"""Dotted-path access into JSON documents.

``"data.SRRankings[].teams[].damage"`` means: take ``data``, walk every element of
``SRRankings``, walk every element of each ``teams``, and collect ``damage``.
A missing key yields nothing rather than raising: a partially-populated response
should cost one field, not the whole season.

Kept separate from any one parser because both the collector (to count records
before storing a response) and the builders use it.
"""

from __future__ import annotations

from typing import Any


def resolve_path(document: Any, path: str) -> list[Any]:
    """Walk a dotted path, flattening any segment marked ``[]``."""
    if not path:
        return []
    nodes: list[Any] = [document]
    for segment in path.split("."):
        iterate = segment.endswith("[]")
        key = segment[:-2] if iterate else segment
        next_nodes: list[Any] = []
        for node in nodes:
            value = node
            if key:
                if isinstance(node, dict):
                    value = node.get(key)
                elif isinstance(node, list) and key.isdigit():
                    index = int(key)
                    value = node[index] if index < len(node) else None
                else:
                    value = None
            if value is None:
                continue
            if iterate:
                if isinstance(value, list):
                    next_nodes.extend(value)
            else:
                next_nodes.append(value)
        nodes = next_nodes
    return nodes


def resolve_one(document: Any, path: str, default: Any = None) -> Any:
    """The first value at ``path``, or ``default``."""
    values = resolve_path(document, path)
    return values[0] if values else default
