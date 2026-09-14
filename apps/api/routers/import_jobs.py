"""Local-collector import API: device tokens plus job upload/workspace.

Device management requires the operator ``X-API-Key``; the upload and private
workspace endpoints require a per-device ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.import_gateway import import_jobs as run_import
from apps.api.models import CollectorDevice, ImportBatch, Job, JobImportProvenance, utcnow
from apps.api.ratelimit import rate_limit
from apps.api.schemas import (
    DeviceCreated,
    DeviceIn,
    DeviceOut,
    ImportBatchOut,
    ImportedJobOut,
    ImportedJobsResponse,
    ImportJobsRequest,
    ImportJobsResponse,
    JobOut,
)
from apps.api.security import (
    generate_device_token,
    hash_device_token,
    require_api_key,
    require_device_token,
)

router = APIRouter(prefix="/import", tags=["import"])


def _device_out(device: CollectorDevice) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        owner=device.owner_ref,
        platform=device.platform,
        token_prefix=device.token_prefix,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
    )


@router.post(
    "/devices",
    response_model=DeviceCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_device(payload: DeviceIn, db: Session = Depends(get_db)) -> DeviceCreated:
    token = generate_device_token()
    device = CollectorDevice(
        name=payload.name,
        owner_ref=payload.owner,
        platform=payload.platform,
        token_hash=hash_device_token(token),
        token_prefix=token[:12],
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return DeviceCreated(
        id=device.id,
        name=device.name,
        owner=device.owner_ref,
        platform=device.platform,
        token=token,
        token_prefix=device.token_prefix,
        created_at=device.created_at,
    )


@router.get(
    "/devices", response_model=list[DeviceOut], dependencies=[Depends(require_api_key)]
)
def list_devices(db: Session = Depends(get_db)) -> list[DeviceOut]:
    devices = db.scalars(select(CollectorDevice).order_by(CollectorDevice.id.desc())).all()
    return [_device_out(device) for device in devices]


@router.post(
    "/devices/{device_id}/revoke",
    response_model=DeviceOut,
    dependencies=[Depends(require_api_key)],
)
def revoke_device(device_id: int, db: Session = Depends(get_db)) -> DeviceOut:
    device = db.get(CollectorDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if device.revoked_at is None:
        device.revoked_at = utcnow()
        db.commit()
        db.refresh(device)
    return _device_out(device)


@router.post(
    "/jobs",
    response_model=ImportJobsResponse,
    dependencies=[Depends(rate_limit("import"))],
)
def import_jobs(
    payload: ImportJobsRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    device: CollectorDevice = Depends(require_device_token),
    db: Session = Depends(get_db),
) -> ImportJobsResponse:
    batch, errors = run_import(db, device, payload, idempotency_key)
    return ImportJobsResponse(
        batch_id=batch.id,
        status=batch.status,
        received_count=batch.received_count,
        accepted_count=batch.accepted_count,
        duplicate_count=batch.duplicate_count,
        rejected_count=batch.rejected_count,
        errors=errors,
    )


@router.get("/batches", response_model=list[ImportBatchOut])
def list_batches(
    device: CollectorDevice = Depends(require_device_token),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ImportBatch]:
    return list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.device_id == device.id)
            .order_by(ImportBatch.id.desc())
            .limit(limit)
        ).all()
    )


@router.get("/jobs", response_model=ImportedJobsResponse)
def list_imported_jobs(
    device: CollectorDevice = Depends(require_device_token),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ImportedJobsResponse:
    total = (
        db.scalar(
            select(func.count(func.distinct(JobImportProvenance.job_id))).where(
                JobImportProvenance.device_id == device.id
            )
        )
        or 0
    )
    # One row per unique job, using the most recent import as the provenance.
    latest = (
        select(
            JobImportProvenance.job_id.label("job_id"),
            func.max(JobImportProvenance.id).label("provenance_id"),
        )
        .where(JobImportProvenance.device_id == device.id)
        .group_by(JobImportProvenance.job_id)
        .subquery()
    )
    rows = db.execute(
        select(Job, JobImportProvenance)
        .join(latest, latest.c.provenance_id == JobImportProvenance.id)
        .join(Job, Job.id == JobImportProvenance.job_id)
        .order_by(JobImportProvenance.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        ImportedJobOut(
            job=JobOut.model_validate(job),
            batch_id=provenance.batch_id,
            action=provenance.action,
            collected_at=provenance.collected_at,
        )
        for job, provenance in rows
    ]
    return ImportedJobsResponse(total=total, items=items)
