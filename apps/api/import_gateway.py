"""Ingestion gateway for user-run local collectors (e.g. LinkedIn).

Local collectors never touch the database directly. They upload
:class:`~apps.api.schemas.ImportJobIn` payloads to ``/api/v1/import/jobs``
authenticated with a device token. Jobs land in the same ``jobs`` table as
platform data but are tagged ``visibility='private'`` and owned by the device,
so they never leak into public search, market comparison or aggregate stats.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.metrics import record_import
from apps.api.models import CollectorDevice, ImportBatch, JobImportProvenance, utcnow
from apps.api.schemas import ImportErrorItem, ImportJobsRequest
from apps.worker.pipeline import persist_job_row_safe
from packages.job_schema import CollectionMode, NormalizedJob, Visibility

MAX_ERRORS = 50


def _to_normalized(item, default_source: str) -> NormalizedJob:
    return NormalizedJob(
        source=item.source or default_source,
        source_job_id=item.source_job_id,
        title=item.title,
        company=item.company,
        description=item.description,
        country=item.country.upper() if item.country else None,
        state=item.state,
        city=item.city,
        remote_type=item.remote_type,
        employment_type=item.employment_type,
        canonical_url=item.canonical_url,
        apply_url=item.apply_url,
        salary_min=item.salary_min,
        salary_max=item.salary_max,
        salary_currency=item.salary_currency,
        salary_period=item.salary_period,
        posted_at=item.posted_at,
        raw_payload=item.raw_payload,
    )


def import_jobs(
    db: Session,
    device: CollectorDevice,
    payload: ImportJobsRequest,
    idempotency_key: str | None = None,
) -> tuple[ImportBatch, list[ImportErrorItem]]:
    """Persist one upload batch. Returns the batch plus any per-item errors.

    Replaying the same ``Idempotency-Key`` returns the original batch instead of
    importing twice.
    """
    if idempotency_key:
        existing = db.scalar(
            select(ImportBatch).where(
                ImportBatch.device_id == device.id,
                ImportBatch.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, []

    batch = ImportBatch(
        device_id=device.id,
        owner_ref=device.owner_ref,
        source=payload.source,
        query=payload.query,
        geo_id=payload.geo_id,
        collection_mode=CollectionMode.USER_LOCAL.value,
        idempotency_key=idempotency_key,
        status="processing",
        received_count=len(payload.jobs),
        started_at=utcnow(),
    )
    db.add(batch)
    try:
        db.flush()
    except IntegrityError:
        # Lost the race against a concurrent upload with the same
        # Idempotency-Key: uq_import_batch_idempotency rejected our insert.
        # Roll back and return the winner instead of failing with a 500.
        db.rollback()
        winner = db.scalar(
            select(ImportBatch).where(
                ImportBatch.device_id == device.id,
                ImportBatch.idempotency_key == idempotency_key,
            )
        )
        if winner is not None:
            return winner, []
        raise

    accepted = 0
    duplicate = 0
    rejected = 0
    errors: list[ImportErrorItem] = []
    seen_job_ids: set[int] = set()

    for index, item in enumerate(payload.jobs):
        try:
            normalized = _to_normalized(item, payload.source)
            action, row = persist_job_row_safe(
                db,
                normalized,
                visibility=Visibility.PRIVATE.value,
                collection_mode=CollectionMode.USER_LOCAL.value,
                owner_device_id=device.id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad item must not fail the batch
            rejected += 1
            if len(errors) < MAX_ERRORS:
                errors.append(
                    ImportErrorItem(index=index, reason=f"{type(exc).__name__}: {exc}")
                )
            continue

        if action == "inserted":
            accepted += 1
        else:
            duplicate += 1

        if row.id not in seen_job_ids:
            seen_job_ids.add(row.id)
            db.add(
                JobImportProvenance(
                    job_id=row.id,
                    batch_id=batch.id,
                    device_id=device.id,
                    owner_ref=device.owner_ref,
                    collection_mode=CollectionMode.USER_LOCAL.value,
                    action=action,
                    source_url=normalized.best_url(),
                    collected_at=item.collected_at,
                )
            )

    batch.accepted_count = accepted
    batch.duplicate_count = duplicate
    batch.rejected_count = rejected
    batch.status = "completed" if rejected == 0 else "partial"
    batch.completed_at = utcnow()
    db.commit()
    db.refresh(batch)
    record_import(accepted=accepted, duplicate=duplicate, rejected=rejected)
    return batch, errors


__all__ = ["import_jobs"]
