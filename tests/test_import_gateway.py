from __future__ import annotations

from sqlalchemy import func, select

from apps.api.models import Job
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def create_device(client, name="laptop", owner="alice@example.com") -> dict:
    response = client.post(
        "/api/v1/import/devices", json={"name": name, "owner": owner}
    )
    assert response.status_code == 201
    return response.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sample_job(**overrides) -> dict:
    payload = {
        "source": "linkedin_user_import",
        "source_job_id": "li-1",
        "title": "Senior Data Analyst",
        "company": "Example",
        "description": "SQL dashboards for the Melbourne team",
        "city": "Melbourne",
        "state": "VIC",
        "country": "AU",
        "canonical_url": "https://www.linkedin.com/jobs/view/li-1",
    }
    payload.update(overrides)
    return payload


def test_device_creation_returns_token_once(client):
    device = create_device(client)
    assert device["token"].startswith("jagg_")
    listed = client.get("/api/v1/import/devices").json()
    assert listed[0]["token_prefix"] == device["token_prefix"]
    assert "token" not in listed[0]


def test_import_creates_private_job_hidden_from_public(client, session):
    device = create_device(client)
    response = client.post(
        "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["duplicate_count"] == 0
    assert body["rejected_count"] == 0

    assert client.get("/api/v1/jobs").json()["total"] == 0
    assert client.get("/api/v1/stats").json()["total_jobs"] == 0

    workspace = client.get("/api/v1/import/jobs", headers=auth(device["token"])).json()
    assert workspace["total"] == 1
    item = workspace["items"][0]
    assert item["job"]["title"] == "Senior Data Analyst"
    assert item["job"]["visibility"] == "private"
    assert item["action"] == "inserted"


def test_import_requires_valid_device_token(client):
    assert client.post("/api/v1/import/jobs", json={"jobs": [sample_job()]}).status_code == 401
    assert (
        client.post(
            "/api/v1/import/jobs",
            headers=auth("jagg_not-a-real-token"),
            json={"jobs": [sample_job()]},
        ).status_code
        == 401
    )


def test_revoked_device_token_is_rejected(client):
    device = create_device(client)
    assert client.post(f"/api/v1/import/devices/{device['id']}/revoke").status_code == 200
    response = client.post(
        "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
    )
    assert response.status_code == 401


def test_duplicate_import_within_device_is_deduped(client, session):
    device = create_device(client)
    first = client.post(
        "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
    ).json()
    second = client.post(
        "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
    ).json()
    assert first["accepted_count"] == 1
    assert second["accepted_count"] == 0
    assert second["duplicate_count"] == 1

    assert session.scalar(select(func.count()).select_from(Job)) == 1
    assert client.get("/api/v1/import/jobs", headers=auth(device["token"])).json()["total"] == 1


def test_devices_do_not_share_private_jobs(client, session):
    device_a = create_device(client, name="a", owner="alice@example.com")
    device_b = create_device(client, name="b", owner="bob@example.com")
    for device in (device_a, device_b):
        client.post(
            "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
        )
    assert session.scalar(select(func.count()).select_from(Job)) == 2

    for device in (device_a, device_b):
        workspace = client.get("/api/v1/import/jobs", headers=auth(device["token"])).json()
        assert workspace["total"] == 1


def test_import_matching_public_job_counts_as_duplicate(client, session):
    persist_job(
        session,
        NormalizedJob(
            source="indeed",
            source_job_id="pub-1",
            title="Senior Data Analyst",
            company="Example",
            description="SQL dashboards for the Melbourne team",
            city="Melbourne",
            state="VIC",
            country="AU",
        ),
    )
    session.commit()

    device = create_device(client)
    body = client.post(
        "/api/v1/import/jobs", headers=auth(device["token"]), json={"jobs": [sample_job()]}
    ).json()
    assert body["duplicate_count"] == 1
    assert body["accepted_count"] == 0
    # The import is attached as a private duplicate of the public row.
    private = session.scalar(
        select(Job).where(Job.visibility == "private")
    )
    assert private is not None and private.duplicate_of is not None
    assert client.get("/api/v1/jobs").json()["total"] == 1


def test_idempotency_key_replays_same_batch(client, session):
    device = create_device(client)
    headers = {**auth(device["token"]), "Idempotency-Key": "abc-123"}
    first = client.post("/api/v1/import/jobs", headers=headers, json={"jobs": [sample_job()]}).json()
    second = client.post("/api/v1/import/jobs", headers=headers, json={"jobs": [sample_job()]}).json()
    assert first["batch_id"] == second["batch_id"]
    assert session.scalar(select(func.count()).select_from(Job)) == 1
    batches = client.get("/api/v1/import/batches", headers=auth(device["token"])).json()
    assert len(batches) == 1


def test_invalid_item_is_rejected_without_failing_batch(client):
    device = create_device(client)
    body = client.post(
        "/api/v1/import/jobs",
        headers=auth(device["token"]),
        json={"jobs": [sample_job(), {"source_job_id": "x", "title": ""}]},
    )
    assert body.status_code == 422
