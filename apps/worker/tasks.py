"""Celery tasks.

Core logic lives in plain ``*_sync`` helpers so it can be unit-tested without a
broker; the task objects are thin wrappers adding retries and fan-out.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from celery import chord
from sqlalchemy import or_, select, update

from apps.api.alerts import notify_saved_searches, run_active_saved_searches
from apps.api.config import Settings, get_settings
from apps.api.database import get_session_factory
from apps.api.models import Job, utcnow
from apps.worker.celery_app import celery_app
from apps.worker.pipeline import run_collector
from collectors.base import SearchParams
from collectors.registry import build_collectors
from packages.enrichment import enrich_job
from packages.llm import build_chat_client, build_summary_prompt
from packages.search import build_search_backend, job_to_document
from packages.semantic import build_embedder, embed_text

logger = logging.getLogger("jobagg.tasks")


def params_from_dict(data: dict | None) -> SearchParams:
    data = data or {}
    return SearchParams(
        keywords=data.get("keywords"),
        location=data.get("location"),
        country=data.get("country"),
        results_wanted=int(data.get("results_wanted", 100)),
        remote_only=bool(data.get("remote_only", False)),
        extra=data.get("extra") or {},
    )


def default_params(settings: Settings) -> dict:
    return {
        "keywords": settings.collect_keywords,
        "location": settings.collect_location,
        "country": settings.collect_country,
        "results_wanted": settings.collect_results,
    }


def enabled_source_names(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    return [collector.name for collector in build_collectors(settings)]


def collect_source_sync(source_name: str, params: dict | None = None) -> dict:
    settings = get_settings()
    collectors = {collector.name: collector for collector in build_collectors(settings)}
    collector = collectors.get(source_name)
    if collector is None:
        logger.warning("collect_source: %s is not enabled; skipping", source_name)
        return {"source": source_name, "skipped": True, "reason": "not enabled"}
    stats = asyncio.run(
        run_collector(collector, params_from_dict(params), get_session_factory())
    )
    return stats.as_dict()


def evaluate_alerts_sync(lookback_hours: int = 24) -> dict:
    settings = get_settings()
    with get_session_factory()() as session:
        results = run_active_saved_searches(session, lookback_hours=lookback_hours)
        notified = notify_saved_searches(session, settings, results)
    return {
        "searches": len(results),
        "emails_sent": notified.get("emails_sent", 0),
        "webhooks_sent": notified.get("webhooks_sent", 0),
    }


def enrich_jobs_sync(batch_size: int = 500, with_embeddings: bool = True) -> dict:
    """Backfill skills/summary and semantic embeddings for existing jobs."""
    updated = 0
    embedded = 0
    with get_session_factory()() as session:
        pending_skills = session.scalars(
            select(Job).where(Job.skills.is_(None)).limit(batch_size)
        ).all()
        for job in pending_skills:
            enriched = enrich_job(job)
            job.skills = enriched["skills"]
            if job.summary_source != "llm":
                job.summary = enriched["summary"]
                job.summary_source = "extractive" if enriched["summary"] else None
            updated += 1
        session.commit()

        if with_embeddings:
            embedder = build_embedder(get_settings())
            if embedder is not None:
                pending = session.scalars(
                    select(Job)
                    .where(Job.embedding.is_(None), Job.description.is_not(None))
                    .limit(batch_size)
                ).all()
                if pending:
                    vectors = asyncio.run(
                        embedder.embed([embed_text(job.title, job.description) for job in pending])
                    )
                    for job, vector in zip(pending, vectors):
                        job.embedding = vector
                    session.commit()
                    embedded = len(pending)
    return {"enriched": updated, "embedded": embedded}


def generate_summaries_sync(batch_size: int = 50) -> dict:
    """Replace extractive summaries with LLM summaries when configured."""
    settings = get_settings()
    client = build_chat_client(settings)
    if client is None:
        return {"summarized": 0, "skipped": "llm summaries disabled"}
    max_chars = settings.llm_summary_max_chars

    with get_session_factory()() as session:
        jobs = session.scalars(
            select(Job)
            .where(
                or_(Job.summary_source.is_(None), Job.summary_source != "llm"),
                Job.description.is_not(None),
            )
            .order_by(Job.first_seen_at.desc())
            .limit(batch_size)
        ).all()
        if not jobs:
            return {"summarized": 0}

        async def _run_all() -> list:
            return await asyncio.gather(
                *(
                    client.complete(
                        build_summary_prompt(job.title, job.description, max_chars)
                    )
                    for job in jobs
                ),
                return_exceptions=True,
            )

        results = asyncio.run(_run_all())

    summarized = 0
    with get_session_factory()() as session:
        for job, result in zip(jobs, results):
            if isinstance(result, Exception) or not result:
                continue
            stored = session.get(Job, job.id)
            if stored is None:
                continue
            stored.summary = str(result)
            stored.summary_source = "llm"
            summarized += 1
        session.commit()
    return {"summarized": summarized}


def sweep_stale_jobs_sync(days: int | None = None) -> dict:
    """Mark jobs inactive once they have not been seen for ``days`` days."""
    settings = get_settings()
    window = settings.stale_job_days if days is None else days
    cutoff = utcnow() - timedelta(days=max(int(window), 1))
    with get_session_factory()() as session:
        result = session.execute(
            update(Job)
            .where(Job.is_active.is_(True), Job.last_seen_at < cutoff)
            .values(is_active=False, closed_at=utcnow(), inactive_reason="stale")
        )
        session.commit()
        deactivated = int(result.rowcount or 0)
    return {"deactivated": deactivated, "cutoff_days": int(window)}


def reindex_jobs_sync(batch_size: int = 1000) -> dict:
    """(Re)index every job into OpenSearch when that backend is enabled."""
    backend = build_search_backend(get_settings())
    if backend is None:
        return {"indexed": 0, "skipped": "search backend disabled"}
    backend.ensure_index()
    indexed = 0
    last_id = 0
    with get_session_factory()() as session:
        while True:
            jobs = session.scalars(
                select(Job).where(Job.id > last_id).order_by(Job.id).limit(batch_size)
            ).all()
            if not jobs:
                break
            backend.index_jobs([job_to_document(job) for job in jobs])
            indexed += len(jobs)
            last_id = jobs[-1].id
    return {"indexed": indexed}


@celery_app.task(bind=True, name="jobagg.collect_source", max_retries=3)
def collect_source(self, source_name: str, params: dict | None = None) -> dict:
    try:
        return collect_source_sync(source_name, params)
    except Exception as exc:  # noqa: BLE001 - Celery retries on any failure
        raise self.retry(exc=exc) from exc


@celery_app.task(name="jobagg.evaluate_alerts")
def evaluate_alerts(collection_results: Any = None, lookback_hours: int = 24) -> dict:
    return evaluate_alerts_sync(lookback_hours)


@celery_app.task(name="jobagg.daily_digest")
def daily_digest(lookback_hours: int = 24) -> dict:
    """Beat entry: evaluate saved searches and deliver digest emails/webhooks."""
    return evaluate_alerts_sync(lookback_hours)


@celery_app.task(name="jobagg.sweep_stale")
def sweep_stale_jobs(days: int | None = None) -> dict:
    return sweep_stale_jobs_sync(days)


@celery_app.task(name="jobagg.enrich_jobs")
def enrich_jobs(batch_size: int = 500) -> dict:
    return enrich_jobs_sync(batch_size)


@celery_app.task(name="jobagg.reindex")
def reindex_jobs(batch_size: int = 1000) -> dict:
    return reindex_jobs_sync(batch_size)


@celery_app.task(name="jobagg.generate_summaries")
def generate_summaries(batch_size: int = 50) -> dict:
    return generate_summaries_sync(batch_size)


@celery_app.task(name="jobagg.collect_all")
def collect_all(params: dict | None = None) -> dict:
    settings = get_settings()
    params = params or default_params(settings)
    names = enabled_source_names(settings)
    if not names:
        logger.warning("collect_all: no collectors enabled")
        return {"sources": [], "dispatched": 0}

    header = [collect_source.s(name, params) for name in names]
    result = chord(header)(evaluate_alerts.s(lookback_hours=24))
    return {"sources": names, "dispatched": len(names), "chord_id": getattr(result, "id", None)}


__all__ = [
    "collect_all",
    "collect_source",
    "collect_source_sync",
    "daily_digest",
    "default_params",
    "enabled_source_names",
    "enrich_jobs",
    "enrich_jobs_sync",
    "evaluate_alerts",
    "evaluate_alerts_sync",
    "generate_summaries",
    "generate_summaries_sync",
    "params_from_dict",
    "reindex_jobs",
    "reindex_jobs_sync",
    "sweep_stale_jobs",
    "sweep_stale_jobs_sync",
]
