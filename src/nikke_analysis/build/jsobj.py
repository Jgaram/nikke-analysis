"""A minimal reader for JavaScript object-literal data files.

Some of the best community datasets ship as ``const characters = [ {...}, ... ]``
in a ``.js`` file rather than JSON, so they use unquoted keys, single quotes and
trailing commas - all of which ``json.loads`` rejects.

Rather than regex-scraping fields (which silently returns nothing when the
upstream format shifts) this is a small recursive-descent parser for the literal
subset those files actually use: objects, arrays, strings, numbers, booleans and
null. Anything outside that subset raises with a character offset, so a format
change is a loud failure instead of an empty table.
"""

from __future__ import annotations

import re
from typing import Any

_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "'": "'", "\\": "\\", "/": "/"}


class JsLiteralError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def error(self, message: str) -> JsLiteralError:
        line = self.text.count("\n", 0, self.pos) + 1
        return JsLiteralError(f"{message} at offset {self.pos} (line {line})")

    def skip_ws(self) -> None:
        text, n = self.text, len(self.text)
        while self.pos < n:
            ch = text[self.pos]
            if ch in " \t\r\n":
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = n if end == -1 else end + 1
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos)
                if end == -1:
                    raise self.error("unterminated block comment")
                self.pos = end + 2
            else:
                return

    def parse_value(self) -> Any:
        self.skip_ws()
        if self.pos >= len(self.text):
            raise self.error("unexpected end of input")
        ch = self.text[self.pos]
        if ch == "{":
            return self.parse_object()
        if ch == "[":
            return self.parse_array()
        if ch in "\"'":
            return self.parse_string()
        if self.text.startswith("true", self.pos):
            self.pos += 4
            return True
        if self.text.startswith("false", self.pos):
            self.pos += 5
            return False
        if self.text.startswith("null", self.pos):
            self.pos += 4
            return None
        match = _NUMBER_RE.match(self.text, self.pos)
        if match:
            self.pos = match.end()
            raw = match.group(0)
            return float(raw) if ("." in raw or "e" in raw or "E" in raw) else int(raw)
        raise self.error(f"unexpected character {ch!r}")

    def parse_string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        out: list[str] = []
        while True:
            if self.pos >= len(self.text):
                raise self.error("unterminated string")
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                esc = self.text[self.pos]
                if esc == "u":
                    out.append(chr(int(self.text[self.pos + 1 : self.pos + 5], 16)))
                    self.pos += 5
                    continue
                out.append(_ESCAPES.get(esc, esc))
                self.pos += 1
                continue
            if ch == quote:
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1

    def parse_key(self) -> str:
        self.skip_ws()
        ch = self.text[self.pos]
        if ch in "\"'":
            return self.parse_string()
        match = _IDENT_RE.match(self.text, self.pos)
        if match:
            self.pos = match.end()
            return match.group(0)
        match = _NUMBER_RE.match(self.text, self.pos)
        if match:  # numeric keys, e.g. `specialties: { 1: "Buffer" }`
            self.pos = match.end()
            return match.group(0)
        raise self.error("expected an object key")

    def parse_object(self) -> dict[str, Any]:
        self.pos += 1  # '{'
        obj: dict[str, Any] = {}
        while True:
            self.skip_ws()
            if self.pos >= len(self.text):
                raise self.error("unterminated object")
            if self.text[self.pos] == "}":
                self.pos += 1
                return obj
            key = self.parse_key()
            self.skip_ws()
            if self.text[self.pos] != ":":
                raise self.error(f"expected ':' after key {key!r}")
            self.pos += 1
            obj[key] = self.parse_value()
            self.skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1

    def parse_array(self) -> list[Any]:
        self.pos += 1  # '['
        items: list[Any] = []
        while True:
            self.skip_ws()
            if self.pos >= len(self.text):
                raise self.error("unterminated array")
            if self.text[self.pos] == "]":
                self.pos += 1
                return items
            items.append(self.parse_value())
            self.skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1


def parse_js_literal(text: str) -> Any:
    """Parse a single JS literal value from ``text``."""
    parser = _Parser(text)
    value = parser.parse_value()
    return value


def extract_array_literal(source: str, variable: str) -> list[Any]:
    """Pull ``const <variable> = [ ... ]`` out of a JS module and parse it."""
    pattern = re.compile(
        r"(?:const|let|var)\s+" + re.escape(variable) + r"\s*=\s*(?=\[)", re.MULTILINE
    )
    match = pattern.search(source)
    if not match:
        raise JsLiteralError(f"no array assignment found for {variable!r}")
    parser = _Parser(source)
    parser.pos = match.end()
    value = parser.parse_array()
    if not isinstance(value, list):
        raise JsLiteralError(f"{variable!r} is not an array")
    return value
