from __future__ import annotations

from apps.api.config import Settings, check_production_settings


def test_development_has_no_problems():
    assert check_production_settings(Settings(environment="development")) == []


def test_production_flags_all_unsafe_settings():
    settings = Settings(
        environment="production",
        api_key=None,
        cors_origins="*",
        database_url="postgresql+psycopg://user:jobpass@db:5432/jobs",
        webhook_allow_private=True,
        auto_create_tables=True,
    )
    problems = check_production_settings(settings)
    assert len(problems) == 5
    assert any("API_KEY" in problem for problem in problems)
    assert any("CORS_ORIGINS" in problem for problem in problems)
    assert any("DATABASE_URL" in problem for problem in problems)
    assert any("WEBHOOK_ALLOW_PRIVATE" in problem for problem in problems)
    assert any("AUTO_CREATE_TABLES" in problem for problem in problems)


def test_production_safe_config_passes():
    settings = Settings(
        environment="production",
        api_key="strong-key",
        cors_origins="https://app.example.com",
        database_url="postgresql+psycopg://user:s3cret@db:5432/jobs",
        webhook_allow_private=False,
        auto_create_tables=False,
    )
    assert check_production_settings(settings) == []
