"""Collection pipeline: stream -> normalise -> three-layer dedup -> persist.

Run outcomes are classified into four categories so the task layer can decide
about retries and humans can trust the results:

- ``success``   — clean run, nothing suspicious;
- ``partial``   — ended early (visit/time budget) or some items/boards failed;
- ``retryable``  — transient upstream failure; the Celery task retries it;
- ``blocked``   — CAPTCHA / 401/403 / login wall; the source is paused for a
  human and never retried automatically.

Missing-job sweeps run per board (company) and only after that board's full
snapshot was read successfully — a failing board can no longer age out its
jobs. Sources can be paused manually or by the pipeline, and a run mutex
keeps full / hot / manual dispatches from collecting the same source twice.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.boards import load_runtime_boards
from apps.api.config import get_settings
from apps.api.metrics import record_run
from apps.api.models import CollectorRun, Job, SourceControl, utcnow
from collectors.ats_adapters.config import set_runtime_boards
from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RetryableCollectorError,
    SearchParams,
    classify_exception,
)
from collectors.budget import VisitBudget
from packages.deduplication import compute_hashes
from packages.enrichment import enrich_job
from packages.job_schema import ATS_SOURCES, NormalizedJob

logger = logging.getLogger("jobagg.worker.pipeline")

# A "running" CollectorRun older than this is stale (crashed worker) and no
# longer blocks a new run for the same source.
MUTEX_STALE_MINUTES = 120


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
    outcome: str = "success"  # success | partial | retryable | blocked | paused | skipped
    stopped_reason: str | None = None
    pages_visited: int = 0
    details_visited: int = 0
    retry_after: float | None = None

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
            "outcome": self.outcome,
            "stopped_reason": self.stopped_reason,
            "pages_visited": self.pages_visited,
            "details_visited": self.details_visited,
            "retry_after": self.retry_after,
        }


def _job_fields(job: NormalizedJob, hashes: dict) -> dict:
    enriched = enrich_job(job)
    return {
        "skills": enriched["skills"],
        "summary": enriched["summary"],
        "summary_source": "extractive" if enriched["summary"] else None,
        "occupation_group": enriched.get("occupation_group") or "other",
        "seniority": enriched.get("seniority"),
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


def _owner_identity_condition(owner_device_id: int | None):
    """Exact dedup scope: public rows (NULL owner) or one device's private rows."""
    if owner_device_id is None:
        return Job.owner_device_id.is_(None)
    return Job.owner_device_id == owner_device_id


def _owner_match_condition(owner_device_id: int | None):
    """Cross-post dedup scope: public rows plus the importing device's own rows."""
    if owner_device_id is None:
        return or_(Job.owner_device_id.is_(None), Job.owner_device_id == owner_device_id)
    return or_(Job.owner_device_id.is_(None), Job.owner_device_id == owner_device_id)


def persist_job_row(
    session: Session,
    job: NormalizedJob,
    run_id: int | None = None,
    *,
    visibility: str = "public",
    collection_mode: str = "platform",
    owner_device_id: int | None = None,
    source_board_id: int | None = None,
) -> tuple[str, Job]:
    """Upsert one job and return ``(action, row)``.

    ``action`` is ``inserted`` | ``updated`` | ``duplicate``. Private imports
    dedup only against public rows and the same device's rows, never against
    another device's private data.
    """
    hashes = compute_hashes(job)
    now = _utcnow()

    # Layer 1: exact (source, source_job_id) within the owner scope
    existing = session.scalar(
        select(Job).where(
            Job.source == job.source,
            Job.source_job_id == job.source_job_id,
            _owner_identity_condition(owner_device_id),
        )
    )
    if existing is not None:
        if existing.content_hash != hashes["content_hash"]:
            for key, value in _job_fields(job, hashes).items():
                setattr(existing, key, value)
            existing.updated_at = now
        if existing.source_board_id is None and source_board_id is not None:
            existing.source_board_id = source_board_id
        existing.last_seen_at = now
        existing.is_active = True
        existing.closed_at = None
        existing.inactive_reason = None
        existing.last_seen_run_id = run_id
        existing.missing_runs = 0
        session.flush()
        return "updated", existing

    # Layers 2 & 3: same posting via a different link / cross-posted elsewhere
    match_scope = _owner_match_condition(owner_device_id)
    match = None
    if hashes["canonical_url_hash"]:
        match = session.scalar(
            select(Job).where(
                Job.canonical_url_hash == hashes["canonical_url_hash"],
                Job.duplicate_of.is_(None),
                match_scope,
            )
        )
    if match is None and hashes["dedup_key"]:
        match = session.scalar(
            select(Job).where(
                Job.dedup_key == hashes["dedup_key"],
                Job.duplicate_of.is_(None),
                match_scope,
            )
        )

    if match is not None and match.content_hash == hashes["content_hash"]:
        match.last_seen_at = now
        match.is_active = True
        match.closed_at = None
        match.inactive_reason = None
        match.last_seen_run_id = run_id
        match.missing_runs = 0
        session.flush()
        return "duplicate", match

    row = Job(
        source=job.source,
        source_job_id=job.source_job_id,
        duplicate_of=match.id if match is not None else None,
        first_seen_at=now,
        last_seen_at=now,
        is_active=True,
        last_seen_run_id=run_id,
        missing_runs=0,
        visibility=visibility,
        collection_mode=collection_mode,
        owner_device_id=owner_device_id,
        source_board_id=source_board_id,
        **_job_fields(job, hashes),
    )
    session.add(row)
    session.flush()
    return ("duplicate" if row.duplicate_of is not None else "inserted"), row


def persist_job(
    session: Session,
    job: NormalizedJob,
    run_id: int | None = None,
    **kwargs,
) -> str:
    """Upsert one job. Returns ``inserted`` | ``updated`` | ``duplicate``."""
    return persist_job_row(session, job, run_id, **kwargs)[0]


def persist_job_row_safe(
    session: Session, job: NormalizedJob, run_id: int | None = None, **kwargs
) -> tuple[str, Job]:
    """Savepoint-wrapped :func:`persist_job_row`; survives concurrent inserts."""
    try:
        with session.begin_nested():
            return persist_job_row(session, job, run_id, **kwargs)
    except IntegrityError:
        # Another worker inserted the same job between our SELECT and INSERT;
        # retry once so layer-2/3 dedup can attach it as a duplicate. The retry
        # gets its own savepoint so a second failure leaves the session usable.
        with session.begin_nested():
            return persist_job_row(session, job, run_id, **kwargs)


def persist_job_safe(
    session: Session, job: NormalizedJob, run_id: int | None = None, **kwargs
) -> str:
    """Persist one job inside a savepoint; survive a concurrent-insert race.

    A bad row only rolls back its own savepoint instead of the whole batch.
    """
    try:
        with session.begin_nested():
            return persist_job(session, job, run_id, **kwargs)
    except IntegrityError:
        # Another worker inserted the same job between our SELECT and INSERT;
        # retry once so layer-2/3 dedup can attach it as a duplicate. The retry
        # gets its own savepoint so a second failure leaves the session usable.
        with session.begin_nested():
            return persist_job(session, job, run_id, **kwargs)


def apply_board_missing_sweep(
    session: Session, board_ids: list[int], run_id: int, threshold: int
) -> dict:
    """Age out jobs of *fully collected* boards that did not appear this run.

    Only boards whose snapshot was read completely and successfully may close
    their missing jobs; a board that failed (or a source without board
    attribution) is never swept. Keyword-search sources must not use this.
    """
    if not board_ids:
        return {"closed": 0}
    unseen = (
        Job.source_board_id.in_(board_ids),
        Job.is_active.is_(True),
        or_(Job.last_seen_run_id.is_(None), Job.last_seen_run_id != run_id),
    )
    session.execute(
        update(Job).where(*unseen).values(missing_runs=Job.missing_runs + 1)
    )
    closed = session.execute(
        update(Job)
        .where(
            Job.source_board_id.in_(board_ids),
            Job.is_active.is_(True),
            Job.missing_runs >= threshold,
        )
        .values(is_active=False, closed_at=_utcnow(), inactive_reason="missing")
    )
    session.commit()
    return {"closed": int(closed.rowcount or 0)}


def pause_source(session: Session, source: str, reason: str, note: str | None = None) -> None:
    """Pause a collection source until an operator resumes it."""
    control = session.scalar(select(SourceControl).where(SourceControl.source == source))
    if control is None:
        control = SourceControl(source=source)
        session.add(control)
    control.paused = True
    control.pause_reason = reason
    control.paused_at = _utcnow()
    if note:
        control.note = note[:2000]
    session.commit()


def resume_source(session: Session, source: str) -> bool:
    """Clear a source's pause. Returns False when the source was not paused."""
    control = session.scalar(select(SourceControl).where(SourceControl.source == source))
    if control is None or not control.paused:
        return False
    control.paused = False
    control.pause_reason = None
    control.paused_at = None
    control.note = None
    session.commit()
    return True


def source_is_paused(session: Session, source: str) -> SourceControl | None:
    control = session.scalar(select(SourceControl).where(SourceControl.source == source))
    if control is not None and control.paused:
        return control
    return None


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
    run.stopped_reason = stats.stopped_reason
    run.pages_visited = stats.pages_visited
    run.details_visited = stats.details_visited
    run.finished_at = _utcnow()
    session.commit()


def _record_gate_run(
    session: Session, source: str, status: str, stats: RunStats, reason: str
) -> None:
    """Persist a zero-job run row for a gated (paused/skipped) dispatch."""
    run = CollectorRun(
        source=source,
        status=status,
        params=None,
        jobs_seen=0,
        error=reason,
        started_at=_utcnow(),
        finished_at=_utcnow(),
        stopped_reason=reason,
    )
    session.add(run)
    session.commit()


async def run_collector(
    collector: BaseCollector,
    params: SearchParams,
    session_factory: sessionmaker[Session],
) -> RunStats:
    """Run a single collector end-to-end: gates, budget, stream, sweep, status."""
    settings = get_settings()
    stats = RunStats(source=collector.name)
    max_run_minutes = max(int(settings.max_run_minutes or 0), 0)
    deadline = time.monotonic() + max_run_minutes * 60 if max_run_minutes else None

    with session_factory() as session:
        # Gate 1: operator/pipeline pause — collect nothing until resumed.
        paused = source_is_paused(session, collector.name)
        if paused is not None:
            stats.outcome = "paused"
            stats.stopped_reason = paused.pause_reason or "manual"
            stats.error = f"source paused ({stats.stopped_reason}); resume via collector controls"
            logger.info("collector %s skipped: paused (%s)", collector.name, stats.stopped_reason)
            return stats

        # Gate 2: run mutex — full / hot / manual dispatches must not collect
        # the same source concurrently. Stale "running" rows (crashed worker)
        # stop blocking after the staleness window.
        staleness = dt.timedelta(minutes=max(max_run_minutes, MUTEX_STALE_MINUTES))
        active_id = session.scalar(
            select(CollectorRun.id)
            .where(
                CollectorRun.source == collector.name,
                CollectorRun.status == "running",
                CollectorRun.started_at > utcnow() - staleness,
            )
            .limit(1)
        )
        if active_id is not None:
            stats.outcome = "skipped"
            stats.stopped_reason = "already_running"
            _record_gate_run(session, collector.name, "skipped", stats, stats.stopped_reason)
            logger.info("collector %s skipped: a run is already active", collector.name)
            return stats

        run = CollectorRun(
            source=collector.name,
            status="running",
            params={
                "keywords": params.keywords,
                "location": params.location,
                "country": params.country,
                "results_wanted": params.results_wanted,
                "extra": params.extra,
            },
            started_at=_utcnow(),
        )
        session.add(run)
        session.commit()
        run_id = run.id

        if settings.daily_page_visit_limit or settings.daily_detail_visit_limit:
            collector.budget = VisitBudget(
                collector.name,
                session_factory=session_factory,
                page_limit=settings.daily_page_visit_limit,
                detail_limit=settings.daily_detail_visit_limit,
            )
        try:
            runtime = load_runtime_boards(session)
            set_runtime_boards(runtime)
            board_map: dict[tuple[str, str | None], int] = {
                (provider, entry.get("token")): entry["board_id"]
                for provider, entries in runtime.items()
                for entry in entries
                if entry.get("board_id")
            }
            collector.validate()
            async for job in collector.stream(params):
                if job.board_token is None and collector.current_board:
                    job.board_token = collector.current_board
                board_id = (
                    board_map.get((collector.name, job.board_token)) if job.board_token else None
                )
                stats.seen += 1
                try:
                    action = persist_job_safe(
                        session, job, run_id, source_board_id=board_id
                    )
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
                if deadline is not None and time.monotonic() > deadline:
                    stats.stopped_reason = "time_budget"
                    logger.info("collector %s stopped: time budget reached", collector.name)
                    break
            session.commit()

            if collector.budget is not None:
                stats.pages_visited = collector.budget.page_visits
                stats.details_visited = collector.budget.detail_visits
                if stats.stopped_reason is None and not collector.budget.page_allowed():
                    stats.stopped_reason = "visit_budget"
                    logger.info("collector %s stopped: visit budget reached", collector.name)

            # Per-board missing sweep: only boards that were read completely
            # and successfully may close their missing jobs.
            if settings.board_sweep_enabled and collector.name in ATS_SOURCES:
                complete_ids = [
                    board_id
                    for (source, token), board_id in board_map.items()
                    if source == collector.name
                    and token in collector.complete_boards
                    and collector.board_outcomes.get(token) is True
                ]
                if complete_ids:
                    try:
                        apply_board_missing_sweep(
                            session, complete_ids, run_id, settings.missing_run_threshold
                        )
                    except Exception:  # noqa: BLE001 - never fail the run for this
                        session.rollback()
                        logger.exception("missing sweep failed for %s", collector.name)
                failed_boards = [
                    token for token, ok in collector.board_outcomes.items() if ok is False
                ]
                if failed_boards and not collector.complete_boards:
                    # Every known board failed (or none completed): the run
                    # proved nothing about the source — retryable, not success.
                    detail = "; ".join(
                        f"{token}: {collector.board_errors.get(token, 'failed')}"
                        for token in sorted(failed_boards)[:3]
                    )
                    raise RetryableCollectorError(
                        f"all {len(failed_boards)} board(s) failed — {detail}"
                    )

            if stats.outcome == "success" and (
                stats.stopped_reason
                or stats.errors
                or any(ok is False for ok in collector.board_outcomes.values())
            ):
                stats.outcome = "partial"
            _finish_run(session, run_id, stats.outcome, stats)
        except AccessBlockedError as exc:
            session.rollback()
            stats.error = f"{type(exc).__name__}: {exc}"
            stats.outcome = "blocked"
            logger.error("collector %s blocked: %s", collector.name, stats.error)
            if settings.pause_on_challenge:
                try:
                    pause_source(session, collector.name, "challenge", stats.error)
                except Exception:  # noqa: BLE001
                    session.rollback()
                    logger.exception("failed to pause %s after challenge", collector.name)
            _finish_run(session, run_id, "blocked", stats)
        except Exception as exc:  # noqa: BLE001 - classify, record, maybe retry
            session.rollback()
            outcome, retry_after = classify_exception(exc)
            stats.error = f"{type(exc).__name__}: {exc}"
            stats.outcome = outcome
            stats.retry_after = retry_after
            logger.exception("collector %s failed (%s)", collector.name, outcome)
            _finish_run(session, run_id, outcome, stats)
            if outcome == "retryable":
                # Let the Celery task retry; keep the classified error intact.
                raise RetryableCollectorError(stats.error) from exc

    if collector.budget is not None and stats.pages_visited == 0:
        stats.pages_visited = collector.budget.page_visits
        stats.details_visited = collector.budget.detail_visits
    record_run(collector.name, stats.outcome, stats.as_dict())
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
        try:
            stats = await run_collector(collector, params, session_factory)
        except RetryableCollectorError as exc:
            stats = RunStats(source=collector.name, outcome="retryable", error=str(exc))
        per_source.append(stats)
        total.merge(stats)
    return per_source, total
