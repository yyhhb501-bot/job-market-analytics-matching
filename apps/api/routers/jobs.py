"""Job search endpoints.

Runs on PostgreSQL full-text search by default and transparently uses
OpenSearch when ``SEARCH_BACKEND=opensearch`` (falling back to PostgreSQL on
any OpenSearch error).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.filters import build_conditions, relevance_order
from apps.api.models import Job
from apps.api.schemas import (
    CountryCount,
    JobOut,
    JobSearchResponse,
    SourceCount,
    StatsResponse,
)
from apps.api.source_authorization import public_job_condition
from packages.fx import convert_job_salary
from packages.job_schema import ATS_SOURCES, Source
from packages.search import build_search_backend

logger = logging.getLogger("jobagg.api.jobs")

router = APIRouter(tags=["jobs"])

_SORT_COLUMNS = {
    "posted_at": Job.posted_at,
    "first_seen_at": Job.first_seen_at,
    "last_seen_at": Job.last_seen_at,
    "salary_max": Job.salary_max,
    "id": Job.id,
}
_ALLOWED_SORTS = set(_SORT_COLUMNS) | {"relevance"}


def _apply(statement: Select, conditions: list) -> Select:
    for condition in conditions:
        statement = statement.where(condition)
    return statement


def _load_ordered(db: Session, ids: list[int], conditions: list | None = None) -> list[Job]:
    if not ids:
        return []
    rows = db.scalars(
        select(Job).where(Job.id.in_(ids), public_job_condition(), *(conditions or []))
    ).all()
    by_id = {row.id: row for row in rows}
    return [by_id[job_id] for job_id in ids if job_id in by_id]


def _serialize(rows: list[Job], currency: str | None) -> list[JobOut]:
    items = [JobOut.model_validate(row) for row in rows]
    if currency:
        target = currency.upper()
        rates = get_settings().fx_rate_map
        items = [
            item.model_copy(update=convert_job_salary(item, target, rates)) for item in items
        ]
    return items


@router.get("/jobs", response_model=JobSearchResponse)
def search_jobs(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="Free-text query over title/company/description"),
    source: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    company: list[str] | None = Query(default=None),
    remote_type: list[str] | None = Query(default=None),
    employment_type: list[str] | None = Query(default=None),
    min_salary: float | None = Query(default=None, ge=0),
    posted_after: datetime | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3, description="Display currency"),
    include_duplicates: bool = Query(default=False, description="Include cross-posted duplicates"),
    sort: str = Query(default="posted_at", description="posted_at | relevance | salary_max | ..."),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> JobSearchResponse:
    if sort not in _ALLOWED_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {sorted(_ALLOWED_SORTS)}")

    dialect = db.get_bind().dialect.name
    conditions = build_conditions(
        q=q,
        dialect_name=dialect,
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
    total = db.scalar(_apply(select(func.count()).select_from(Job), conditions)) or 0

    backend = build_search_backend(get_settings())
    if backend is not None:
        try:
            hits = backend.search(
                q=q,
                sources=source,
                countries=country,
                states=state,
                cities=city,
                companies=company,
                remote_types=remote_type,
                employment_types=employment_type,
                min_salary=min_salary,
                posted_after=posted_after,
                include_duplicates=include_duplicates,
                sort=sort,
                order=order,
                page=page,
                page_size=page_size,
            )
            rows = _load_ordered(db, hits.ids, conditions)
            expected = min(page_size, max(0, total - (page - 1) * page_size))
            if hits.total == total and len(rows) == len(hits.ids) == expected:
                return JobSearchResponse(
                    items=_serialize(rows, currency),
                    total=total,
                    page=page,
                    page_size=page_size,
                )
        except Exception as exc:  # noqa: BLE001 - always fall back to PostgreSQL
            logger.warning("opensearch search failed (%s); falling back to postgres", exc)

    base = _apply(select(Job), conditions)

    if sort == "relevance" and q and dialect == "postgresql":
        ordered = base.order_by(relevance_order(q))
    elif sort == "relevance":
        ordered = base.order_by(Job.posted_at.desc().nullslast())
    else:
        sort_col = _SORT_COLUMNS[sort]
        ordered = base.order_by(
            sort_col.desc().nullslast() if order == "desc" else sort_col.asc().nullsfirst()
        )
    rows = db.scalars(ordered.offset((page - 1) * page_size).limit(page_size)).all()

    return JobSearchResponse(
        items=_serialize(rows, currency), total=total, page=page, page_size=page_size
    )


@router.get("/fx")
def list_fx_rates() -> dict:
    settings = get_settings()
    return {"base": settings.fx_base_currency.upper(), "rates": settings.fx_rate_map}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    job = db.scalar(select(Job).where(Job.id == job_id, public_job_condition()))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut.model_validate(job)


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    counts = dict(
        db.execute(
            select(Job.source, func.count())
            .where(public_job_condition())
            .group_by(Job.source)
        ).all()
    )
    enabled = {
        Source.GREENHOUSE.value: settings.enable_ats,
        Source.LEVER.value: settings.enable_ats,
        Source.ASHBY.value: settings.enable_ats,
        Source.WORKABLE.value: settings.enable_ats,
        Source.SMARTRECRUITERS.value: settings.enable_ats,
        Source.RECRUITEE.value: settings.enable_ats,
        Source.BREEZY.value: settings.enable_ats,
        Source.WORKDAY.value: settings.enable_ats,
        Source.PERSONIO.value: settings.enable_ats,
        Source.TEAMTAILOR.value: settings.enable_ats,
        Source.BAMBOOHR.value: settings.enable_ats,
        Source.JAZZHR.value: settings.enable_ats,
        Source.PINPOINT.value: settings.enable_ats,
        Source.RIPPLING.value: settings.enable_ats,
        Source.JOBVITE.value: settings.enable_ats,
        Source.USAJOBS.value: settings.enable_usajobs,
        Source.SEEK.value: settings.enable_seek,
        Source.INDEED.value: settings.enable_jobspy,
        Source.GLASSDOOR.value: settings.enable_jobspy,
        Source.GOOGLE.value: settings.enable_jobspy,
        Source.ZIPRECRUITER.value: settings.enable_jobspy,
        Source.REMOTEOK.value: settings.enable_remoteok,
        Source.LINKEDIN.value: settings.enable_linkedin,
        Source.ADZUNA.value: settings.enable_adzuna,
    }
    return {
        "known": sorted({s.value for s in Source} | set(counts)),
        "ats": sorted(ATS_SOURCES),
        "enabled": enabled,
        "counts": counts,
    }


@router.get("/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)) -> StatsResponse:
    public = public_job_condition()
    total = db.scalar(select(func.count()).select_from(Job).where(public)) or 0
    active = (
        db.scalar(
            select(func.count()).select_from(Job).where(Job.is_active.is_(True), public)
        )
        or 0
    )
    by_source = [
        SourceCount(source=source, count=count)
        for source, count in db.execute(
            select(Job.source, func.count())
            .where(public)
            .group_by(Job.source)
            .order_by(func.count().desc())
        ).all()
    ]
    by_country = [
        CountryCount(country=country, count=count)
        for country, count in db.execute(
            select(Job.country, func.count())
            .where(public)
            .group_by(Job.country)
            .order_by(func.count().desc())
        ).all()
    ]
    return StatsResponse(total_jobs=total, active_jobs=active, by_source=by_source, by_country=by_country)
