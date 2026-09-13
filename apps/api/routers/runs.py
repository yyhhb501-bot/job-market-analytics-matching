"""Collector run monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import CollectorRun
from apps.api.schemas import CollectorRunOut, RunsSummaryResponse, SourceRunSummary

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
