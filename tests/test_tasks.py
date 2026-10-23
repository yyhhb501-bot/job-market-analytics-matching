from __future__ import annotations

from apps.api.config import Settings
from apps.api.models import SavedSearch, SourceAuthorization, utcnow
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
    session.add(
        SourceAuthorization(
            source="seek",
            evidence_ref="test-license:tasks:seek",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
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


def test_expand_collector_specs_multi_keyword(monkeypatch):
    from apps.api.config import Settings
    from apps.worker import tasks

    monkeypatch.setattr(
        tasks, "enabled_source_names", lambda settings: ["greenhouse", "jobspy"]
    )
    settings = Settings(
        enable_ats=True,
        enable_jobspy=True,
        collect_keywords="nurse,teacher",
        collect_country="US,AU",
    )
    specs = tasks.expand_collector_specs(settings)
    names = [name for name, _ in specs]
    assert names.count("greenhouse") == 1
    assert names.count("jobspy") == 4  # 2 keywords x 2 countries
    jobspy_keywords = sorted(
        spec["keywords"] for name, spec in specs if name == "jobspy"
    )
    assert jobspy_keywords == ["nurse", "nurse", "teacher", "teacher"]


def test_expand_applies_per_source_result_overrides(monkeypatch):
    from apps.api.config import Settings
    from apps.worker import tasks

    monkeypatch.setattr(
        tasks, "enabled_source_names", lambda settings: ["greenhouse", "jobspy"]
    )
    settings = Settings(
        collect_results=100,
        collect_results_overrides='{"jobspy": 300}',
        collect_keywords="nurse",
        collect_country="US",
    )
    specs = tasks.expand_collector_specs(settings)
    jobspy = [spec for name, spec in specs if name == "jobspy"]
    assert jobspy and all(spec["results_wanted"] == 300 for spec in jobspy)
    greenhouse = next(spec for name, spec in specs if name == "greenhouse")
    assert greenhouse["results_wanted"] == 100


def test_celery_tasks_registered():
    from apps.worker.celery_app import celery_app

    assert "jobagg.collect_source" in celery_app.tasks
    assert "jobagg.collect_all" in celery_app.tasks
    assert "jobagg.evaluate_alerts" in celery_app.tasks


def test_au_nurse_plan_only_selects_explicit_api_source(monkeypatch):
    monkeypatch.setattr(tasks, "enabled_source_names", lambda settings: ["jobspy"])
    source, params = tasks.au_nurse_plan_params(
        Settings(au_nurse_plan_enabled=True, au_nurse_plan_sources="jobspy")
    )
    assert source is None
    assert params is None

    monkeypatch.setattr(tasks, "enabled_source_names", lambda settings: ["adzuna"])
    source, params = tasks.au_nurse_plan_params(
        Settings(au_nurse_plan_enabled=True, au_nurse_plan_sources="adzuna")
    )
    assert source == "adzuna"
    assert params["country"] == "AU"
    assert params["extra"]["plan"] == "au_nurse"
    assert params["extra"]["nurse_only"] is True
