"""Aligning text in a terminal, where a Hangul syllable takes two columns."""

from __future__ import annotations

import unicodedata


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, columns: int) -> str:
    """Left-align ``text`` in ``columns`` columns, cutting it if it is wider."""
    while width(text) > columns:
        text = text[:-1]
    return text + " " * (columns - width(text))


def rjust(text: str, columns: int) -> str:
    """Right-align ``text`` in ``columns`` columns."""
    return " " * max(columns - width(text), 0) + text
