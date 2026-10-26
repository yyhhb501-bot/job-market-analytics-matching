"""Pydantic response models for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_job_id: str
    title: str
    is_active: bool = True
    closed_at: datetime | None = None
    review_status: str | None = Field(default=None, validation_alias=AliasPath('raw_payload', 'lifecycle', 'status'))
    last_checked_at: datetime | None = Field(default=None, validation_alias=AliasPath('raw_payload', 'lifecycle', 'checked_at'))
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
    visibility: str = "public"
    collection_mode: str = "platform"
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


class BoardIn(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    board_token: str = Field(min_length=1, max_length=255)
    company_name: str | None = None
    company_domain: str | None = None
    country: str | None = Field(default=None, max_length=2)
    careers_url: str | None = None
    config: dict | None = None
    enabled: bool = True
    verify: bool = False


class BoardUpdate(BaseModel):
    enabled: bool | None = None
    company_name: str | None = None
    company_domain: str | None = None
    country: str | None = Field(default=None, max_length=2)
    config: dict | None = None


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    board_token: str
    company_name: str | None = None
    company_domain: str | None = None
    country: str | None = None
    careers_url: str | None = None
    config: dict | None = None
    enabled: bool
    discovery_source: str | None = None
    verified_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_job_count: int
    consecutive_failures: int
    discovered_at: datetime | None = None


class BoardCandidate(BaseModel):
    provider: str
    board_token: str
    careers_url: str | None = None
    config: dict | None = None
    job_count: int | None = None
    verified: bool = False


class DiscoverRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    create: bool = False


class CompareAreaMetrics(BaseModel):
    label: str
    active_jobs: int
    new_jobs: int
    unique_companies: int
    remote_ratio: float
    salary_coverage: float
    salary_median: float | None = None
    salary_currency: str | None = None
    salary_sample: int = 0
    top_skills: list[dict] = []
    top_companies: list[dict] = []
    daily_counts: list[dict] = []
    source_counts: list[dict] = []


class CompareComparison(BaseModel):
    job_count_ratio: float | None = None
    salary_difference_percent: float | None = None
    remote_ratio_difference: float | None = None


class CompareDataQuality(BaseModel):
    deduplicated: bool
    last_updated_at: datetime | None = None


class CompareResponse(BaseModel):
    occupation: str | None = None
    period_days: int
    area_a: CompareAreaMetrics
    area_b: CompareAreaMetrics
    comparison: CompareComparison
    data_quality: CompareDataQuality
    summary: str


class LocationOut(BaseModel):
    country: str | None = None
    state: str | None = None
    city: str | None = None
    count: int


class OccupationOut(BaseModel):
    occupation_group: str
    count: int


class SourceHealthOut(BaseModel):
    source: str
    runs: int
    successes: int
    errors: int
    success_rate: float
    last_status: str | None = None
    last_run_at: datetime | None = None
    last_job_count: int
    consecutive_zero_runs: int
    jobs_total: int
    jobs_active: int
    jobs_added_today: int
    schema_drift: bool = False


class CollectionTrendPoint(BaseModel):
    """New internal records collected on one Beijing-time calendar day."""

    date: str
    new_jobs: int


class CollectionSourceRow(BaseModel):
    """Whitelisted per-source figures for the public collection dashboard.

    Internal counts cover every collected record; public counts cover only
    records displayable under the current source-authorization policy. The
    two must never be conflated on public pages.
    """

    source: str
    internal_total: int
    public_total: int
    today_new_bj: int
    seven_day_new_bj: int
    last_ingest_at: datetime | None = None
    last_run_status: str | None = None
    last_run_at: datetime | None = None


class CollectionLocalUploadRow(BaseModel):
    """Local-collector upload aggregates; no tokens, owners or raw queries."""

    source: str
    today_accepted_bj: int
    today_duplicate_bj: int
    today_rejected_bj: int
    last_batch_id: int | None = None
    last_batch_status: str | None = None
    last_batch_accepted: int | None = None
    last_batch_duplicate: int | None = None
    last_batch_rejected: int | None = None
    last_batch_completed_at: datetime | None = None
    collector_state: str = "none"  # online | stale | offline | none
    collector_last_seen_at: datetime | None = None


class CollectionOverviewResponse(BaseModel):
    generated_at: datetime
    daily_target_per_source: int  # a target, not an achievement
    sources: list[CollectionSourceRow]
    local_uploads: list[CollectionLocalUploadRow]
    seven_day_trend: list[CollectionTrendPoint]
    trend_scope: str = "internal"


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
    keyword_coverage_score: float | None = None
    title_weight_score: float | None = None
    recency_score: float | None = None


class MatchResponse(BaseModel):
    engine: str = "keyword"
    reranked: bool = False
    data_scope: Literal["public_jobs", "illustrative_examples"] = "public_jobs"
    results: list[MatchResult]


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="linkedin", max_length=40)


class DeviceCreated(BaseModel):
    id: int
    name: str
    owner: str
    platform: str
    token: str
    token_prefix: str
    created_at: datetime | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner: str
    platform: str
    token_prefix: str
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


class ImportJobIn(BaseModel):
    source: str = Field(default="linkedin_user_import", max_length=50)
    source_job_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    company: str | None = None
    description: str | None = None
    country: str | None = Field(default=None, max_length=2)
    state: str | None = None
    city: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    canonical_url: str | None = None
    apply_url: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = Field(default=None, max_length=3)
    salary_period: str | None = None
    posted_at: datetime | None = None
    collected_at: datetime | None = None
    raw_payload: dict | None = None


class ImportJobsRequest(BaseModel):
    jobs: list[ImportJobIn] = Field(min_length=1, max_length=500)
    source: str = Field(default="linkedin_user_import", max_length=50)
    query: str | None = Field(default=None, max_length=300)
    geo_id: str | None = Field(default=None, max_length=50)


class ImportErrorItem(BaseModel):
    index: int
    reason: str


class ImportJobsResponse(BaseModel):
    batch_id: int
    status: str
    received_count: int
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    errors: list[ImportErrorItem] = []
    progress: dict | None = None


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    source: str
    query: str | None = None
    geo_id: str | None = None
    collection_mode: str
    status: str
    received_count: int
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImportedJobOut(BaseModel):
    job: JobOut
    batch_id: int | None = None
    action: str | None = None
    collected_at: datetime | None = None


class ImportedJobsResponse(BaseModel):
    total: int
    items: list[ImportedJobOut]
