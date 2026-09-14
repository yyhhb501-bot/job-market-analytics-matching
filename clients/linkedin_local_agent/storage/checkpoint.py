"""Resumable run checkpoint: which pages are done and what has been uploaded."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from clients.linkedin_local_agent.storage._json_store import read_json, write_json_atomic


class Checkpoint:
    """Tracks completed search pages so an interrupted run can resume.

    All mutations are in memory; call :meth:`save` after each page/batch so a
    crash never loses more than the page currently in flight.
    """

    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        data = data or {}
        self.completed_pages: set[str] = set(data.get("completed_pages", []))
        self.uploaded_job_ids: set[str] = set(data.get("uploaded_job_ids", []))
        self.stats: dict[str, int] = data.get("stats", {})

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        data = read_json(Path(path), default={})
        return cls(Path(path), data if isinstance(data, dict) else {})

    def save(self) -> None:
        write_json_atomic(
            self.path,
            {
                "completed_pages": sorted(self.completed_pages),
                "uploaded_job_ids": sorted(self.uploaded_job_ids),
                "stats": self.stats,
                "updated_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        )

    def is_page_done(self, page_key: str) -> bool:
        return page_key in self.completed_pages

    def mark_page_done(self, page_key: str) -> None:
        self.completed_pages.add(page_key)

    def mark_uploaded(self, job_ids: list[str]) -> None:
        self.uploaded_job_ids.update(job_ids)

    def bump(self, name: str, amount: int = 1) -> None:
        self.stats[name] = self.stats.get(name, 0) + amount

    def reset(self) -> None:
        self.completed_pages.clear()
        self.uploaded_job_ids.clear()
        self.stats.clear()


__all__ = ["Checkpoint"]
