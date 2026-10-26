"""Public collection dashboard endpoint: whitelisted fields, Beijing windows."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from apps.api.models import (
    CollectorDevice,
    CollectorRun,
    ImportBatch,
    SourceAuthorization,
    utcnow,
)
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def test_old_upload_stays_visible_with_zero_today_and_stale_device(client, session):
    device_id = _device_id(session)
    device = session.get(CollectorDevice, device_id)
    device.last_seen_at = utcnow() - timedelta(days=2)
    batch = ImportBatch(
        device_id=device_id,
        owner_ref="hidden-owner",
        source="seek_user_import",
        status="completed",
        received_count=1,
        accepted_count=1,
        duplicate_count=0,
        rejected_count=0,
        started_at=utcnow() - timedelta(days=2),
        completed_at=utcnow() - timedelta(days=2),
    )
    session.add(batch)
    session.commit()
    body = client.get("/api/v1/collection/overview").json()
    row = next(row for row in body["local_uploads"] if row["source"] == "seek_user_import")
    assert row["today_accepted_bj"] == 0 and row["last_batch_id"] == batch.id
    assert row["collector_state"] == "stale"
    assert any(row["source"] == "linkedin_user_import" for row in body["local_uploads"])


def _device_id(session) -> int:
    import hashlib

    token = "test-device-token"
    device = CollectorDevice(
        name="test device",
        owner_ref="hidden-owner",
        platform="seek",
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_prefix="tst_",
    )
    session.add(device)
    session.commit()
    return device.id


def _seed(session, *, source: str, source_job_id: str) -> None:
    persist_job(
        session,
        NormalizedJob(
            source=source,
            source_job_id=source_job_id,
            title="Software Engineer",
            company="Acme",
            description="Python backend",
            city="Austin",
            country="US",
        ),
    )


def test_collection_overview_whitelist_and_counts(client, session):
    session.add(
        SourceAuthorization(
            source="seek",
            evidence_ref="test-license:collection:seek",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
    )
    session.commit()
    _seed(session, source="seek", source_job_id="c-1")
    _seed(session, source="seek", source_job_id="c-2")
    _seed(session, source="greenhouse", source_job_id="c-3")
    session.commit()

    device_row = session.execute(select(ImportBatch)).scalar_one_or_none()
    assert device_row is None

    body = client.get("/api/v1/collection/overview").json()

    by_source = {row["source"]: row for row in body["sources"]}
    assert by_source["seek"]["internal_total"] == 2
    assert by_source["seek"]["public_total"] == 2  # authorization approved above
    assert by_source["greenhouse"]["public_total"] == 0  # no authorization record
    assert by_source["greenhouse"]["internal_total"] == 1
    assert body["daily_target_per_source"] == 600
    assert body["trend_scope"] == "internal"

    # Whitelist: no token/owner/query/idempotency/error fields anywhere.
    serialized = str(body)
    for forbidden in ("token", "owner", "idempotency", "query", "error"):
        assert forbidden not in serialized, forbidden


def test_collection_overview_beijing_today_window(client, session):
    session.add(
        SourceAuthorization(
            source="seek",
            evidence_ref="test-license:collection:seek2",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
    )
    session.commit()
    _seed(session, source="seek", source_job_id="bj-1")
    session.commit()

    batch = ImportBatch(
        device_id=_device_id(session),
        owner_ref="hidden-owner",
        source="seek_user_import",
        status="accepted",
        received_count=1,
        accepted_count=1,
        duplicate_count=0,
        rejected_count=0,
        started_at=utcnow(),
        completed_at=utcnow(),
    )
    session.add(batch)
    session.commit()

    body = client.get("/api/v1/collection/overview").json()
    seek = next(row for row in body["sources"] if row["source"] == "seek")
    assert seek["today_new_bj"] >= 1

    uploads = {row["source"]: row for row in body["local_uploads"]}
    upload = uploads["seek_user_import"]
    assert upload["today_accepted_bj"] == 1
    assert upload["last_batch_status"] == "accepted"
    assert upload["collector_state"] in ("online", "stale", "offline", "none")


def test_collection_overview_last_run_status(client, session):
    _seed(session, source="seek", source_job_id="run-1")
    session.commit()
    session.add(
        CollectorRun(
            source="seek",
            status="success",
            jobs_seen=5,
            jobs_inserted=1,
            started_at=utcnow() - timedelta(minutes=5),
            finished_at=utcnow(),
        )
    )
    session.commit()

    body = client.get("/api/v1/collection/overview").json()
    seek = next(row for row in body["sources"] if row["source"] == "seek")
    assert seek["last_run_status"] == "success"
    assert seek["last_run_at"] is not None
