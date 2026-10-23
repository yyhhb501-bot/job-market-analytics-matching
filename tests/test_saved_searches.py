from __future__ import annotations

import argparse

from apps.api.alerts import run_active_saved_searches
from apps.api.config import Settings
from apps.api.models import SavedSearch, SourceAuthorization, utcnow
from apps.worker import main as worker_main
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def seed(session) -> None:
    persist_job(
        session,
        NormalizedJob(
            source="indeed",
            source_job_id="1",
            title="Senior Data Engineer",
            company="Acme",
            description="Python and Spark pipelines",
            city="Austin",
            country="US",
        ),
    )
    persist_job(
        session,
        NormalizedJob(
            source="seek",
            source_job_id="2",
            title="Marketing Manager",
            company="Globex",
            description="Own the growth funnel",
            city="Sydney",
            country="AU",
        ),
    )
    session.add_all(
        SourceAuthorization(
            source=source,
            evidence_ref=f"test-license:saved-searches:{source}",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
        for source in ("indeed", "seek")
    )
    session.commit()


def test_create_run_and_matches(client, session):
    seed(session)
    created = client.post(
        "/api/v1/saved-searches", json={"name": "Data roles", "keywords": "data"}
    )
    assert created.status_code == 201
    search_id = created.json()["id"]

    run = client.post(f"/api/v1/saved-searches/{search_id}/run")
    assert run.status_code == 200
    body = run.json()
    assert body["new_matches"] == 1
    assert body["total_matches"] == 1
    assert body["items"][0]["title"] == "Senior Data Engineer"

    matches = client.get(f"/api/v1/saved-searches/{search_id}/matches")
    assert matches.status_code == 200
    assert len(matches.json()) == 1

    second_run = client.post(f"/api/v1/saved-searches/{search_id}/run").json()
    assert second_run["new_matches"] == 0
    assert second_run["total_matches"] == 1


def test_list_and_delete(client):
    created = client.post("/api/v1/saved-searches", json={"name": "AU remote", "country": "AU"})
    search_id = created.json()["id"]

    listed = client.get("/api/v1/saved-searches").json()
    assert [row["name"] for row in listed] == ["AU remote"]

    assert client.delete(f"/api/v1/saved-searches/{search_id}").status_code == 204
    assert client.get(f"/api/v1/saved-searches/{search_id}").status_code == 404
    assert client.get("/api/v1/saved-searches").json() == []


def test_worker_alert_evaluation(session):
    seed(session)
    session.add(SavedSearch(name="AU jobs", country="AU"))
    session.commit()

    results = run_active_saved_searches(session, lookback_hours=24)
    assert len(results) == 1
    assert results[0]["new_matches"] == 1
    assert len(results[0]["new_jobs"]) == 1
    assert results[0]["new_jobs"][0].title == "Marketing Manager"


def test_patch_saved_search(client):
    created = client.post(
        "/api/v1/saved-searches", json={"name": "AU", "frequency": "immediate"}
    ).json()
    updated = client.patch(
        f"/api/v1/saved-searches/{created['id']}",
        json={"frequency": "digest", "is_active": False, "notify_email": "me@x.com"},
    ).json()
    assert updated["frequency"] == "digest"
    assert updated["is_active"] is False
    assert updated["notify_email"] == "me@x.com"
    assert updated["name"] == "AU"

    assert (
        client.patch("/api/v1/saved-searches/999999", json={"is_active": True}).status_code
        == 404
    )


def test_create_rejects_bad_webhook(client):
    response = client.post(
        "/api/v1/saved-searches", json={"name": "x", "webhook_url": "ftp://example.com"}
    )
    assert response.status_code == 422


def test_webhook_sent_on_new_matches(session_factory, session, monkeypatch):
    seed(session)
    session.add(
        SavedSearch(
            name="AU hook", country="AU", webhook_url="https://hooks.example.com/jobs"
        )
    )
    session.commit()

    captured: dict = {}
    monkeypatch.setattr(
        "apps.api.alerts.send_webhook",
        lambda url, payload, settings=None, timeout=10.0, **kwargs: captured.update(
            url=url, payload=payload
        )
        or True,
    )
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        worker_main,
        "get_settings",
        lambda: Settings(web_base_url="http://localhost:3000", enable_webhooks=True),
    )

    assert worker_main._cmd_alerts(argparse.Namespace(lookback_hours=24)) == 0
    assert captured["url"] == "https://hooks.example.com/jobs"
    assert captured["payload"]["new_matches"] == 1
    assert captured["payload"]["jobs"][0]["url"].startswith("http://localhost:3000/jobs/")


def test_slack_webhook_payload_shape(session_factory, session, monkeypatch):
    seed(session)
    session.add(
        SavedSearch(
            name="Slack AU",
            country="AU",
            webhook_url="https://hooks.slack.com/services/x",
            webhook_kind="slack",
        )
    )
    session.commit()

    captured: dict = {}
    monkeypatch.setattr(
        "apps.api.alerts.send_webhook",
        lambda url, payload, settings=None, timeout=10.0, **kwargs: captured.update(
            payload=payload
        )
        or True,
    )
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        worker_main,
        "get_settings",
        lambda: Settings(web_base_url="http://localhost:3000", enable_webhooks=True),
    )

    assert worker_main._cmd_alerts(argparse.Namespace(lookback_hours=24)) == 0
    assert "text" in captured["payload"]
    assert "Slack AU" in captured["payload"]["text"]


def test_unsubscribe_deactivates_search(client, session):
    created = client.post(
        "/api/v1/saved-searches", json={"name": "AU", "notify_email": "a@b.com"}
    ).json()
    search = session.get(SavedSearch, created["id"])
    token = search.unsubscribe_token
    assert token

    assert client.get("/api/v1/saved-searches/unsubscribe", params={"token": token}).status_code == 200
    session.expire_all()
    assert session.get(SavedSearch, created["id"]).is_active is False
    assert (
        client.get(
            "/api/v1/saved-searches/unsubscribe", params={"token": "doesnotexist123"}
        ).status_code
        == 404
    )


def test_digest_email_combines_matches(session_factory, session, monkeypatch):
    seed(session)
    session.add(
        SavedSearch(
            name="AU digest",
            country="AU",
            notify_email="me@example.com",
            frequency="digest",
            unsubscribe_token="tok-digest-123",
        )
    )
    session.commit()

    captured: dict = {}

    def fake_send(settings, name, email, jobs, unsubscribe_url=None, digest=False):
        captured.update(digest=digest, count=len(jobs), url=unsubscribe_url)
        return True

    monkeypatch.setattr("apps.api.alerts.send_saved_search_alert", fake_send)
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        worker_main,
        "get_settings",
        lambda: Settings(
            enable_email_alerts=True,
            smtp_host="smtp.example.com",
            alert_from_email="x@y.com",
            web_base_url="http://localhost:3000",
        ),
    )

    assert worker_main._cmd_alerts(argparse.Namespace(lookback_hours=24)) == 0
    assert captured["digest"] is True
    assert captured["count"] == 1
    assert captured["url"] and "token=tok-digest-123" in captured["url"]


def test_worker_alerts_command_sends_email(session_factory, session, monkeypatch):
    seed(session)
    session.add(SavedSearch(name="AU jobs", country="AU", notify_email="me@example.com"))
    session.commit()

    captured: list[tuple[str, str, int]] = []
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        worker_main,
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

    assert worker_main._cmd_alerts(argparse.Namespace(lookback_hours=24)) == 0
    assert captured == [("AU jobs", "me@example.com", 1)]
