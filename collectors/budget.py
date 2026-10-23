"""Daily upstream visit budgets, enforced per source across worker restarts.

Counters live in the ``source_visit_counters`` table (one row per source per
day) so the budget survives process restarts and is shared by every worker.
A limit of ``0`` (the default) means unlimited — budgets only apply when the
operator configures ``DAILY_PAGE_VISIT_LIMIT`` / ``DAILY_DETAIL_VISIT_LIMIT``.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.models import SourceVisitCounter

logger = logging.getLogger("jobagg.collectors.budget")


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class VisitBudget:
    """Track and enforce a source's daily page/detail visit allowances."""

    def __init__(
        self,
        source: str,
        *,
        session_factory: sessionmaker[Session],
        page_limit: int = 0,
        detail_limit: int = 0,
    ) -> None:
        self.source = source
        self.session_factory = session_factory
        self.page_limit = max(int(page_limit), 0)
        self.detail_limit = max(int(detail_limit), 0)
        self.day = _today()
        # In-process mirrors of the DB counters (single worker per source via
        # the run mutex; the DB row remains the cross-restart source of truth).
        self.page_visits = 0
        self.detail_visits = 0
        self._load()

    # -- state --------------------------------------------------------------

    def _load(self) -> None:
        with self.session_factory() as session:
            row = session.scalar(
                select(SourceVisitCounter).where(
                    SourceVisitCounter.source == self.source,
                    SourceVisitCounter.day == self.day,
                )
            )
            if row is not None:
                self.page_visits = int(row.page_visits or 0)
                self.detail_visits = int(row.detail_visits or 0)

    def _save(self) -> None:
        with self.session_factory() as session:
            row = session.scalar(
                select(SourceVisitCounter).where(
                    SourceVisitCounter.source == self.source,
                    SourceVisitCounter.day == self.day,
                )
            )
            if row is None:
                row = SourceVisitCounter(
                    source=self.source, day=self.day, page_visits=0, detail_visits=0
                )
                session.add(row)
            row.page_visits = self.page_visits
            row.detail_visits = self.detail_visits
            session.commit()

    def _roll_day(self) -> None:
        today = _today()
        if today != self.day:
            self.day = today
            self.page_visits = 0
            self.detail_visits = 0

    # -- enforcement ----------------------------------------------------------

    def page_allowed(self) -> bool:
        """True when another page visit fits in today's budget."""
        self._roll_day()
        return self.page_limit == 0 or self.page_visits < self.page_limit

    def remaining_pages(self) -> int | None:
        self._roll_day()
        return None if self.page_limit == 0 else max(self.page_limit - self.page_visits, 0)

    # -- recording ------------------------------------------------------------

    async def record_page(self) -> None:
        self._roll_day()
        self.page_visits += 1
        try:
            self._save()
        except Exception:  # noqa: BLE001 - budget tracking must not break a run
            logger.exception("failed to persist page visit counter for %s", self.source)

    async def record_detail(self) -> bool:
        """Count one detail visit; False when today's detail budget is spent."""
        self._roll_day()
        if self.detail_limit != 0 and self.detail_visits >= self.detail_limit:
            return False
        self.detail_visits += 1
        try:
            self._save()
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist detail visit counter for %s", self.source)
        return True


__all__ = ["VisitBudget"]
