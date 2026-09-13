from __future__ import annotations

from apps.worker.celery_app import celery_app
from apps.worker.tasks import collect_source


def test_task_runs_eagerly_without_broker():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        result = collect_source.apply(args=["not-enabled"])
        assert result.get()["skipped"] is True
    finally:
        celery_app.conf.task_always_eager = False


def test_expected_tasks_registered():
    for name in (
        "jobagg.collect_source",
        "jobagg.collect_all",
        "jobagg.evaluate_alerts",
        "jobagg.daily_digest",
        "jobagg.sweep_stale",
        "jobagg.enrich_jobs",
        "jobagg.generate_summaries",
        "jobagg.reindex",
    ):
        assert name in celery_app.tasks


def test_beat_schedule_entries():
    schedule = celery_app.conf.beat_schedule
    # Default schedule is daily collection at 12:00 local time.
    assert "daily-collect" in schedule
    assert "daily-digest" in schedule
    assert "daily-sweep" in schedule
