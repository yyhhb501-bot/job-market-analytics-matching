"""Load ATS board configuration from ``config/ats_companies.json``.

Entries may be plain strings (a board token) or objects with extra fields, e.g.
Workday's ``tenant``/``host``/``site`` or a per-company API token.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from apps.api.config import Settings

logger = logging.getLogger("jobagg.collectors.ats")


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else Path.cwd() / path


def load_board_entries(settings: Settings, key: str) -> list[dict]:
    """Return boards as dicts. A bare string becomes ``{"token": value}``."""
    path = _resolve(settings.ats_companies_file)
    if not path.exists():
        logger.warning("ATS companies file not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Invalid ATS companies file %s: %s", path, exc)
        return []

    entries: list[dict] = []
    for entry in data.get(key) or []:
        if isinstance(entry, str) and entry.strip():
            entries.append({"token": entry.strip()})
        elif isinstance(entry, dict) and entry:
            entries.append({str(k): v for k, v in entry.items()})
    return entries


def load_board_tokens(settings: Settings, key: str) -> list[str]:
    return [entry["token"] for entry in load_board_entries(settings, key) if entry.get("token")]


__all__ = ["load_board_entries", "load_board_tokens"]
