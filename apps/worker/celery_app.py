"""Celery application: parallel, retrying ingestion backed by Redis.

Run with::

    celery -A apps.worker.celery_app worker --loglevel=info
    celery -A apps.worker.celery_app beat   --loglevel=info

APScheduler (``python -m apps.worker.main schedule``) remains available as a
no-Redis fallback; do not run both schedulers against the same database at the
same time or jobs will be collected twice.
"""

from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from apps.api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "jobagg",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    enable_utc=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=60,
)

beat_schedule: dict = {}
if str(settings.collect_schedule).lower() == "interval":
    beat_schedule["collect-and-alert"] = {
        "task": "jobagg.collect_all",
        "schedule": timedelta(minutes=settings.collect_interval_minutes),
    }
else:
    # Daily collection at a fixed local time (default 12:00 in TIMEZONE).
    beat_schedule["daily-collect"] = {
        "task": "jobagg.collect_all",
        "schedule": crontab(minute=settings.collect_minute, hour=settings.collect_hour),
    }

beat_schedule["daily-digest"] = {
    "task": "jobagg.daily_digest",
    "schedule": crontab(minute=30, hour=settings.digest_hour_utc),
}
beat_schedule["daily-sweep"] = {
    "task": "jobagg.sweep_stale",
    "schedule": crontab(minute=0, hour=(settings.digest_hour_utc + 1) % 24),
}

# Keep the OpenSearch index fresh when that backend is enabled.
if str(settings.search_backend).lower() == "opensearch":
    beat_schedule["reindex"] = {
        "task": "jobagg.reindex",
        "schedule": timedelta(minutes=30),
    }

celery_app.conf.beat_schedule = beat_schedule

__all__ = ["celery_app", "settings"]
