"""Local-collector import API: device tokens plus job upload/workspace.

Device management requires the operator ``X-API-Key``; the upload and private
workspace endpoints require a per-device ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select
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
from packages.seek_policy import SEEK_DAILY_TARGET, SEEK_HOURLY_LIMIT, SEEK_IMPORT_SOURCE

router = APIRouter(prefix="/import", tags=["import"])


def _seek_progress(db: Session, device_id: int | None = None) -> dict:
    """Return truthful SEEK RN progress for the admin UI and extension."""
    now = utcnow().astimezone(dt.UTC)
    beijing = now.astimezone(dt.timezone(dt.timedelta(hours=8)))
    day = beijing.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    conditions = [
        Job.source == SEEK_IMPORT_SOURCE,
        Job.visibility == "private",
        Job.duplicate_of.is_(None),
    ]
    if device_id is not None:
        conditions.append(Job.owner_device_id == device_id)
    today = int(db.scalar(select(func.count()).select_from(Job).where(*conditions,Job.first_seen_at >= day)) or 0)
    hour_conditions = [*conditions, Job.first_seen_at >= hour]
    this_hour = int(db.scalar(select(func.count()).select_from(Job).where(*hour_conditions)) or 0)

    recent_conditions = [
        Job.source == SEEK_IMPORT_SOURCE,
        Job.visibility == "private",
        Job.duplicate_of.is_(None),
        Job.first_seen_at >= now - dt.timedelta(days=7),
    ]
    if device_id is not None:
        recent_conditions.append(Job.owner_device_id == device_id)
    recent = db.scalars(select(Job).where(*recent_conditions)).all()
    by_state = Counter((job.state or "unknown").upper() for job in recent)
    by_specialty: Counter[str] = Counter()
    salary_count = 0
    visa_count = 0
    for job in recent:
        raw = job.raw_payload if isinstance(job.raw_payload, dict) else {}
        for tag in raw.get("specialty_tags") or []:
            by_specialty[str(tag)] += 1
        if job.salary_min is not None:
            salary_count += 1
        if raw.get("visa_sponsorship") is True:
            visa_count += 1

    batch_conditions = [ImportBatch.source == SEEK_IMPORT_SOURCE]
    if device_id is not None:
        batch_conditions.append(ImportBatch.device_id == device_id)
    duplicate_count = int(
        db.scalar(select(func.coalesce(func.sum(ImportBatch.duplicate_count), 0)).where(*batch_conditions)) or 0
    )
    rejected_count = int(
        db.scalar(select(func.coalesce(func.sum(ImportBatch.rejected_count), 0)).where(*batch_conditions)) or 0
    )
    last_success = db.scalar(
        select(ImportBatch.completed_at)
        .where(*batch_conditions, ImportBatch.accepted_count > 0)
        .order_by(ImportBatch.id.desc())
        .limit(1)
    )
    status = "done" if today >= SEEK_DAILY_TARGET else "waiting" if this_hour >= SEEK_HOURLY_LIMIT else "running"
    next_run = hour + dt.timedelta(hours=1) if status == "waiting" else None
    return {
        "today_valid": today,
        "today_target": SEEK_DAILY_TARGET,
        "hour_valid": this_hour,
        "hour_limit": SEEK_HOURLY_LIMIT,
        "recent_7d_valid": len(recent),
        "by_state": dict(by_state),
        "by_specialty": dict(by_specialty),
        "salary_rate": round(salary_count / len(recent), 4) if recent else 0,
        "visa_sponsorship_count": visa_count,
        "duplicate_count": duplicate_count,
        "rejected_count": rejected_count,
        "last_success_at": last_success,
        "status": status,
        "next_run_at": next_run,
    }


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


@router.get("/admin", dependencies=[Depends(require_api_key)])
def import_admin(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, max_length=200),
    country: str | None = Query(default=None, max_length=2),
    job_status: str = Query(default='active', pattern='^(active|closed|pending|all)$'),
    db: Session = Depends(get_db),
) -> dict:
    """Operator-only view across every local collector device."""
    total_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.visibility == "private")) or 0
    total_batches = db.scalar(select(func.count()).select_from(ImportBatch)) or 0
    country_rows = db.execute(
        select(Job.country, func.count(Job.id))
        .where(Job.visibility == "private")
        .group_by(Job.country)
        .order_by(func.count(Job.id).desc())
    ).all()
    latest_batch = db.scalar(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(1))
    seek = _seek_progress(db)
    filters = [Job.visibility == "private"]
    if job_status == 'active':
        filters.append(Job.is_active.is_(True))
    elif job_status == 'closed':
        filters.append(Job.is_active.is_(False))
    elif job_status == 'pending':
        filters.append(Job.raw_payload['lifecycle']['status'].as_string() == 'unknown')
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(Job.title.ilike(pattern), Job.company.ilike(pattern), Job.description.ilike(pattern)))
    if country and country.strip():
        filters.append(Job.country == country.strip().upper())
    matched_jobs = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    latest_provenance = (
        select(
            JobImportProvenance.job_id.label("job_id"),
            func.max(JobImportProvenance.id).label("provenance_id"),
        )
        .group_by(JobImportProvenance.job_id)
        .subquery()
    )
    rows = db.execute(
        select(Job, JobImportProvenance, CollectorDevice)
        .join(latest_provenance, latest_provenance.c.job_id == Job.id)
        .join(JobImportProvenance, JobImportProvenance.id == latest_provenance.c.provenance_id)
        .join(CollectorDevice, CollectorDevice.id == JobImportProvenance.device_id)
        .where(*filters)
        .order_by(JobImportProvenance.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    batches = db.execute(
        select(ImportBatch, CollectorDevice)
        .join(CollectorDevice, CollectorDevice.id == ImportBatch.device_id)
        .order_by(ImportBatch.id.desc())
        .limit(20)
    ).all()
    return {
        "summary": {
            "total_jobs": total_jobs,
            "total_batches": total_batches,
            "devices": db.scalar(select(func.count()).select_from(CollectorDevice)) or 0,
            "latest_import_at": latest_batch.completed_at if latest_batch else None,
            "by_country": {country or "unknown": count for country, count in country_rows},
            "seek": seek,
        },
        "jobs": {
            "total": matched_jobs,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "job": JobOut.model_validate(job).model_dump(mode="json"),
                    "batch_id": provenance.batch_id,
                    "action": provenance.action,
                    "collected_at": provenance.collected_at,
                    "imported_at": provenance.created_at,
                    "device": {"id": device.id, "name": device.name, "owner": device.owner_ref},
                }
                for job, provenance, device in rows
            ],
        },
        "batches": [
            {
                "id": batch.id,
                "device": {"id": device.id, "name": device.name},
                "status": batch.status,
                "received_count": batch.received_count,
                "accepted_count": batch.accepted_count,
                "duplicate_count": batch.duplicate_count,
                "rejected_count": batch.rejected_count,
                "started_at": batch.started_at,
                "completed_at": batch.completed_at,
                "error": batch.error,
            }
            for batch, device in batches
        ],
    }


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
    progress = _seek_progress(db, device.id) if payload.source == SEEK_IMPORT_SOURCE else None
    return ImportJobsResponse(
        batch_id=batch.id,
        status=batch.status,
        received_count=batch.received_count,
        accepted_count=batch.accepted_count,
        duplicate_count=batch.duplicate_count,
        rejected_count=batch.rejected_count,
        errors=errors,
        progress=progress,
    )


@router.get("/seek/progress")
def seek_device_progress(
    device: CollectorDevice = Depends(require_device_token),
    db: Session = Depends(get_db),
) -> dict:
    return {**_seek_progress(db, device.id), "checked_at": utcnow(), "timezone": "Asia/Shanghai"}


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
