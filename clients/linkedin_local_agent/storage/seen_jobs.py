"""Durable ``seen`` state with explicit job states.

Only terminal states (``accepted``/``uploaded``/``duplicate``) block a job from
being processed again. ``filtered_location`` and ``filtered_title`` are
remembered for diagnostics but **must not** permanently hide a job, because it
may be re-posted later as remote or with a different title.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from clients.linkedin_local_agent.models import JobStub
from clients.linkedin_local_agent.storage._json_store import read_json, write_json_atomic

STATE_DISCOVERED = "discovered"
STATE_FETCHED = "fetched"
STATE_FILTERED_LOCATION = "filtered_location"
STATE_FILTERED_TITLE = "filtered_title"
STATE_ACCEPTED = "accepted"
STATE_UPLOADED = "uploaded"
STATE_DUPLICATE = "duplicate"
STATE_FAILED = "failed"

TERMINAL_STATES = frozenset({STATE_ACCEPTED, STATE_UPLOADED, STATE_DUPLICATE})


class SeenStore:
    """Two-key seen index: ``job_id`` and normalised ``title|company``."""

    def __init__(self, path: Path, entries: dict[str, dict] | None = None) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict] = entries or {}

    @classmethod
    def load(cls, path: Path) -> SeenStore:
        data = read_json(Path(path), default={})
        return cls(Path(path), data.get("entries", {}) if isinstance(data, dict) else {})

    def save(self) -> None:
        write_json_atomic(self.path, {"entries": self.entries})

    def _terminal(self, key: str) -> bool:
        entry = self.entries.get(key)
        return bool(entry) and entry.get("status") in TERMINAL_STATES

    def is_blocked(self, stub: JobStub) -> bool:
        return any(self._terminal(key) for key in stub.dedup_keys())

    def status_for(self, stub: JobStub) -> str | None:
        for key in stub.dedup_keys():
            entry = self.entries.get(key)
            if entry:
                return entry.get("status")
        return None

    def mark(self, stub: JobStub, status: str) -> None:
        now = dt.datetime.now(dt.UTC).isoformat()
        for key in stub.dedup_keys():
            existing = self.entries.get(key)
            # A terminal state wins over anything recorded later.
            if existing and existing.get("status") in TERMINAL_STATES and status not in TERMINAL_STATES:
                continue
            self.entries[key] = {
                "status": status,
                "job_id": stub.job_id,
                "title": stub.title,
                "company": stub.company,
                "updated_at": now,
            }


__all__ = [
    "STATE_ACCEPTED",
    "STATE_DISCOVERED",
    "STATE_DUPLICATE",
    "STATE_FAILED",
    "STATE_FETCHED",
    "STATE_FILTERED_LOCATION",
    "STATE_FILTERED_TITLE",
    "STATE_UPLOADED",
    "TERMINAL_STATES",
    "SeenStore",
]
