"""Collection pipeline: stream -> normalise -> three-layer dedup -> persist."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.config import get_settings
from apps.api.models import CollectorRun, Job
from collectors.base import BaseCollector, SearchParams
from packages.deduplication import compute_hashes
from packages.enrichment import enrich_job
from packages.job_schema import ATS_SOURCES, NormalizedJob

logger = logging.getLogger("jobagg.worker.pipeline")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class RunStats:
    source: str
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    errors: int = 0
    error: str | None = None

    def merge(self, other: RunStats) -> None:
        self.seen += other.seen
        self.inserted += other.inserted
        self.updated += other.updated
        self.duplicates += other.duplicates
        self.errors += other.errors

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "seen": self.seen,
            "inserted": self.inserted,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "error": self.error,
        }


def _job_fields(job: NormalizedJob, hashes: dict) -> dict:
    enriched = enrich_job(job)
    return {
        "skills": enriched["skills"],
        "summary": enriched["summary"],
        "summary_source": "extractive" if enriched["summary"] else None,
        "canonical_url": job.canonical_url,
        "apply_url": job.apply_url,
        "title": job.title,
        "title_normalized": hashes["title_normalized"],
        "company": job.company,
        "company_normalized": hashes["company_normalized"],
        "description": job.description,
        "description_hash": hashes["description_hash"],
        "content_hash": hashes["content_hash"],
        "dedup_key": hashes["dedup_key"],
        "canonical_url_hash": hashes["canonical_url_hash"],
        "country": job.country,
        "state": job.state,
        "city": job.city,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_period": job.salary_period,
        "posted_at": job.posted_at,
        "expires_at": job.expires_at,
        "raw_payload": job.raw_payload,
    }


def persist_job(session: Session, job: NormalizedJob, run_id: int | None = None) -> str:
    """Upsert one job. Returns ``inserted`` | ``updated`` | ``duplicate``."""
    hashes = compute_hashes(job)
    now = _utcnow()

    # Layer 1: exact (source, source_job_id)
    existing = session.scalar(
        select(Job).where(Job.source == job.source, Job.source_job_id == job.source_job_id)
    )
    if existing is not None:
        if existing.content_hash != hashes["content_hash"]:
            for key, value in _job_fields(job, hashes).items():
                setattr(existing, key, value)
            existing.updated_at = now
        existing.last_seen_at = now
        existing.is_active = True
        existing.closed_at = None
        existing.inactive_reason = None
        existing.last_seen_run_id = run_id
        existing.missing_runs = 0
        session.flush()
        return "updated"

    # Layers 2 & 3: same posting via a different link / cross-posted elsewhere
    match = None
    if hashes["canonical_url_hash"]:
        match = session.scalar(
            select(Job).where(
                Job.canonical_url_hash == hashes["canonical_url_hash"],
                Job.duplicate_of.is_(None),
            )
        )
    if match is None and hashes["dedup_key"]:
        match = session.scalar(
            select(Job).where(Job.dedup_key == hashes["dedup_key"], Job.duplicate_of.is_(None))
        )

    if match is not None and match.content_hash == hashes["content_hash"]:
        match.last_seen_at = now
        match.is_active = True
        match.closed_at = None
        match.inactive_reason = None
        match.last_seen_run_id = run_id
        match.missing_runs = 0
        session.flush()
        return "duplicate"

    row = Job(
        source=job.source,
        source_job_id=job.source_job_id,
        duplicate_of=match.id if match is not None else None,
        first_seen_at=now,
        last_seen_at=now,
        is_active=True,
        last_seen_run_id=run_id,
        missing_runs=0,
        **_job_fields(job, hashes),
    )
    session.add(row)
    session.flush()
    return "duplicate" if row.duplicate_of is not None else "inserted"


def persist_job_safe(session: Session, job: NormalizedJob, run_id: int | None = None) -> str:
    """Persist one job inside a savepoint; survive a concurrent-insert race.

    A bad row only rolls back its own savepoint instead of the whole batch.
    """
    try:
        with session.begin_nested():
            return persist_job(session, job, run_id)
    except IntegrityError:
        # Another worker inserted the same job between our SELECT and INSERT;
        # retry once so layer-2/3 dedup can attach it as a duplicate.
        return persist_job(session, job, run_id)


def apply_missing_sweep(
    session: Session, source: str, run_id: int, threshold: int
) -> dict:
    """After a complete board run, age out jobs that did not appear.

    Only safe for full-board snapshot sources (ATS); keyword-search sources
    must not use this because a successful search is not a board snapshot.
    """
    unseen = (
        Job.source == source,
        Job.is_active.is_(True),
        or_(Job.last_seen_run_id.is_(None), Job.last_seen_run_id != run_id),
    )
    session.execute(
        update(Job).where(*unseen).values(missing_runs=Job.missing_runs + 1)
    )
    closed = session.execute(
        update(Job)
        .where(Job.source == source, Job.is_active.is_(True), Job.missing_runs >= threshold)
        .values(is_active=False, closed_at=_utcnow(), inactive_reason="missing")
    )
    session.commit()
    return {"closed": int(closed.rowcount or 0)}


def _finish_run(session: Session, run_id: int, status: str, stats: RunStats) -> None:
    run = session.get(CollectorRun, run_id)
    if run is None:
        return
    run.status = status
    run.jobs_seen = stats.seen
    run.jobs_inserted = stats.inserted
    run.jobs_updated = stats.updated
    run.jobs_duplicate = stats.duplicates
    run.error = stats.error
    run.finished_at = _utcnow()
    session.commit()


async def run_collector(
    collector: BaseCollector,
    params: SearchParams,
    session_factory: sessionmaker[Session],
) -> RunStats:
    """Run a single collector end-to-end and record its status."""
    stats = RunStats(source=collector.name)
    run = CollectorRun(
        source=collector.name,
        status="running",
        params={
            "keywords": params.keywords,
            "location": params.location,
            "country": params.country,
            "results_wanted": params.results_wanted,
        },
        started_at=_utcnow(),
    )
    with session_factory() as session:
        session.add(run)
        session.commit()
        run_id = run.id
        try:
            collector.validate()
            async for job in collector.stream(params):
                stats.seen += 1
                try:
                    action = persist_job_safe(session, job, run_id)
                except Exception:  # noqa: BLE001 - isolate the bad row
                    session.rollback()
                    stats.errors += 1
                    logger.exception("failed to persist job from %s", collector.name)
                    continue
                if action == "inserted":
                    stats.inserted += 1
                elif action == "updated":
                    stats.updated += 1
                else:
                    stats.duplicates += 1
                if stats.seen % 200 == 0:
                    session.commit()
            session.commit()
            settings = get_settings()
            board_complete = stats.seen < params.results_wanted and stats.seen > 0
            if (
                settings.board_sweep_enabled
                and board_complete
                and collector.name in ATS_SOURCES
            ):
                try:
                    apply_missing_sweep(
                        session, collector.name, run_id, settings.missing_run_threshold
                    )
                except Exception:  # noqa: BLE001 - never fail the run for this
                    session.rollback()
                    logger.exception("missing sweep failed for %s", collector.name)
            _finish_run(session, run_id, "success", stats)
        except Exception as exc:  # noqa: BLE001 - one source must not kill the run
            session.rollback()
            stats.error = f"{type(exc).__name__}: {exc}"
            logger.exception("collector %s failed", collector.name)
            _finish_run(session, run_id, "error", stats)
    logger.info("collector %s done: %s", collector.name, stats.as_dict())
    return stats


async def run_collectors(
    collectors: list[BaseCollector],
    params: SearchParams,
    session_factory: sessionmaker[Session],
) -> tuple[list[RunStats], RunStats]:
    per_source: list[RunStats] = []
    total = RunStats(source="total")
    for collector in collectors:
        stats = await run_collector(collector, params, session_factory)
        per_source.append(stats)
        total.merge(stats)
    return per_source, total
