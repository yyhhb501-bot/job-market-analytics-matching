from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from apps.api.config import Settings
from apps.api.models import Job, utcnow
from apps.worker import tasks
from apps.worker.pipeline import apply_missing_sweep, persist_job
from packages.job_schema import NormalizedJob


def make_job() -> NormalizedJob:
    return NormalizedJob(
        source="test",
        source_job_id="life-1",
        title="Data Engineer",
        company="Acme",
        description="Python pipelines",
        city="Austin",
        country="US",
    )


def test_sweep_marks_stale_jobs_inactive(session_factory, session, monkeypatch):
    persist_job(session, make_job())
    session.commit()
    job = session.scalars(select(Job)).one()
    job.last_seen_at = utcnow() - timedelta(days=60)
    session.commit()

    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(stale_job_days=30))

    result = tasks.sweep_stale_jobs_sync()
    assert result["deactivated"] == 1

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is False
    assert job.inactive_reason == "stale"
    assert job.closed_at is not None


def test_board_missing_sweep_closes_after_threshold(session):
    persist_job(session, make_job(), run_id=1)
    session.commit()

    apply_missing_sweep(session, "test", run_id=2, threshold=2)
    apply_missing_sweep(session, "test", run_id=3, threshold=2)

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is False
    assert job.inactive_reason == "missing"


def test_board_missing_sweep_ignores_seen_jobs(session):
    persist_job(session, make_job(), run_id=5)
    session.commit()

    result = apply_missing_sweep(session, "test", run_id=5, threshold=1)

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is True
    assert result["closed"] == 0


def test_reseen_job_is_reactivated(session_factory, session, monkeypatch):
    persist_job(session, make_job())
    session.commit()
    job = session.scalars(select(Job)).one()
    job.is_active = False
    job.inactive_reason = "stale"
    job.closed_at = utcnow()
    job.last_seen_at = utcnow() - timedelta(days=60)
    session.commit()

    persist_job(session, make_job())
    session.commit()

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is True
    assert job.inactive_reason is None
    assert job.closed_at is None
