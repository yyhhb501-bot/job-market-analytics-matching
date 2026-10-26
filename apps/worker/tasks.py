"""Celery tasks.

Core logic lives in plain ``*_sync`` helpers so it can be unit-tested without a
broker; the task objects are thin wrappers adding retries and fan-out.

Retry policy for ``collect_source``:

- transient failures (network/timeout/5xx and HTTP 429) retry with
  exponential backoff + jitter; a 429's ``Retry-After`` wins when present;
- access blocks (CAPTCHA / 401/403 / login wall) never retry — the pipeline
  has already paused the source for a human to resume;
- partial runs (budget stops, some items/boards failed) are reported and left
  for the next scheduled run instead of being forced complete.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
from datetime import timedelta
from typing import Any

from celery import chain, chord, group
from sqlalchemy import func, or_, select, update

from apps.api.alerts import notify_saved_searches, run_active_saved_searches
from apps.api.config import Settings, get_settings
from apps.api.database import get_session_factory
from apps.api.models import CollectorRun, Job, utcnow
from apps.api.source_authorization import public_job_condition
from apps.worker.celery_app import celery_app
from apps.worker.pipeline import run_collector
from collectors.base import (
    AccessBlockedError,
    CollectorError,
    RateLimitedError,
    RetryableCollectorError,
    SearchParams,
)
from collectors.registry import build_collectors
from packages.enrichment import classify_occupation, classify_seniority, enrich_job
from packages.job_schema import ATS_SOURCES
from packages.llm import build_chat_client, build_summary_prompt
from packages.search import build_search_backend, job_to_document
from packages.seek_policy import SEEK_DAILY_TARGET, SEEK_HOURLY_LIMIT
from packages.semantic import build_embedder, embed_text

logger = logging.getLogger("jobagg.tasks")

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 60.0
BACKOFF_CAP_SECONDS = 900.0
BACKOFF_JITTER_SECONDS = 30.0


def retry_backoff(retries: int) -> float:
    """Exponential backoff with jitter, capped at 15 minutes."""
    base = min(BACKOFF_BASE_SECONDS * (2 ** max(retries, 0)), BACKOFF_CAP_SECONDS)
    return base + random.uniform(0, BACKOFF_JITTER_SECONDS)


def retry_decision(exc: Exception, retries: int) -> tuple[bool, float]:
    """Decide whether a failed collection should retry, and after how long.

    Returns ``(should_retry, countdown_seconds)``. Access blocks never retry.
    """
    if isinstance(exc, AccessBlockedError):
        return False, 0.0
    if isinstance(exc, RateLimitedError) and exc.retry_after:
        return True, float(exc.retry_after)
    if isinstance(exc, CollectorError | RetryableCollectorError):
        return retries < MAX_RETRIES, retry_backoff(retries)
    return retries < MAX_RETRIES, retry_backoff(retries)


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


SEARCH_SOURCES = {"jobspy", "seek", "adzuna", "usajobs"}
COUNTRY_SOURCES = {"jobspy", "adzuna"}


def default_params(settings: Settings) -> dict:
    return {
        "keywords": settings.collect_keywords,
        "location": settings.collect_location,
        "country": settings.collect_country,
        "results_wanted": settings.collect_results,
        "extra": {
            "sites": [site.strip() for site in settings.collect_sites.split(",") if site.strip()]
        },
    }


def expand_collector_specs(
    settings: Settings, params: dict | None = None, only_names: list[str] | None = None
) -> list[tuple[str, dict]]:
    """Expand one run into per-source specs.

    Full-board ATS sources run once. Keyword search sources (JobSpy/Adzuna/...)
    run once per comma-separated keyword, and per country for JobSpy/Adzuna, so
    ``COLLECT_KEYWORDS="nurse,teacher,driver"`` covers many occupations.
    """
    base = params or default_params(settings)
    names = list(only_names) if only_names else enabled_source_names(settings)
    search = [name for name in names if name in SEARCH_SOURCES]
    rest = [name for name in names if name not in SEARCH_SOURCES]

    specs: list[tuple[str, dict]] = [(name, base) for name in rest]
    keywords = [k.strip() for k in str(base.get("keywords") or "").split(",") if k.strip()]
    if keywords:
        for name in search:
            if name in COUNTRY_SOURCES:
                countries = (
                    [c.strip() for c in str(base.get("country") or "").split(",") if c.strip()]
                    or settings.country_list
                    or [None]
                )
            else:
                countries = [None]
            for keyword in keywords:
                for country in countries:
                    spec = dict(base)
                    spec["keywords"] = keyword
                    if country:
                        spec["country"] = country
                    specs.append((name, spec))
    else:
        specs += [(name, base) for name in search]

    overrides = getattr(settings, "results_override_map", {})
    if overrides:
        specs = [
            (name, {**spec, "results_wanted": overrides[name]} if name in overrides else spec)
            for name, spec in specs
        ]
    return specs


def enabled_source_names(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    return [collector.name for collector in build_collectors(settings)]


def daily_new_target(settings: Settings, source_name: str) -> int:
    """Configured daily new-job target for a platform source (0 = unlimited)."""
    targets = {
        "seek": settings.seek_daily_new_target,
        "linkedin": settings.linkedin_daily_new_target,
    }
    return max(int(targets.get(source_name, 0) or 0), 0)


def clamp_to_daily_target(
    session: Any, settings: Settings, source_name: str, results_wanted: int
) -> int | None:
    """Cap ``results_wanted`` by today's remaining new-job target.

    Returns None when the target is already met (nothing to collect today).
    Platform sources only; user-private imports are not capped.
    """
    target = daily_new_target(settings, source_name)
    if target <= 0:
        return max(int(results_wanted), 0)
    inserted_today = int(
        session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.source == source_name,
                Job.visibility == "public",
                func.date(Job.first_seen_at) == func.current_date(),
            )
        )
        or 0
    )
    return max(target - inserted_today, 0)


def collect_source_sync(source_name: str, params: dict | None = None) -> dict:
    settings = get_settings()
    collectors = {collector.name: collector for collector in build_collectors(settings)}
    collector = collectors.get(source_name)
    if collector is None:
        logger.warning("collect_source: %s is not enabled; skipping", source_name)
        return {"source": source_name, "skipped": True, "reason": "not enabled"}
    search = params_from_dict(params)
    with get_session_factory()() as session:
        if search.extra.get("plan") == "au_nurse":
            remaining = au_nurse_remaining(session, source_name, search.results_wanted)
        else:
            remaining = clamp_to_daily_target(session, settings, source_name, search.results_wanted)
        if remaining is not None:
            if remaining <= 0:
                logger.info(
                    "collect_source: %s daily new-job target already met; skipping",
                    source_name,
                )
                # Record the gate so the management page can show it.
                session.add(
                    CollectorRun(
                        source=source_name,
                        status="skipped",
                        stopped_reason="daily_target_met",
                        error="daily new-job target met",
                        started_at=utcnow(),
                        finished_at=utcnow(),
                    )
                )
                session.commit()
                return {
                    "source": source_name,
                    "skipped": True,
                    "reason": "daily new-job target met",
                }
            search.results_wanted = remaining
    stats = asyncio.run(run_collector(collector, search, get_session_factory()))
    return stats.as_dict()


def au_nurse_remaining(session: Any, source_name: str, requested: int) -> int:
    """Return the remaining per-day/per-hour allowance for the RN plan."""
    now = utcnow().astimezone(dt.UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour = now.replace(minute=0, second=0, microsecond=0)
    base = (
        Job.source == source_name,
        Job.country == "AU",
        Job.visibility == "public",
        Job.duplicate_of.is_(None),
    )
    today = int(
        session.scalar(select(func.count()).select_from(Job).where(*base, Job.first_seen_at >= day))
        or 0
    )
    this_hour = int(
        session.scalar(
            select(func.count()).select_from(Job).where(*base, Job.first_seen_at >= hour)
        )
        or 0
    )
    return max(min(int(requested), SEEK_DAILY_TARGET - today, SEEK_HOURLY_LIMIT - this_hour), 0)


def au_nurse_plan_params(settings: Settings) -> tuple[str | None, dict | None]:
    """Select one RN keyword per hourly slot and an enabled API source."""
    allowed_sources = {"adzuna"}
    enabled = set(enabled_source_names(settings))
    source = next(
        (
            item.strip().lower()
            for item in settings.au_nurse_plan_sources.split(",")
            if item.strip().lower() in allowed_sources and item.strip().lower() in enabled
        ),
        None,
    )
    keywords = [item.strip() for item in settings.au_nurse_plan_keywords.split(",") if item.strip()]
    if source is None or not keywords:
        return None, None
    slot = int(utcnow().timestamp() // 3600) % len(keywords)
    return source, {
        "keywords": keywords[slot],
        "location": settings.au_nurse_plan_location,
        "country": settings.au_nurse_plan_country,
        "results_wanted": min(max(settings.au_nurse_plan_results_per_run, 1), SEEK_HOURLY_LIMIT),
        "extra": {"plan": "au_nurse", "nurse_only": True},
    }


@celery_app.task(name="jobagg.collect_au_nurse_plan")
def collect_au_nurse_plan() -> dict:
    """Dispatch one bounded RN batch from an explicitly enabled API source."""
    settings = get_settings()
    if not settings.au_nurse_plan_enabled:
        return {"plan": "au_nurse", "skipped": True, "reason": "plan disabled"}
    source, params = au_nurse_plan_params(settings)
    if source is None or params is None:
        return {
            "plan": "au_nurse",
            "skipped": True,
            "reason": "no enabled API-backed source; configure Adzuna credentials",
        }
    result = collect_source.delay(source, params)
    return {"plan": "au_nurse", "source": source, "dispatched": True, "task_id": result.id}


def group_specs_by_source(specs: list[tuple[str, dict]]) -> list[list[tuple[str, dict]]]:
    """Group per-source specs so one source's specs dispatch serially.

    The run mutex rejects concurrent runs of the same source, so multi-keyword
    / multi-country expansions of a search source must run one after another
    while different sources still fan out in parallel.
    """
    grouped: dict[str, list[tuple[str, dict]]] = {}
    for name, spec in specs:
        grouped.setdefault(name, []).append((name, spec))
    return list(grouped.values())


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
            job.occupation_group = (
                job.occupation_group or enriched.get("occupation_group") or "other"
            )
            job.seniority = job.seniority or enriched.get("seniority")
            updated += 1

        # Jobs whose occupation could not be classified still get "other" so the
        # backfill is idempotent and the CLI loop terminates.
        pending_occupation = session.scalars(
            select(Job).where(Job.occupation_group.is_(None)).limit(batch_size)
        ).all()
        for job in pending_occupation:
            job.occupation_group = classify_occupation(job.title, job.description) or "other"
            job.seniority = job.seniority or classify_seniority(job.title)
            updated += 1
        session.commit()

        if with_embeddings:
            embedder = build_embedder(get_settings())
            if embedder is not None:
                pending = session.scalars(
                    select(Job)
                    .where(
                        or_(
                            Job.embedding.is_(None),
                            Job.embedding_model.is_(None),
                            Job.embedding_model != embedder.name,
                        ),
                        Job.description.is_not(None),
                    )
                    .limit(batch_size)
                ).all()
                if pending:
                    vectors = asyncio.run(
                        embedder.embed([embed_text(job.title, job.description) for job in pending])
                    )
                    for job, vector in zip(pending, vectors):
                        job.embedding = vector
                        job.embedding_model = embedder.name
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
                    client.complete(build_summary_prompt(job.title, job.description, max_chars))
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
                select(Job)
                .where(Job.id > last_id, public_job_condition())
                .order_by(Job.id)
                .limit(batch_size)
            ).all()
            if not jobs:
                break
            backend.index_jobs([job_to_document(job) for job in jobs])
            indexed += len(jobs)
            last_id = jobs[-1].id
    return {"indexed": indexed}


@celery_app.task(bind=True, name="jobagg.collect_source", max_retries=MAX_RETRIES)
def collect_source(self, source_name: str, params: dict | None = None) -> dict:
    try:
        return collect_source_sync(source_name, params)
    except Exception as exc:  # noqa: BLE001 - classified below
        should_retry, countdown = retry_decision(exc, self.request.retries)
        if not should_retry:
            outcome = "blocked" if isinstance(exc, AccessBlockedError) else "retryable"
            logger.error(
                "collect_source %s failed without retry (%s): %s",
                source_name,
                type(exc).__name__,
                exc,
            )
            return {
                "source": source_name,
                "outcome": outcome,
                "error": f"{type(exc).__name__}: {exc}",
            }
        logger.warning(
            "collect_source %s retrying in %.0fs (%s): %s",
            source_name,
            countdown,
            type(exc).__name__,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc


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


def _dispatch_header(specs: list[tuple[str, dict]]) -> list:
    """Build fan-out signatures: one chain per source, parallel across sources.

    Same-source specs run serially (the run mutex would otherwise skip the
    later keyword/country expansions), different sources run concurrently.
    """
    header: list = []
    for source_group in group_specs_by_source(specs):
        if len(source_group) == 1:
            name, spec = source_group[0]
            header.append(collect_source.si(name, spec))
        else:
            # Immutable signatures (.si): a chain prepends the previous
            # task's result to the next call, which collect_source does not
            # accept — serial execution must not change the arguments.
            header.append(chain(*[collect_source.si(name, spec) for name, spec in source_group]))
    return header


@celery_app.task(name="jobagg.collect_all")
def collect_all(params: dict | None = None) -> dict:
    settings = get_settings()
    specs = expand_collector_specs(settings, params)
    if not specs:
        logger.warning("collect_all: no collectors enabled")
        return {"sources": [], "dispatched": 0}

    header = _dispatch_header(specs)
    result = chord(header)(evaluate_alerts.s(lookback_hours=24))
    return {
        "sources": sorted({name for name, _ in specs}),
        "dispatched": len(specs),
        "chord_id": getattr(result, "id", None),
    }


@celery_app.task(name="jobagg.collect_scope")
def collect_scope(scope: str = "all") -> dict:
    """Run a subset of collectors: ``ats`` (boards), ``hot`` (hot keywords)."""
    settings = get_settings()
    names = enabled_source_names(settings)
    if scope == "ats":
        specs = [(name, default_params(settings)) for name in names if name in ATS_SOURCES]
    elif scope == "hot":
        params = default_params(settings)
        params["keywords"] = settings.collect_hot_keywords
        hot = [name for name in names if name in SEARCH_SOURCES]
        specs = expand_collector_specs(settings, params, only_names=hot)
    else:
        specs = expand_collector_specs(settings)

    if not specs:
        return {"scope": scope, "dispatched": 0}
    header = _dispatch_header(specs)
    result = group(header).apply_async()
    return {"scope": scope, "dispatched": len(specs), "group_id": getattr(result, "id", None)}


@celery_app.task(name="jobagg.verify_boards")
def verify_boards() -> dict:
    from apps.api.boards import verify_all_boards

    settings = get_settings()
    with get_session_factory()() as session:
        return asyncio.run(verify_all_boards(session, settings))


@celery_app.task(bind=True, name="jobagg.nightly_local_import", max_retries=3)
def nightly_local_import(self) -> dict:
    from apps.worker.nightly_import import sync_nightly_imports

    try:
        return sync_nightly_imports()
    except Exception as exc:
        logger.exception("Nightly local import failed")
        raise self.retry(exc=exc, countdown=30 * 60)


__all__ = [
    "au_nurse_plan_params",
    "au_nurse_remaining",
    "clamp_to_daily_target",
    "collect_all",
    "collect_au_nurse_plan",
    "group_specs_by_source",
    "collect_scope",
    "collect_source",
    "collect_source_sync",
    "daily_digest",
    "default_params",
    "enabled_source_names",
    "expand_collector_specs",
    "enrich_jobs",
    "enrich_jobs_sync",
    "evaluate_alerts",
    "evaluate_alerts_sync",
    "generate_summaries",
    "generate_summaries_sync",
    "nightly_local_import",
    "params_from_dict",
    "reindex_jobs",
    "retry_backoff",
    "retry_decision",
    "reindex_jobs_sync",
    "sweep_stale_jobs",
    "sweep_stale_jobs_sync",
    "verify_boards",
]
