"""Pydantic response models for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_job_id: str
    title: str
    company: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    apply_url: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    duplicate_of: int | None = None
    skills: list[str] | None = None
    summary: str | None = None
    salary_display_min: float | None = None
    salary_display_max: float | None = None
    salary_display_currency: str | None = None
    salary_display_period: str | None = None


class JobSearchResponse(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class SourceCount(BaseModel):
    source: str
    count: int


class CountryCount(BaseModel):
    country: str | None = None
    count: int


class StatsResponse(BaseModel):
    total_jobs: int
    active_jobs: int
    by_source: list[SourceCount]
    by_country: list[CountryCount]


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    keywords: str | None = None
    country: str | None = None
    source: str | None = None
    city: str | None = None
    state: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    min_salary: float | None = None
    notify_email: str | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_kind: Literal["generic", "slack", "teams"] = "generic"
    frequency: Literal["immediate", "digest"] = "immediate"

    @field_validator("webhook_url")
    @classmethod
    def _check_webhook(cls, value: str | None) -> str | None:
        from apps.api.webhooks import normalize_webhook_url

        return normalize_webhook_url(value)


class SavedSearchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notify_email: str | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_kind: Literal["generic", "slack", "teams"] | None = None
    frequency: Literal["immediate", "digest"] | None = None
    is_active: bool | None = None

    @field_validator("webhook_url")
    @classmethod
    def _check_webhook(cls, value: str | None) -> str | None:
        from apps.api.webhooks import normalize_webhook_url

        return normalize_webhook_url(value)


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    keywords: str | None = None
    country: str | None = None
    source: str | None = None
    city: str | None = None
    state: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    min_salary: float | None = None
    notify_email: str | None = None
    webhook_url: str | None = None
    webhook_kind: str = "generic"
    frequency: str = "immediate"
    is_active: bool
    last_run_at: datetime | None = None
    last_notified_at: datetime | None = None
    last_match_count: int
    created_at: datetime | None = None


class SavedSearchRunResult(BaseModel):
    saved_search_id: int
    new_matches: int
    total_matches: int
    items: list[JobOut]


class CollectorRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    status: str
    params: dict | None = None
    jobs_seen: int
    jobs_inserted: int
    jobs_updated: int
    jobs_duplicate: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SourceRunSummary(BaseModel):
    source: str
    runs: int
    successes: int
    errors: int
    last_status: str | None = None
    last_run_at: datetime | None = None
    jobs_seen: int
    jobs_inserted: int


class RunsSummaryResponse(BaseModel):
    total_runs: int
    sources: list[SourceRunSummary]


class MatchRequest(BaseModel):
    resume: str = Field(min_length=1, max_length=20000)
    limit: int = Field(default=20, ge=1, le=100)
    country: str | None = None
    remote_type: str | None = None


class MatchResult(BaseModel):
    job: JobOut
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    shared_keywords: list[str]
    semantic_score: float | None = None
    rerank_score: float | None = None


class MatchResponse(BaseModel):
    engine: str = "keyword"
    reranked: bool = False
    results: list[MatchResult]
