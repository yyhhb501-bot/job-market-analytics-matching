"""Collector run monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import CollectorRun, Job
from apps.api.schemas import (
    CollectorRunOut,
    RunsSummaryResponse,
    SourceHealthOut,
    SourceRunSummary,
)

router = APIRouter(tags=["runs"])


@router.get("/runs/summary", response_model=RunsSummaryResponse)
def runs_summary(
    db: Session = Depends(get_db), limit: int = Query(default=2000, ge=1, le=10000)
) -> RunsSummaryResponse:
    runs = list(
        db.scalars(select(CollectorRun).order_by(CollectorRun.id.desc()).limit(limit)).all()
    )
    aggregated: dict[str, dict] = {}
    for run in runs:
        row = aggregated.setdefault(
            run.source,
            {
                "source": run.source,
                "runs": 0,
                "successes": 0,
                "errors": 0,
                "last_status": None,
                "last_run_at": None,
                "jobs_seen": 0,
                "jobs_inserted": 0,
            },
        )
        row["runs"] += 1
        if run.status == "success":
            row["successes"] += 1
        elif run.status == "error":
            row["errors"] += 1
        if row["last_status"] is None:
            row["last_status"] = run.status
            row["last_run_at"] = run.started_at
        row["jobs_seen"] += run.jobs_seen or 0
        row["jobs_inserted"] += run.jobs_inserted or 0

    sources = [
        SourceRunSummary(**value)
        for value in sorted(aggregated.values(), key=lambda item: item["source"])
    ]
    return RunsSummaryResponse(total_runs=len(runs), sources=sources)


@router.get("/health/sources", response_model=list[SourceHealthOut])
def source_health(
    db: Session = Depends(get_db), limit: int = Query(default=5000, ge=1, le=20000)
) -> list[SourceHealthOut]:
    """Per-source health incl. success rate, zero-result streaks and drift."""
    totals = dict(db.execute(select(Job.source, func.count()).group_by(Job.source)).all())
    actives = dict(
        db.execute(
            select(Job.source, func.count())
            .where(Job.is_active.is_(True))
            .group_by(Job.source)
        ).all()
    )
    today_col = func.date(Job.first_seen_at)
    today_added = dict(
        db.execute(
            select(Job.source, func.count())
            .where(today_col == func.current_date())
            .group_by(Job.source)
        ).all()
    )

    runs = list(
        db.scalars(select(CollectorRun).order_by(CollectorRun.id.desc()).limit(limit)).all()
    )
    aggregated: dict[str, dict] = {}
    for run in runs:
        row = aggregated.setdefault(
            run.source,
            {
                "source": run.source,
                "runs": 0,
                "successes": 0,
                "errors": 0,
                "last_status": None,
                "last_run_at": None,
                "last_job_count": 0,
                "consecutive_zero_runs": 0,
                "tracking_zero": True,
                "max_seen": 0,
            },
        )
        row["runs"] += 1
        if run.status == "success":
            row["successes"] += 1
        elif run.status == "error":
            row["errors"] += 1
        row["max_seen"] = max(row["max_seen"], run.jobs_seen or 0)
        if row["last_status"] is None:
            row["last_status"] = run.status
            row["last_run_at"] = run.started_at
            row["last_job_count"] = run.jobs_seen or 0
        if row["tracking_zero"]:
            if (run.jobs_seen or 0) == 0:
                row["consecutive_zero_runs"] += 1
            else:
                row["tracking_zero"] = False

    results: list[SourceHealthOut] = []
    for source, row in aggregated.items():
        results.append(
            SourceHealthOut(
                source=source,
                runs=row["runs"],
                successes=row["successes"],
                errors=row["errors"],
                success_rate=round(row["successes"] / row["runs"], 3) if row["runs"] else 0.0,
                last_status=row["last_status"],
                last_run_at=row["last_run_at"],
                last_job_count=row["last_job_count"],
                consecutive_zero_runs=row["consecutive_zero_runs"],
                jobs_total=int(totals.get(source, 0)),
                jobs_active=int(actives.get(source, 0)),
                jobs_added_today=int(today_added.get(source, 0)),
                schema_drift=(
                    row["last_job_count"] == 0
                    and row["max_seen"] > 0
                    and row["consecutive_zero_runs"] >= 3
                ),
            )
        )
    results.sort(key=lambda item: item.jobs_total, reverse=True)
    return results


@router.get("/runs", response_model=list[CollectorRunOut])
def list_runs(
    db: Session = Depends(get_db),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[CollectorRun]:
    statement = select(CollectorRun)
    if source:
        statement = statement.where(CollectorRun.source == source)
    if status:
        statement = statement.where(CollectorRun.status == status)
    statement = statement.order_by(
        CollectorRun.started_at.desc().nullslast(), CollectorRun.id.desc()
    ).limit(limit)
    return list(db.scalars(statement).all())
