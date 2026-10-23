from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.alerts import evaluate_search
from apps.api.config import Settings
from apps.api.database import get_db
from apps.api.models import Job, SavedSearch, SourceAuthorization, utcnow
from apps.api.routers import compare, export, jobs, match, saved_searches, source_authorizations
from apps.api.source_authorization import public_job_condition


@pytest.fixture
def auth_client(session, monkeypatch):
    app = FastAPI()
    for module in (export, jobs, compare, match, saved_searches, source_authorizations):
        app.include_router(module.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: session
    settings = Settings(
        api_key="admin-test-key", rate_limit_enabled=False, search_backend="postgres"
    )
    monkeypatch.setattr("apps.api.config.get_settings", lambda: settings)
    monkeypatch.setattr(source_authorizations, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr("apps.api.security.get_settings", lambda: settings)
    with TestClient(app) as client:
        yield client


def add_job(session, source="greenhouse", **fields):
    index = len(session.scalars(select(Job)).all()) + 1
    row = Job(
        source=source,
        source_job_id=str(index),
        title="Python Engineer",
        content_hash=str(index),
        city="Sydney",
        country="AU",
        occupation_group="software-engineer",
        **fields,
    )
    session.add(row)
    session.commit()
    return row


def grant(session, source="greenhouse", **fields):
    values = dict(
        source=source,
        evidence_ref="contract:123",
        approved=True,
        commercial_display=True,
        valid_from=utcnow() - timedelta(days=1),
    )
    values.update(fields)
    row = SourceAuthorization(**values)
    session.add(row)
    session.commit()
    return row


def test_alerts_deny_jobs_without_source_authorization(session):
    session.add(Job(source="greenhouse", source_job_id="1", title="Engineer", content_hash="1"))
    search = SavedSearch(name="engineering")
    session.add(search)
    session.commit()
    result = evaluate_search(session, search)
    assert result["items"] == []
    assert result["total_matches"] == 0


def test_public_condition_requires_valid_authorization(session):
    job = add_job(session)
    assert session.scalar(select(Job.id).where(public_job_condition())) is None
    grant(session, approved=False)
    assert session.scalar(select(Job.id).where(public_job_condition())) is None
    grant(session)
    assert session.scalar(select(Job.id).where(public_job_condition())) == job.id


def test_http_publication_lifecycle(client, session, settings_env):
    job = add_job(session)
    private = add_job(session, visibility="private")
    path = "/api/v1/admin/source-authorizations"
    headers = {"X-API-Key": "admin-test-key"}
    payload = {
        "source": "greenhouse",
        "evidence_ref": "test-contract:123",
        "approved": True,
        "commercial_display": True,
        "valid_from": (utcnow() - timedelta(days=1)).isoformat(),
        "valid_until": (utcnow() + timedelta(days=1)).isoformat(),
    }
    with settings_env(API_KEY="admin-test-key", RATE_LIMIT_ENABLED="false"):
        assert client.get(path).status_code == 401
        assert client.post(path, json=payload).status_code == 401
        assert client.get("/api/v1/jobs").json()["total"] == 0
        assert client.get(f"/api/v1/jobs/{job.id}").status_code == 404
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 201, response.text
        authorization_id = response.json()["id"]
        assert client.get(f"/api/v1/jobs/{job.id}").status_code == 200
        assert client.get(f"/api/v1/jobs/{private.id}").status_code == 404
        assert client.get("/api/v1/jobs").json()["total"] == 1
        assert client.get("/api/v1/stats").json()["total_jobs"] == 1
        payload["approved"] = False
        assert client.put(f"{path}/{authorization_id}", json=payload, headers=headers).status_code == 200
        assert client.get(f"/api/v1/jobs/{job.id}").status_code == 404
        assert client.get("/api/v1/jobs").json()["total"] == 0
        assert client.get("/api/v1/stats").json()["total_jobs"] == 0


@pytest.mark.parametrize("configured_key", ["", " "])
def test_authorization_admin_fails_closed(client, settings_env, configured_key):
    with settings_env(API_KEY=configured_key):
        response = client.get("/api/v1/admin/source-authorizations")
        assert response.status_code == 401


@pytest.mark.parametrize("fields", [
    {"valid_until": utcnow() - timedelta(hours=1)},
    {"valid_from": utcnow() + timedelta(hours=1)},
    {"commercial_display": False},
])
def test_invalid_authorization_denies_http(client, session, fields):
    job = add_job(session)
    grant(session, **fields)
    assert client.get(f"/api/v1/jobs/{job.id}").status_code == 404
    assert client.get("/api/v1/jobs").json()["total"] == 0


def test_board_authorization_does_not_grant_other_boards(session, client):
    from apps.api.models import Board

    first = Board(provider="greenhouse", board_token="first")
    second = Board(provider="greenhouse", board_token="second")
    session.add_all([first, second])
    session.commit()
    allowed = add_job(session, source_board_id=first.id)
    denied = add_job(session, source_board_id=second.id)
    unscoped = add_job(session)
    grant(session, source_board_id=first.id)
    assert client.get(f"/api/v1/jobs/{allowed.id}").status_code == 200
    assert client.get(f"/api/v1/jobs/{denied.id}").status_code == 404
    assert client.get(f"/api/v1/jobs/{unscoped.id}").status_code == 404
