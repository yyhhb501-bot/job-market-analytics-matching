"""Saved-search evaluation and notification logic (API + worker + Celery)."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.config import Settings
from apps.api.filters import as_list, build_conditions
from apps.api.mailer import is_email_configured, send_saved_search_alert
from apps.api.models import Job, SavedSearch, SavedSearchMatch, utcnow
from apps.api.source_authorization import public_job_condition
from apps.api.webhooks import build_webhook_payload, send_webhook


def generate_unsubscribe_token() -> str:
    return secrets.token_urlsafe(32)


def build_unsubscribe_url(settings: Settings, search: SavedSearch) -> str | None:
    if not search.unsubscribe_token:
        return None
    return f"{settings.web_base_url.rstrip('/')}/unsubscribe?token={search.unsubscribe_token}"


def match_conditions(search: SavedSearch, since, dialect_name: str = "sqlite") -> list:
    conditions = build_conditions(
        q=search.keywords,
        dialect_name=dialect_name,
        sources=as_list(search.source),
        countries=as_list(search.country),
        states=as_list(search.state),
        cities=as_list(search.city),
        remote_types=as_list(search.remote_type),
        employment_types=as_list(search.employment_type),
        min_salary=search.min_salary,
        first_seen_after=since,
    )
    conditions.append(Job.is_active.is_(True))
    conditions.append(Job.duplicate_of.is_(None))
    return conditions


def evaluate_search(session: Session, search: SavedSearch, lookback_hours: int = 24) -> dict:
    """Find jobs matching ``search`` first seen since its last run (or lookback)."""
    now = utcnow()
    since = search.last_run_at or (now - timedelta(hours=max(lookback_hours, 0)))
    dialect_name = session.get_bind().dialect.name
    jobs = session.scalars(
        select(Job)
        .where(*match_conditions(search, since, dialect_name))
        .order_by(Job.first_seen_at.desc())
        .limit(200)
    ).all()

    new_matches = 0
    new_jobs = []
    for job in jobs:
        existing = session.scalar(
            select(SavedSearchMatch).where(
                SavedSearchMatch.saved_search_id == search.id,
                SavedSearchMatch.job_id == job.id,
            )
        )
        if existing is None:
            session.add(SavedSearchMatch(saved_search_id=search.id, job_id=job.id, matched_at=now))
            new_matches += 1
            new_jobs.append(job)

    search.last_run_at = now
    search.last_match_count = len(jobs)
    session.commit()

    total = (
        session.scalar(
            select(func.count())
            .select_from(SavedSearchMatch)
            .join(Job, Job.id == SavedSearchMatch.job_id)
            .where(SavedSearchMatch.saved_search_id == search.id, public_job_condition())
        )
        or 0
    )
    return {
        "new_matches": new_matches,
        "total_matches": total,
        "items": jobs,
        "new_jobs": new_jobs,
    }


def run_active_saved_searches(session: Session, lookback_hours: int = 24) -> list[dict]:
    results: list[dict] = []
    searches = session.scalars(
        select(SavedSearch).where(SavedSearch.is_active.is_(True)).order_by(SavedSearch.id)
    ).all()
    for search in searches:
        result = evaluate_search(session, search, lookback_hours=lookback_hours)
        results.append(
            {
                "saved_search_id": search.id,
                "name": search.name,
                "notify_email": search.notify_email,
                "frequency": search.frequency,
                "new_matches": result["new_matches"],
                "new_jobs": result["new_jobs"],
                "total_matches": result["total_matches"],
            }
        )
    return results


def _unnotified_jobs(session: Session, search: SavedSearch) -> list[Job]:
    statement = (
        select(Job)
        .join(SavedSearchMatch, SavedSearchMatch.job_id == Job.id)
        .where(SavedSearchMatch.saved_search_id == search.id, public_job_condition())
    )
    if search.last_notified_at is not None:
        statement = statement.where(SavedSearchMatch.matched_at > search.last_notified_at)
    statement = statement.order_by(
        SavedSearchMatch.matched_at.desc(), SavedSearchMatch.id.desc()
    ).limit(100)
    return list(session.scalars(statement).all())


def notify_saved_searches(
    session: Session, settings: Settings, results: list[dict]
) -> dict:
    """Deliver alerts (email and/or webhook) according to each search's settings."""
    email_configured = is_email_configured(settings)
    emails_sent = 0
    webhooks_sent = 0
    now = utcnow()

    for row in results:
        search = session.get(SavedSearch, row["saved_search_id"])
        if search is None or not search.is_active:
            continue
        digest = search.frequency == "digest"
        jobs = _unnotified_jobs(session, search) if digest else row["new_jobs"]
        ids = [job.id for job in jobs]
        allowed = set(
            session.scalars(select(Job.id).where(Job.id.in_(ids), public_job_condition())).all()
        )
        jobs = [job for job in jobs if job.id in allowed]
        if not jobs:
            continue

        delivered = False
        if email_configured and search.notify_email:
            if send_saved_search_alert(
                settings,
                search.name,
                search.notify_email,
                jobs,
                unsubscribe_url=build_unsubscribe_url(settings, search),
                digest=digest,
            ):
                emails_sent += 1
                delivered = True
        if settings.enable_webhooks and search.webhook_url:
            if send_webhook(
                search.webhook_url,
                build_webhook_payload(settings, search, jobs),
                settings=settings,
                timeout=settings.webhook_timeout_seconds,
            ):
                webhooks_sent += 1
                delivered = True

        if delivered:
            search.last_notified_at = now

    session.commit()
    return {"emails_sent": emails_sent, "webhooks_sent": webhooks_sent}


__all__ = [
    "build_unsubscribe_url",
    "evaluate_search",
    "generate_unsubscribe_token",
    "match_conditions",
    "notify_saved_searches",
    "run_active_saved_searches",
]
