"""End-to-end tests for the import gateway on real PostgreSQL.

These run only when ``TEST_POSTGRES_URL`` is set (CI provides a Postgres
service). Unlike the SQLite unit tests in ``test_import_gateway.py`` they
exercise the real owner-scoped unique indexes, per-item data errors on
``String`` length columns, and the full public-surface isolation sweep.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

PRIVATE_COMPANY = "ZZPrivateCo"
PUBLIC_COMPANY = "ZZPublicCo"


@pytest.fixture(autouse=True)
def _no_rate_limit(settings_env):
    with settings_env(RATE_LIMIT_ENABLED="false"):
        yield


def create_device(client, name="laptop", owner="alice@example.com") -> dict:
    response = client.post("/api/v1/import/devices", json={"name": name, "owner": owner})
    assert response.status_code == 201
    return response.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sample_job(**overrides) -> dict:
    payload = {
        "source": "linkedin_user_import",
        "source_job_id": "li-1",
        "title": "Senior Data Analyst",
        "company": PRIVATE_COMPANY,
        "description": "SQL dashboards for the Melbourne team",
        "city": "Melbourne",
        "state": "VIC",
        "country": "AU",
        "canonical_url": "https://www.linkedin.com/jobs/view/li-1",
    }
    payload.update(overrides)
    return payload


def upload(client, token: str, jobs: list[dict], key: str | None = None, source=None) -> dict:
    headers = auth(token)
    if key:
        headers["Idempotency-Key"] = key
    payload: dict = {"jobs": jobs}
    if source is not None:
        payload["source"] = source
    response = client.post("/api/v1/import/jobs", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Device lifecycle
# ---------------------------------------------------------------------------


def test_revoked_token_blocked_on_every_import_endpoint(pg_client):
    device = create_device(pg_client)
    upload(pg_client, device["token"], [sample_job()])

    response = pg_client.post(
        f"/api/v1/import/devices/{device['id']}/revoke", json={}
    )
    assert response.status_code == 200
    assert response.json()["revoked_at"] is not None

    assert pg_client.post(
        "/api/v1/import/jobs", json={"jobs": [sample_job()]}, headers=auth(device["token"])
    ).status_code == 401
    assert pg_client.get(
        "/api/v1/import/jobs", headers=auth(device["token"])
    ).status_code == 401
    assert pg_client.get(
        "/api/v1/import/batches", headers=auth(device["token"])
    ).status_code == 401


def test_revoke_unknown_device_returns_404(pg_client):
    response = pg_client.post("/api/v1/import/devices/999999/revoke", json={})
    assert response.status_code == 404
    assert response.json()["detail"] == "device not found"


def test_revoke_is_idempotent(pg_client):
    device = create_device(pg_client)
    first = pg_client.post(f"/api/v1/import/devices/{device['id']}/revoke", json={})
    second = pg_client.post(f"/api/v1/import/devices/{device['id']}/revoke", json={})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["revoked_at"] == first.json()["revoked_at"]


def test_device_admin_requires_api_key_when_configured(pg_client, settings_env):
    with settings_env(API_KEY="test-operator-key"):
        missing = pg_client.post(
            "/api/v1/import/devices", json={"name": "d1", "owner": "o"}
        )
        assert missing.status_code == 401

        wrong = pg_client.post(
            "/api/v1/import/devices",
            json={"name": "d1", "owner": "o"},
            headers={"X-API-Key": "wrong"},
        )
        assert wrong.status_code == 401

        created = pg_client.post(
            "/api/v1/import/devices",
            json={"name": "d1", "owner": "o"},
            headers={"X-API-Key": "test-operator-key"},
        )
        assert created.status_code == 201

        # The device-token endpoints themselves never take the operator key.
        listed = pg_client.get("/api/v1/import/devices")
        assert listed.status_code == 401
        upload = pg_client.post(
            "/api/v1/import/jobs",
            json={"jobs": [sample_job()]},
            headers=auth(created.json()["token"]),
        )
        assert upload.status_code == 200


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotency_replay_returns_original_batch(pg_client):
    device = create_device(pg_client)
    key = "replay-key-1"

    first = upload(pg_client, device["token"], [sample_job()], key=key)
    second = upload(
        pg_client,
        device["token"],
        [sample_job(source_job_id="li-other")],  # different payload, same key
        key=key,
    )

    assert second["batch_id"] == first["batch_id"]
    assert second["received_count"] == first["received_count"] == 1
    batches = pg_client.get("/api/v1/import/batches", headers=auth(device["token"]))
    assert len(batches.json()) == 1


def test_concurrent_same_key_returns_winner_batch(pg_client, pg_session, monkeypatch):
    """A replay racing the original upload must not 500 on the unique index."""
    from apps.api import import_gateway
    from apps.api.models import ImportBatch

    device = create_device(pg_client)

    # Simulate the winner committing between the gateway's lookup and insert:
    # pre-create the batch, then make the *first* (pre-check) lookup miss.
    existing = ImportBatch(
        device_id=device["id"],
        owner_ref=device["owner"],
        source="linkedin_user_import",
        collection_mode="user_local",
        idempotency_key="race-key",
        status="completed",
        received_count=1,
    )
    pg_session.add(existing)
    pg_session.commit()

    real_select = import_gateway.select
    calls = {"n": 0}

    def racing_select(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # Race window: the idempotency pre-check misses the committed row.
            return real_select(ImportBatch).where(ImportBatch.device_id == -1)
        return real_select(*args, **kwargs)

    monkeypatch.setattr(import_gateway, "select", racing_select)

    response = pg_client.post(
        "/api/v1/import/jobs",
        json={"jobs": [sample_job()]},
        headers={**auth(device["token"]), "Idempotency-Key": "race-key"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["batch_id"] == existing.id
    assert calls["n"] >= 2  # pre-check missed, winner lookup found the batch


def test_same_key_across_devices_does_not_collide(pg_client):
    device_a = create_device(pg_client, name="a")
    device_b = create_device(pg_client, name="b")
    key = "shared-key"

    first = upload(pg_client, device_a["token"], [sample_job()], key=key)
    second = upload(pg_client, device_b["token"], [sample_job()], key=key)

    assert first["batch_id"] != second["batch_id"]
    assert first["accepted_count"] == 1
    assert second["accepted_count"] == 1  # each device owns its own private row


# ---------------------------------------------------------------------------
# Per-item rejection (unreachable in the SQLite suite: request-level
# validation short-circuits, but overlong columns only fail on PostgreSQL)
# ---------------------------------------------------------------------------


def test_invalid_item_is_rejected_without_failing_batch(pg_client):
    device = create_device(pg_client)
    result = upload(
        pg_client,
        device["token"],
        [
            sample_job(source_job_id="li-ok"),
            sample_job(source_job_id="li-bad", state="X" * 120),  # String(100)
        ],
    )

    assert result["received_count"] == 2
    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 1
    assert result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["index"] == 1
    assert result["errors"][0]["reason"]


def test_error_list_is_capped_at_max_errors(pg_client):
    from apps.api.import_gateway import MAX_ERRORS

    device = create_device(pg_client)
    bad_jobs = [
        sample_job(source_job_id=f"li-bad-{i}", state="X" * 120) for i in range(MAX_ERRORS + 10)
    ]
    result = upload(pg_client, device["token"], bad_jobs)

    assert result["rejected_count"] == MAX_ERRORS + 10
    assert len(result["errors"]) == MAX_ERRORS


# ---------------------------------------------------------------------------
# Provenance and owner-scoped dedup on real indexes
# ---------------------------------------------------------------------------


def test_provenance_recorded_once_per_job_per_batch(pg_client, pg_session):
    from sqlalchemy import select

    from apps.api.models import JobImportProvenance

    device = create_device(pg_client)
    # Same job twice in one payload: one row, one provenance entry.
    result = upload(
        pg_client, device["token"], [sample_job(), sample_job()]
    )

    assert result["accepted_count"] == 1
    assert result["duplicate_count"] == 1
    rows = list(pg_session.scalars(select(JobImportProvenance)).all())
    assert len(rows) == 1
    row = rows[0]
    assert row.device_id == device["id"]
    assert row.action == "inserted"
    assert row.source_url == "https://www.linkedin.com/jobs/view/li-1"
    assert row.owner_ref == device["owner"]


def test_owner_scoped_dedup_enforced_by_real_indexes(pg_client, pg_session):
    from sqlalchemy import func, select

    from apps.api.models import Job

    device_a = create_device(pg_client, name="a")
    device_b = create_device(pg_client, name="b")

    # Same device: second upload of the identical job is deduped.
    upload(pg_client, device_a["token"], [sample_job()])
    dedup = upload(pg_client, device_a["token"], [sample_job()])
    assert dedup["accepted_count"] == 0
    assert dedup["duplicate_count"] == 1

    # Different device: identical (source, source_job_id) is a separate row
    # because uq_jobs_source_job_id is scoped by coalesce(owner_device_id, 0).
    cross = upload(pg_client, device_b["token"], [sample_job()])
    assert cross["accepted_count"] == 1
    assert (
        pg_session.scalar(
            select(func.count()).where(Job.source_job_id == "li-1")
        )
        == 2
    )


def test_cross_link_duplicate_attaches_within_owner_scope(pg_client):
    """Layer-2 dedup: same canonical_url, different source_job_id."""
    device_a = create_device(pg_client, name="a")
    device_b = create_device(pg_client, name="b")

    upload(pg_client, device_a["token"], [sample_job(source_job_id="li-1")])
    # Device B re-hosts the same posting under a new id: against A's row this
    # must still insert (owners never dedup against each other's rows).
    result_b = upload(
        pg_client,
        device_b["token"],
        [sample_job(source_job_id="li-other-id")],
    )
    assert result_b["accepted_count"] == 1

    # Device B importing *its own* posting again under a fresh id attaches as
    # a cross-link duplicate of its own row.
    second = upload(
        pg_client,
        device_b["token"],
        [sample_job(source_job_id="li-third-id")],
    )
    assert second["duplicate_count"] == 1


# ---------------------------------------------------------------------------
# Private-data isolation across every public surface
# ---------------------------------------------------------------------------


def _seed_public_job(pg_session):
    import datetime as dt

    from apps.api.models import SourceAuthorization, utcnow
    from apps.worker.pipeline import persist_job
    from packages.job_schema import NormalizedJob

    persist_job(
        pg_session,
        NormalizedJob(
            source="greenhouse",
            source_job_id="pub-1",
            title="Public Platform Engineer",
            company=PUBLIC_COMPANY,
            description="Build public platform services",
            city="Austin",
            state="TX",
            country="US",
            remote_type="remote",
            employment_type="full_time",
            canonical_url="https://example.com/jobs/pub-1",
            apply_url="https://example.com/jobs/pub-1",
            posted_at=dt.datetime.now(dt.UTC),
        ),
    )
    pg_session.add(
        SourceAuthorization(
            source="greenhouse",
            evidence_ref="test-license:import-gateway-e2e:public-seed",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
    )
    pg_session.commit()


def _import_private_job(pg_client, token: str) -> dict:
    return upload(
        pg_client,
        token,
        [
            sample_job(
                source_job_id="priv-1",
                title="Private Analyst Role",
                company=PRIVATE_COMPANY,
            )
        ],
    )


def test_private_jobs_never_leak_to_public_surfaces(pg_client, pg_session):
    _seed_public_job(pg_session)
    device = create_device(pg_client)
    result = _import_private_job(pg_client, device["token"])
    assert result["accepted_count"] == 1

    # The public search (PostgreSQL full-text on title/company/description)
    # matches only the public job, never the private one.
    search = pg_client.get("/api/v1/jobs", params={"q": "analyst"})
    assert search.status_code == 200
    assert search.json()["total"] == 0  # only the private job is an analyst role

    search_public = pg_client.get("/api/v1/jobs", params={"q": "platform"})
    assert search_public.status_code == 200
    assert search_public.json()["total"] == 1
    assert search_public.json()["items"][0]["company"] == PUBLIC_COMPANY

    # Public job visible, private job 404 on the detail endpoint.
    from sqlalchemy import select

    from apps.api.models import Job

    private_job = pg_session.scalar(select(Job).where(Job.source_job_id == "priv-1"))
    public_job = pg_session.scalar(select(Job).where(Job.source_job_id == "pub-1"))
    assert pg_client.get(f"/api/v1/jobs/{private_job.id}").status_code == 404
    assert pg_client.get(f"/api/v1/jobs/{public_job.id}").status_code == 200

    # Export CSV excludes private rows.
    export = pg_client.get("/api/v1/jobs/export", params={"format": "csv"})
    assert export.status_code == 200
    assert PRIVATE_COMPANY not in export.text
    assert PUBLIC_COMPANY in export.text

    # Sources and stats count only public data.
    sources = pg_client.get("/api/v1/sources").json()
    assert "linkedin_user_import" not in sources["counts"]
    assert sources["counts"]["greenhouse"] == 1

    stats = pg_client.get("/api/v1/stats").json()
    assert stats["total_jobs"] == 1

    # Match, compare and runs return 200 without exposing the private row.
    match = pg_client.post(
        "/api/v1/match",
        json={"resume": "data analyst with SQL and Python", "limit": 50},
    )
    assert match.status_code == 200
    assert PRIVATE_COMPANY not in match.text

    compare = pg_client.get(
        "/api/v1/compare", params={"area_a_country": "US", "area_b_country": "AU"}
    )
    assert compare.status_code == 200
    assert PRIVATE_COMPANY not in compare.text

    runs = pg_client.get("/api/v1/runs")
    assert runs.status_code == 200
    assert PRIVATE_COMPANY not in runs.text

    # Saved-search evaluation matches only public jobs.
    saved = pg_client.post(
        "/api/v1/saved-searches",
        json={"name": "leak-probe-private", "keywords": "analyst"},
    )
    assert saved.status_code == 201
    private_probe_id = saved.json()["id"]
    run = pg_client.post(f"/api/v1/saved-searches/{private_probe_id}/run")
    assert run.status_code == 200
    assert run.json()["new_matches"] == 0
    assert run.json()["total_matches"] == 0
    matches = pg_client.get(f"/api/v1/saved-searches/{private_probe_id}/matches")
    assert matches.status_code == 200
    assert matches.json() == []

    saved_public = pg_client.post(
        "/api/v1/saved-searches",
        json={"name": "leak-probe-public", "keywords": "platform"},
    )
    assert saved_public.status_code == 201
    run_public = pg_client.post(
        f"/api/v1/saved-searches/{saved_public.json()['id']}/run"
    )
    assert run_public.status_code == 200
    assert run_public.json()["total_matches"] == 1

    # The device's own workspace still sees its private row.
    workspace = pg_client.get("/api/v1/import/jobs", headers=auth(device["token"]))
    assert workspace.status_code == 200
    assert workspace.json()["total"] == 1
    assert workspace.json()["items"][0]["job"]["company"] == PRIVATE_COMPANY


def test_import_matching_public_job_counts_as_duplicate(pg_client, pg_session):
    """A private import of a public posting attaches as a duplicate of it."""
    _seed_public_job(pg_session)
    device = create_device(pg_client)
    result = upload(
        pg_client,
        device["token"],
        [
            sample_job(
                source_job_id="priv-dup-of-pub",
                title="Public Platform Engineer",
                company=PUBLIC_COMPANY,
                description="Build public platform services",
                city="Austin",
                state="TX",
                country="US",
                canonical_url="https://example.com/jobs/pub-1",
            )
        ],
    )

    # Same canonical_url as the public row -> layer-2 duplicate.
    assert result["accepted_count"] == 0
    assert result["duplicate_count"] == 1

    from sqlalchemy import func, select

    from apps.api.models import Job

    # A cross-link duplicate creates its own row pointing at the public one.
    assert pg_session.scalar(select(func.count()).select_from(Job)) == 2
    private_row = pg_session.scalar(
        select(Job).where(Job.source_job_id == "priv-dup-of-pub")
    )
    public_row = pg_session.scalar(select(Job).where(Job.source_job_id == "pub-1"))
    assert private_row is not None
    assert private_row.duplicate_of == public_row.id
    assert private_row.visibility == "private"
    assert public_row.visibility == "public"
    assert public_row.duplicate_of is None
