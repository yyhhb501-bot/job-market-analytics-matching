"""Small HTML helpers shared by the parsers (stdlib only)."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAK = re.compile(r"<\s*(?:br|/p|/div|/li)\s*/?\s*>", re.IGNORECASE)
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def strip_tags(value: str | None) -> str:
    """Convert an HTML fragment to readable plain text."""
    if not value:
        return ""
    text = _SCRIPT_STYLE.sub(" ", value)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


def first_group(pattern: str, value: str | None, group: int = 1) -> str | None:
    if not value:
        return None
    match = re.search(pattern, value, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return html.unescape(match.group(group)).strip()


__all__ = ["first_group", "strip_tags"]
