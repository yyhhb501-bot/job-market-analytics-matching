"""Public read-only collection dashboard data.

Whitelisted aggregate figures only: no device tokens, owner references, raw
collector queries, idempotency keys or error texts are ever returned. "Today"
and trend days are Beijing-time (UTC+8) calendar days, matching the local
collector operating window; all timestamps themselves stay UTC-aware.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import CollectorDevice, CollectorRun, ImportBatch, Job
from apps.api.schemas import (
    CollectionLocalUploadRow,
    CollectionOverviewResponse,
    CollectionSourceRow,
    CollectionTrendPoint,
)
from apps.api.source_authorization import public_job_condition
from apps.api.time_windows import BJT, bj_today_start_utc, ensure_aware

router = APIRouter(tags=["collection"])

DAILY_TARGET_PER_SOURCE = 600  # target per source per day, not an achievement
COLLECTOR_HEARTBEAT_STALE_SECONDS = 300


def _utc(value: datetime) -> datetime:
    return ensure_aware(value).astimezone(UTC)


def _bj_today_start_utc(now: datetime) -> datetime:
    """UTC instant of the current Beijing-time midnight."""
    return bj_today_start_utc(now)


@router.get("/collection/overview", response_model=CollectionOverviewResponse)
def collection_overview(db: Session = Depends(get_db)) -> CollectionOverviewResponse:
    now = datetime.now(UTC)
    today_start = _bj_today_start_utc(now)
    week_start = today_start - timedelta(days=6)

    rows = db.execute(
        select(
            Job.source,
            func.count().label("total"),
            func.sum(case((Job.first_seen_at >= today_start, 1), else_=0)).label("today_new"),
            func.sum(case((Job.first_seen_at >= week_start, 1), else_=0)).label("week_new"),
            func.max(Job.first_seen_at).label("last_ingest"),
        ).group_by(Job.source)
    ).all()

    public_rows = db.execute(
        select(Job.source, func.count()).where(public_job_condition()).group_by(Job.source)
    ).all()
    public_totals = {source: count for source, count in public_rows}

    # Latest run per source via Python reduction: DISTINCT ON is
    # Postgres-only while the test suite runs on SQLite.
    recent_runs = list(
        db.scalars(select(CollectorRun).order_by(CollectorRun.started_at.desc()).limit(5000)).all()
    )
    last_run_by_source: dict[str, tuple[str | None, datetime | None]] = {}
    for run in recent_runs:
        if run.source not in last_run_by_source:
            last_run_by_source[run.source] = (run.status, run.started_at)

    sources = [
        CollectionSourceRow(
            source=source,
            internal_total=total,
            public_total=public_totals.get(source, 0),
            today_new_bj=today_new or 0,
            seven_day_new_bj=week_new or 0,
            last_ingest_at=last_ingest,
            last_run_status=last_run_by_source.get(source, (None, None))[0],
            last_run_at=last_run_by_source.get(source, (None, None))[1],
        )
        for source, total, today_new, week_new, last_ingest in sorted(rows)
    ]

    batches = list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.completed_at >= today_start, ImportBatch.completed_at <= now)
            .order_by(ImportBatch.started_at.desc())
        ).all()
    )
    agg: dict[str, dict] = {}
    for batch in batches:
        row = agg.setdefault(
            batch.source,
            {
                "source": batch.source,
                "today_accepted_bj": 0,
                "today_duplicate_bj": 0,
                "today_rejected_bj": 0,
            },
        )
        row["today_accepted_bj"] += batch.accepted_count or 0
        row["today_duplicate_bj"] += batch.duplicate_count or 0
        row["today_rejected_bj"] += batch.rejected_count or 0

    latest_ids = select(func.max(ImportBatch.id)).group_by(ImportBatch.source)
    latest_batch = {
        batch.source: batch
        for batch in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(latest_ids))).all()
    }

    devices = list(
        db.scalars(select(CollectorDevice).where(CollectorDevice.revoked_at.is_(None))).all()
    )

    def _device_state(source: str) -> tuple[str, datetime | None]:
        candidates = [d for d in devices if d.platform and source.startswith(d.platform)]
        if not candidates:
            return "none", None
        freshest = max(
            (_utc(d.last_seen_at) for d in candidates if d.last_seen_at is not None),
            default=None,
        )
        if freshest is None:
            return "offline", None
        age = (now - freshest).total_seconds()
        if 0 <= age <= COLLECTOR_HEARTBEAT_STALE_SECONDS:
            return "online", freshest
        return "stale", freshest

    local_uploads = []
    for source in sorted(
        set(agg) | set(latest_batch) | {"seek_user_import", "linkedin_user_import"}
    ):
        row = agg.get(
            source,
            {
                "source": source,
                "today_accepted_bj": 0,
                "today_duplicate_bj": 0,
                "today_rejected_bj": 0,
            },
        )
        batch = latest_batch.get(source)
        state, last_seen = _device_state(source)
        local_uploads.append(
            CollectionLocalUploadRow(
                **row,
                last_batch_id=batch.id if batch else None,
                last_batch_status=batch.status if batch else None,
                last_batch_accepted=batch.accepted_count if batch else None,
                last_batch_duplicate=batch.duplicate_count if batch else None,
                last_batch_rejected=batch.rejected_count if batch else None,
                last_batch_completed_at=batch.completed_at if batch else None,
                collector_state=state,
                collector_last_seen_at=last_seen,
            )
        )

    recent = (
        db.execute(select(Job.first_seen_at).where(Job.first_seen_at >= week_start)).scalars().all()
    )
    trend_counts: dict[str, int] = {}
    for seen in recent:
        day = _utc(seen).astimezone(BJT).date().isoformat()
        trend_counts[day] = trend_counts.get(day, 0) + 1
    trend = [
        CollectionTrendPoint(date=day, new_jobs=trend_counts.get(day, 0))
        for day in sorted(trend_counts)
    ]

    return CollectionOverviewResponse(
        generated_at=now,
        daily_target_per_source=DAILY_TARGET_PER_SOURCE,
        sources=sources,
        local_uploads=local_uploads,
        seven_day_trend=trend,
    )
