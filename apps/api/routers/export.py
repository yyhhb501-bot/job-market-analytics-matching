"""Job export endpoints: CSV, JSON and XLSX with the same filters as search."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.filters import build_conditions
from apps.api.models import Job
from apps.api.ratelimit import rate_limit

router = APIRouter(tags=["export"])

COLUMNS = [
    "id",
    "source",
    "source_job_id",
    "title",
    "company",
    "city",
    "state",
    "country",
    "remote_type",
    "employment_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "posted_at",
    "first_seen_at",
    "apply_url",
    "canonical_url",
]

MAX_ROWS = 50000


def _serialize(job: Job) -> dict:
    record: dict[str, object] = {}
    for column in COLUMNS:
        value = getattr(job, column, None)
        record[column] = value.isoformat() if isinstance(value, datetime) else value
    return record


def export_conditions(
    *,
    q: str | None,
    source: list[str] | None,
    country: list[str] | None,
    state: list[str] | None,
    city: list[str] | None,
    company: list[str] | None,
    remote_type: list[str] | None,
    employment_type: list[str] | None,
    min_salary: float | None,
    posted_after: datetime | None,
    include_duplicates: bool,
    dialect_name: str,
) -> list:
    conditions = build_conditions(
        q=q,
        dialect_name=dialect_name,
        sources=source,
        countries=country,
        states=state,
        cities=city,
        companies=company,
        remote_types=remote_type,
        employment_types=employment_type,
        min_salary=min_salary,
        posted_after=posted_after,
    )
    if not include_duplicates:
        conditions.append(Job.duplicate_of.is_(None))
    conditions.append(Job.is_active.is_(True))
    return conditions


@router.get("/jobs/export", dependencies=[Depends(rate_limit("export"))])
def export_jobs(
    db: Session = Depends(get_db),
    format: str = Query(default="csv", pattern="^(csv|json|xlsx)$"),
    limit: int = Query(default=5000, ge=1, le=MAX_ROWS),
    q: str | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    company: list[str] | None = Query(default=None),
    remote_type: list[str] | None = Query(default=None),
    employment_type: list[str] | None = Query(default=None),
    min_salary: float | None = Query(default=None, ge=0),
    posted_after: datetime | None = Query(default=None),
    include_duplicates: bool = Query(default=False),
) -> Response:
    conditions = export_conditions(
        q=q,
        source=source,
        country=country,
        state=state,
        city=city,
        company=company,
        remote_type=remote_type,
        employment_type=employment_type,
        min_salary=min_salary,
        posted_after=posted_after,
        include_duplicates=include_duplicates,
        dialect_name=db.get_bind().dialect.name,
    )
    rows = db.scalars(
        select(Job)
        .where(*conditions)
        .order_by(Job.posted_at.desc().nullslast(), Job.id.desc())
        .limit(limit)
    ).all()
    records = [_serialize(job) for job in rows]

    if format == "json":
        return JSONResponse(records)

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="jobs.csv"'},
        )

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "jobs"
    sheet.append(COLUMNS)
    for record in records:
        sheet.append([record.get(column) for column in COLUMNS])
    output = io.BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="jobs.xlsx"'},
    )
