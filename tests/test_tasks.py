from __future__ import annotations

from apps.api.config import Settings
from apps.api.models import SavedSearch
from apps.worker import tasks
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def test_params_from_dict_defaults_and_overrides():
    default = tasks.params_from_dict({})
    assert default.results_wanted == 100
    assert default.keywords is None

    custom = tasks.params_from_dict(
        {"keywords": "data", "results_wanted": 5, "extra": {"sites": ["indeed"]}}
    )
    assert custom.keywords == "data"
    assert custom.results_wanted == 5
    assert custom.extra == {"sites": ["indeed"]}


def test_default_params_uses_settings():
    settings = Settings(collect_keywords="data", collect_country="US", collect_results=25)
    params = tasks.default_params(settings)
    assert params["keywords"] == "data"
    assert params["country"] == "US"
    assert params["results_wanted"] == 25


def test_collect_source_sync_skips_disabled_source(monkeypatch):
    monkeypatch.setattr(tasks, "build_collectors", lambda settings: [])
    result = tasks.collect_source_sync("not-enabled")
    assert result == {"source": "not-enabled", "skipped": True, "reason": "not enabled"}


def test_evaluate_alerts_sync_sends_email(session_factory, session, monkeypatch):
    persist_job(
        session,
        NormalizedJob(
            source="seek",
            source_job_id="1",
            title="Data Analyst",
            company="Oz Corp",
            description="SQL dashboards",
            city="Sydney",
            country="AU",
        ),
    )
    session.add(SavedSearch(name="AU jobs", country="AU", notify_email="me@example.com"))
    session.commit()

    captured: list[tuple[str, str, int]] = []
    monkeypatch.setattr(tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: Settings(
            enable_email_alerts=True, smtp_host="smtp.example.com", alert_from_email="x@y.com"
        ),
    )
    monkeypatch.setattr(
        "apps.api.alerts.send_saved_search_alert",
        lambda settings, name, email, jobs, unsubscribe_url=None, digest=False: captured.append(
            (name, email, len(jobs))
        )
        or True,
    )

    result = tasks.evaluate_alerts_sync(lookback_hours=24)
    assert result == {"searches": 1, "emails_sent": 1, "webhooks_sent": 0}
    assert captured == [("AU jobs", "me@example.com", 1)]


def test_celery_tasks_registered():
    from apps.worker.celery_app import celery_app

    assert "jobagg.collect_source" in celery_app.tasks
    assert "jobagg.collect_all" in celery_app.tasks
    assert "jobagg.evaluate_alerts" in celery_app.tasks
