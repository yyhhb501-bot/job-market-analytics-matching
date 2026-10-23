from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from apps.api.config import Settings
from apps.api.models import Board, Job, utcnow
from apps.worker import tasks
from apps.worker.pipeline import apply_board_missing_sweep, persist_job, persist_job_row
from packages.job_schema import NormalizedJob


def make_job(**overrides) -> NormalizedJob:
    data = {
        "source": "greenhouse",
        "source_job_id": "life-1",
        "title": "Data Engineer",
        "company": "Acme",
        "description": "Python pipelines",
        "city": "Austin",
        "country": "US",
    }
    data.update(overrides)
    return NormalizedJob(**data)


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
    board = Board(provider="greenhouse", board_token="acme")
    session.add(board)
    session.commit()
    persist_job(
        session, make_job(source_job_id="life-1"), run_id=1, source_board_id=board.id
    )
    session.commit()

    apply_board_missing_sweep(session, [board.id], run_id=2, threshold=2)
    apply_board_missing_sweep(session, [board.id], run_id=3, threshold=2)

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is False
    assert job.inactive_reason == "missing"


def test_board_missing_sweep_ignores_seen_jobs(session):
    board = Board(provider="greenhouse", board_token="acme")
    session.add(board)
    session.commit()
    persist_job(
        session, make_job(source_job_id="life-1"), run_id=5, source_board_id=board.id
    )
    session.commit()

    result = apply_board_missing_sweep(session, [board.id], run_id=5, threshold=1)

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.is_active is True
    assert result["closed"] == 0


def test_failed_board_never_sweeps_other_boards_jobs(session):
    """A failing board's missing jobs must never be aged out."""
    ok_board = Board(provider="greenhouse", board_token="healthy")
    down_board = Board(provider="greenhouse", board_token="broken")
    session.add_all([ok_board, down_board])
    session.commit()
    healthy_job = persist_job_row(
        session,
        make_job(source_job_id="healthy-1", title="Engineer A"),
        run_id=1,
        source_board_id=ok_board.id,
    )[1].id
    downed_job = persist_job_row(
        session,
        make_job(source_job_id="down-1", title="Engineer B"),
        run_id=1,
        source_board_id=down_board.id,
    )[1].id
    session.commit()

    # Only the healthy board completed run 2; its jobs were all seen again.
    persist_job(
        session,
        make_job(source_job_id="healthy-1", title="Engineer A"),
        run_id=2,
        source_board_id=ok_board.id,
    )
    result = apply_board_missing_sweep(session, [ok_board.id], run_id=2, threshold=1)

    session.expire_all()
    ok_row = session.get(Job, healthy_job)
    down_row = session.get(Job, downed_job)
    assert ok_row.is_active is True
    assert ok_row.missing_runs == 0
    assert down_row.is_active is True
    assert down_row.missing_runs == 0
    assert result["closed"] == 0


def test_completed_board_sweeps_only_its_own_gone_jobs(session):
    """A fully-read board closes its own disappeared jobs — and nothing else."""
    board_a = Board(provider="greenhouse", board_token="alpha")
    board_b = Board(provider="greenhouse", board_token="beta")
    session.add_all([board_a, board_b])
    session.commit()
    gone_from_a = persist_job_row(
        session,
        make_job(source_job_id="a-gone", title="Engineer A"),
        run_id=1,
        source_board_id=board_a.id,
    )[1].id
    still_on_b = persist_job_row(
        session,
        make_job(source_job_id="b-here", title="Engineer B"),
        run_id=1,
        source_board_id=board_b.id,
    )[1].id
    session.commit()

    result = apply_board_missing_sweep(session, [board_a.id], run_id=2, threshold=1)

    session.expire_all()
    assert session.get(Job, gone_from_a).is_active is False
    assert session.get(Job, gone_from_a).inactive_reason == "missing"
    assert session.get(Job, still_on_b).is_active is True
    assert result["closed"] == 1


def test_jobs_without_board_attribution_are_never_swept(session):
    persist_job(session, make_job(source_job_id="legacy-1"), run_id=1)
    session.commit()

    result = apply_board_missing_sweep(session, [999], run_id=2, threshold=1)

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
