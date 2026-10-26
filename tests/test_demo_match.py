"""Anonymous demo match endpoint: keyless access, strict caps, honest fallback."""

from __future__ import annotations

import pytest

from tests.test_semantic import _persist_embedded_job


@pytest.fixture(autouse=True)
def isolated_rate_windows():
    from apps.api.ratelimit import _limiters

    _limiters.clear()
    yield
    _limiters.clear()


def test_demo_match_works_without_api_key(client, session):
    _persist_embedded_job(session, embedding_model="local")

    body = client.post("/api/v1/demo/match", json={"resume": "Python AWS pipelines"}).json()
    assert body["engine"].startswith("semantic")
    assert len(body["results"]) >= 1
    assert body["results"][0]["semantic_score"] is not None


def test_demo_match_rejects_oversized_resume(client, session):
    _persist_embedded_job(session, embedding_model="local")

    response = client.post("/api/v1/demo/match", json={"resume": "x" * 8001})
    assert response.status_code == 422
    assert "8000" in response.json()["detail"]


def test_demo_match_caps_results_at_ten(client, session):
    _persist_embedded_job(session, embedding_model="local")

    body = client.post(
        "/api/v1/demo/match", json={"resume": "Python AWS pipelines", "limit": 100}
    ).json()
    assert len(body["results"]) <= 10


def test_member_match_still_requires_api_key(client, session):
    """The demo endpoint being keyless must not open the member endpoint:
    dropping the X-API-Key header is rejected while the demo path is not."""
    _persist_embedded_job(session, embedding_model="local")

    denied = client.post("/api/v1/match", json={"resume": "Python"}, headers={"X-API-Key": ""})
    assert denied.status_code in (401, 403)

    allowed = client.post("/api/v1/demo/match", json={"resume": "Python"})
    assert allowed.status_code == 200


def test_matching_cannot_bypass_public_source_authorization(client, session):
    from sqlalchemy import select

    from apps.api.models import Job, SourceAuthorization

    _persist_embedded_job(session)
    authorization = session.scalars(select(SourceAuthorization)).one()
    authorization.approved = False
    session.commit()
    for endpoint in ("/api/v1/demo/match", "/api/v1/match"):
        result = client.post(endpoint, json={"resume": "Python AWS pipelines"})
        assert result.status_code == 200
        assert result.json()["results"] == []
    authorization.approved = True
    session.scalars(select(Job)).one().visibility = "private"
    session.commit()
    assert client.post("/api/v1/demo/match", json={"resume": "Python"}).json()["results"] == []


def test_explicit_examples_are_fictional_computed_and_never_persisted(client, session):
    from sqlalchemy import func, select

    from apps.api.models import Job

    before = session.scalar(select(func.count()).select_from(Job))
    response = client.post(
        "/api/v1/demo/examples/match",
        json={"resume": "Registered Nurse AHPRA ICU critical care", "country": "AU"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data_scope"] == "illustrative_examples"
    assert body["engine"] == "semantic+local"
    assert body["results"] and all(row["job"]["country"] == "AU" for row in body["results"])
    assert body["results"][0]["job"]["title"] == "Registered Nurse - Critical Care"
    assert all(
        row["job"]["source"] == "illustrative_example" and row["job"]["canonical_url"] is None
        for row in body["results"]
    )
    assert all(row["semantic_score"] is not None for row in body["results"])
    assert session.scalar(select(func.count()).select_from(Job)) == before


def test_examples_and_public_jobs_share_the_demo_rate_budget(client, settings_env):
    with settings_env(
        RATE_LIMIT_ENABLED="true", RATE_LIMIT_BACKEND="memory", DEMO_MATCH_RATE_LIMIT_PER_MINUTE="2"
    ):
        assert client.post("/api/v1/demo/match", json={"resume": "Python"}).status_code == 200
        assert (
            client.post("/api/v1/demo/examples/match", json={"resume": "Python"}).status_code == 200
        )
        assert (
            client.post("/api/v1/demo/examples/match", json={"resume": "Python"}).status_code == 429
        )
