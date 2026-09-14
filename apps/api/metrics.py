"""Prometheus metrics for the API, collectors and the import gateway.

Metric names follow the roadmap:

``http_request_duration_seconds``, ``collector_runs_total``,
``collector_jobs_total``, ``collector_parse_errors_total``,
``collector_http_errors_total``, ``collector_last_success_timestamp``,
``queue_depth``, ``job_freshness_seconds``, ``webhook_delivery_total``,
``import_batch_jobs_total``.

Labels are deliberately low-cardinality: HTTP routes use the matched route
template, not the raw path.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger("jobagg.metrics")

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "HTTP requests processed", ["method", "route", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
COLLECTOR_RUNS_TOTAL = Counter(
    "collector_runs_total", "Collector runs by source and status", ["source", "status"]
)
COLLECTOR_JOBS_TOTAL = Counter(
    "collector_jobs_total", "Jobs processed by collector action", ["source", "action"]
)
COLLECTOR_PARSE_ERRORS_TOTAL = Counter(
    "collector_parse_errors_total", "Collector rows that could not be persisted", ["source"]
)
COLLECTOR_HTTP_ERRORS_TOTAL = Counter(
    "collector_http_errors_total", "Upstream HTTP error responses by status code", ["source", "code"]
)
COLLECTOR_LAST_SUCCESS = Gauge(
    "collector_last_success_timestamp", "Unix time of the last successful collector run", ["source"]
)
IMPORT_BATCH_JOBS_TOTAL = Counter(
    "import_batch_jobs_total", "Imported jobs by outcome", ["result"]
)
WEBHOOK_DELIVERY_TOTAL = Counter(
    "webhook_delivery_total", "Saved-search webhook deliveries", ["result"]
)
JOB_FRESHNESS_SECONDS = Gauge(
    "job_freshness_seconds", "Seconds since the newest public job was last seen"
)
QUEUE_DEPTH = Gauge(
    "queue_depth", "Pending Celery broker messages per queue", ["queue"]
)

_ACTION_KEYS = {
    "seen": "seen",
    "inserted": "inserted",
    "updated": "updated",
    "duplicates": "duplicate",
    "errors": "error",
}


def record_http(method: str, route: str | None, status: int, duration: float) -> None:
    route_name = route or "unmatched"
    HTTP_REQUESTS_TOTAL.labels(method, route_name, str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method, route_name).observe(max(duration, 0.0))


def record_run(source: str, status: str, stats: dict) -> None:
    COLLECTOR_RUNS_TOTAL.labels(source, status).inc()
    for key, action in _ACTION_KEYS.items():
        value = int(stats.get(key, 0) or 0)
        if value:
            COLLECTOR_JOBS_TOTAL.labels(source, action).inc(value)
    errors = int(stats.get("errors", 0) or 0)
    if errors:
        COLLECTOR_PARSE_ERRORS_TOTAL.labels(source).inc(errors)
    if status == "success":
        COLLECTOR_LAST_SUCCESS.labels(source).set(time.time())


def record_http_error(source: str, status_code: int) -> None:
    COLLECTOR_HTTP_ERRORS_TOTAL.labels(source, str(status_code)).inc()


def record_import(*, accepted: int = 0, duplicate: int = 0, rejected: int = 0) -> None:
    for result, value in (
        ("accepted", accepted),
        ("duplicate", duplicate),
        ("rejected", rejected),
    ):
        if value:
            IMPORT_BATCH_JOBS_TOTAL.labels(result).inc(value)


def record_webhook(result: str) -> None:
    WEBHOOK_DELIVERY_TOTAL.labels(result).inc()


def update_runtime_gauges(db, redis_url: str | None = None, queues: tuple[str, ...] = ("celery",)) -> None:
    """Refresh gauges that are only meaningful at scrape time."""
    from sqlalchemy import func, select

    from apps.api.models import Job

    latest = db.scalar(
        select(func.max(Job.last_seen_at)).where(
            Job.is_active.is_(True), Job.visibility == "public"
        )
    )
    if latest is not None:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=dt.UTC)
        age = (dt.datetime.now(dt.UTC) - latest).total_seconds()
        JOB_FRESHNESS_SECONDS.set(max(age, 0.0))

    if not redis_url:
        return
    try:
        import redis

        client = redis.Redis.from_url(
            redis_url, socket_connect_timeout=1.0, socket_timeout=1.0
        )
        for queue in queues:
            QUEUE_DEPTH.labels(queue).set(int(client.llen(queue) or 0))
    except Exception as exc:  # noqa: BLE001 - metrics must never break a scrape
        logger.debug("queue depth unavailable: %s", exc)


__all__ = [
    "COLLECTOR_HTTP_ERRORS_TOTAL",
    "COLLECTOR_JOBS_TOTAL",
    "COLLECTOR_LAST_SUCCESS",
    "COLLECTOR_PARSE_ERRORS_TOTAL",
    "COLLECTOR_RUNS_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION",
    "IMPORT_BATCH_JOBS_TOTAL",
    "JOB_FRESHNESS_SECONDS",
    "QUEUE_DEPTH",
    "WEBHOOK_DELIVERY_TOTAL",
    "record_http",
    "record_http_error",
    "record_import",
    "record_run",
    "record_webhook",
    "update_runtime_gauges",
]
