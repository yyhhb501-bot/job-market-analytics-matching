"""Application settings, loaded from environment variables / ``.env``."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Job Aggregator API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://jobuser:jobpass@localhost:5432/jobs"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "*"
    auto_create_tables: bool = True

    # Authentication: when API_KEY is set, write endpoints require it via the
    # X-API-Key header. Never deploy publicly without it.
    api_key: str | None = None
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    match_rate_limit_per_minute: int = 10

    # Collector toggles. Anything rate-limited or ToS-sensitive stays off.
    enable_ats: bool = True
    enable_usajobs: bool = False
    enable_jobspy: bool = False
    enable_seek: bool = False
    enable_linkedin: bool = False
    enable_adzuna: bool = False
    enable_remoteok: bool = False

    # Credentials / adapter config
    usajobs_email: str | None = None
    usajobs_api_key: str | None = None
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    ats_companies_file: str = "config/ats_companies.json"

    # Saved-search email alerts (stdlib smtplib)
    enable_email_alerts: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    alert_from_email: str | None = None
    alert_from_name: str = "Job Aggregator"
    web_base_url: str = "http://localhost:3000"

    # Task queue / scheduling
    celery_broker_url: str | None = None  # defaults to REDIS_URL when empty
    celery_result_backend: str | None = None  # defaults to REDIS_URL when empty
    # Scheduling. `daily` runs once a day at COLLECT_HOUR:COLLECT_MINUTE in
    # TIMEZONE; `interval` runs every COLLECT_INTERVAL_MINUTES.
    timezone: str = "Asia/Shanghai"
    collect_schedule: str = "daily"  # daily | interval
    collect_hour: int = 12
    collect_minute: int = 0
    collect_interval_minutes: int = 60
    collect_keywords: str | None = None
    collect_location: str | None = None
    collect_country: str | None = None
    collect_results: int = 100
    # JobSpy sites used by keyword search (comma-separated).
    collect_sites: str = "indeed,google"

    # FX: rates are "value of 1 unit in the base currency" (USD by default).
    fx_base_currency: str = "USD"
    fx_rates: str = (
        '{"USD": 1.0, "AUD": 0.66, "EUR": 1.08, "GBP": 1.27, "CAD": 0.74, "NZD": 0.60}'
    )

    # AI enrichment is local/deterministic by default; plug an LLM behind the
    # same interface later by setting a provider + key here.
    enrichment_enabled: bool = True
    enable_digest_alerts: bool = True

    # Semantic matching. `local` is a deterministic offline embedder; set
    # provider=openai (or auto) with a key to use an OpenAI-compatible endpoint.
    enable_semantic_match: bool = True
    llm_provider: str = "local"  # local | openai | auto | none
    llm_api_key: str | None = None
    llm_model: str = "text-embedding-3-small"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 30.0
    llm_embedding_dim: int = 256

    # Cross-encoder reranking for résumé matching.
    enable_rerank: bool = True
    rerank_provider: str = "local"  # local | http | none
    rerank_api_key: str | None = None
    rerank_model: str = "rerank-english-v3.0"
    rerank_base_url: str = "https://api.jina.ai/v1"
    rerank_top_k: int = 50

    # Saved-search webhook delivery. Off by default; enable deliberately.
    enable_webhooks: bool = False
    webhook_timeout_seconds: float = 10.0
    webhook_max_jobs: int = 20
    # SSRF protection: comma-separated host allowlist (empty = any public host).
    webhook_allowed_hosts: str = ""
    # Escape hatch for trusted internal receivers (self-hosted only).
    webhook_allow_private: bool = False
    # When set, outbound webhooks carry an HMAC-SHA256 signature header.
    webhook_signing_secret: str | None = None

    # Job lifecycle: jobs not seen for this many days are marked inactive.
    stale_job_days: int = 30
    # Per-board missing sweep: after N complete successful board runs that did
    # not include a job, mark it inactive (ATS full-board sources only).
    board_sweep_enabled: bool = True
    missing_run_threshold: int = 3

    # Daily digest/sweep hour (in TIMEZONE), default right after the 12:00
    # collection: digest at :30, sweep at the next hour.
    digest_hour_utc: int = 12

    # LLM-generated summaries (falls back to the extractive summary).
    enable_llm_summaries: bool = False
    llm_summary_model: str = "gpt-4o-mini"
    llm_summary_max_chars: int = 6000

    # Search backend: "postgres" (default) or "opensearch".
    search_backend: str = "postgres"
    opensearch_url: str | None = None
    opensearch_index: str = "jobs"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_timeout_seconds: float = 10.0

    @property
    def fx_rate_map(self) -> dict[str, float]:
        from packages.fx import parse_rates

        return parse_rates(self.fx_rates)

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    # Politeness / networking
    user_agent: str = "job-aggregator/0.1 (+contact: you@example.com)"
    http_timeout_seconds: float = 30.0
    seek_requests_per_minute: int = 10
    default_countries: str = "US,AU"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def country_list(self) -> list[str]:
        return [c.strip().upper() for c in self.default_countries.split(",") if c.strip()]


_WEAK_DB_PASSWORDS = (
    "jobpass",
    "postgres",
    "password",
    "changeme",
    "change_me_strong",
)


def _database_password(database_url: str) -> str:
    try:
        from sqlalchemy.engine import make_url

        return (make_url(database_url).password or "").lower()
    except Exception:  # noqa: BLE001 - unparseable URL is a separate concern
        return ""


def check_production_settings(settings: Settings) -> list[str]:
    """Return a list of unsafe settings when running in production.

    An empty list means the configuration is acceptable to start.
    """
    if settings.environment.lower() != "production":
        return []
    problems: list[str] = []
    if not settings.api_key:
        problems.append("API_KEY must be set so write/read endpoints are authenticated")
    if "*" in settings.cors_origin_list:
        problems.append("CORS_ORIGINS must list explicit origins (not '*')")
    if _database_password(settings.database_url) in _WEAK_DB_PASSWORDS:
        problems.append("DATABASE_URL still uses a default/weak password")
    if settings.webhook_allow_private:
        problems.append("WEBHOOK_ALLOW_PRIVATE must be false on public deployments")
    if settings.auto_create_tables:
        problems.append("AUTO_CREATE_TABLES must be false (run Alembic migrations instead)")
    return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
