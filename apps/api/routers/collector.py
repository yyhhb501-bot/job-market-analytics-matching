"""Collection controls: per-source status, pause and resume.

The status endpoint powers the management page (weekly target progress, per
source: last outcome, pause state, today's visit budget). Pause/resume are
operator actions guarded by the API key; a resume only clears the pause —
it never bypasses the visit budget or the run mutex.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import CollectorRun, Job, SourceControl, SourceVisitCounter, utcnow
from apps.api.security import require_api_key
from apps.api.source_authorization import public_job_condition
from apps.worker.pipeline import resume_source

router = APIRouter(tags=["collector"])


def _week_start() -> dt.datetime:
    """Monday 00:00 UTC of the current ISO week."""
    now = utcnow()
    monday = now.date() - dt.timedelta(days=now.weekday())
    return dt.datetime.combine(monday, dt.time.min, tzinfo=dt.UTC)


@router.get("/collector/status")
def collector_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    week_start = _week_start()
    public = public_job_condition()

    # Weekly unique-job progress (valid postings: active, complete core fields).
    valid_base = (
        public,
        Job.is_active.is_(True),
        Job.title.is_not(None),
        Job.title != "",
        Job.company.is_not(None),
        Job.company != "",
        Job.canonical_url.is_not(None),
        Job.canonical_url != "",
    )
    week_new = int(
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(*valid_base, Job.first_seen_at >= week_start)
        )
        or 0
    )
    week_by_source = dict(
        db.execute(
            select(Job.source, func.count())
            .where(*valid_base, Job.first_seen_at >= week_start)
            .group_by(Job.source)
        ).all()
    )

    today = utcnow().date()
    visits: dict[str, dict] = {}
    for row in db.scalars(
        select(SourceVisitCounter).where(SourceVisitCounter.day == today)
    ).all():
        visits[row.source] = {
            "page_visits": row.page_visits,
            "detail_visits": row.detail_visits,
        }

    controls = {
        control.source: control
        for control in db.scalars(select(SourceControl)).all()
    }

    last_runs: dict[str, CollectorRun] = {}
    recent = db.scalars(
        select(CollectorRun).order_by(CollectorRun.id.desc()).limit(400)
    ).all()
    for run in recent:
        if run.source not in last_runs and run.status != "skipped":
            last_runs[run.source] = run

    sources: list[dict] = []
    known = sorted(set(visits) | set(controls) | set(last_runs))
    for source in known:
        control = controls.get(source)
        run = last_runs.get(source)
        counter = visits.get(source, {})
        sources.append(
            {
                "source": source,
                "paused": bool(control and control.paused),
                "pause_reason": control.pause_reason if control else None,
                "paused_at": control.paused_at if control else None,
                "note": control.note if control else None,
                "last_run": {
                    "id": run.id,
                    "status": run.status,
                    "stopped_reason": run.stopped_reason,
                    "jobs_inserted": run.jobs_inserted,
                    "error": run.error,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                }
                if run
                else None,
                "today_page_visits": counter.get("page_visits", 0),
                "today_detail_visits": counter.get("detail_visits", 0),
                "daily_page_visit_limit": settings.daily_page_visit_limit,
                "daily_detail_visit_limit": settings.daily_detail_visit_limit,
            }
        )

    return {
        "weekly": {
            "target": settings.weekly_unique_target,
            "new_jobs": week_new,
            "by_source": week_by_source,
            "week_start": week_start.isoformat(),
        },
        "sources": sources,
    }


class PauseRequest(BaseModel):
    reason: str = "manual"
    note: str | None = None


@router.post(
    "/collector/{source}/pause",
    dependencies=[Depends(require_api_key)],
)
def pause_collector(source: str, payload: PauseRequest, db: Session = Depends(get_db)) -> dict:
    if len(source) > 50 or not source.strip():
        raise HTTPException(status_code=422, detail="invalid source name")
    control = db.scalar(select(SourceControl).where(SourceControl.source == source))
    if control is None:
        control = SourceControl(source=source)
        db.add(control)
    control.paused = True
    control.pause_reason = payload.reason[:30]
    control.paused_at = utcnow()
    control.note = payload.note
    db.commit()
    return {"source": source, "paused": True, "pause_reason": control.pause_reason}


@router.post(
    "/collector/{source}/resume",
    dependencies=[Depends(require_api_key)],
)
def resume_collector(source: str, db: Session = Depends(get_db)) -> dict:
    if len(source) > 50 or not source.strip():
        raise HTTPException(status_code=422, detail="invalid source name")
    resumed = resume_source(db, source)
    if not resumed:
        raise HTTPException(status_code=409, detail=f"source {source} is not paused")
    return {"source": source, "paused": False}


__all__ = ["router"]
