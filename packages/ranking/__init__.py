"""Lightweight, dependency-free relevance scoring for the first version.

Once results exceed a few hundred thousand rows this can be replaced by
PostgreSQL full-text ranking or OpenSearch without changing callers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.deduplication import normalize_text
from packages.job_schema import NormalizedJob


def _tokenize(value: str | None) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) > 2}


def keyword_score(job: NormalizedJob, keywords: str | None) -> float:
    """Fraction of query tokens present in title/description/company (0..1)."""
    wanted = _tokenize(keywords)
    if not wanted:
        return 0.0
    haystack = _tokenize(f"{job.title} {job.company} {job.description}") | _tokenize(job.title)
    hits = wanted & haystack
    title_hits = wanted & _tokenize(job.title)
    score = len(hits) / len(wanted)
    score += 0.5 * (len(title_hits) / len(wanted))
    return min(score, 1.5)


def recency_score(job: NormalizedJob, now: datetime | None = None) -> float:
    if not job.posted_at:
        return 0.0
    now = now or datetime.now(UTC)
    posted = job.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    age = now - posted
    if age <= timedelta(days=1):
        return 0.5
    if age <= timedelta(days=7):
        return 0.3
    if age <= timedelta(days=30):
        return 0.1
    return 0.0


def score_job(job: NormalizedJob, keywords: str | None = None) -> float:
    return keyword_score(job, keywords) + recency_score(job)


__all__ = ["keyword_score", "recency_score", "score_job"]
