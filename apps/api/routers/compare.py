"""Two-region job-market comparison.

Aggregates an occupation across two areas (country/state/city) over a time
window: job counts, new jobs, remote ratio, salary median/coverage, top skills
and companies, daily trend and source mix. All figures are computed with the
same filters so the two areas are directly comparable.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from statistics import median

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import Job
from apps.api.schemas import (
    CompareAreaMetrics,
    CompareComparison,
    CompareDataQuality,
    CompareResponse,
    LocationOut,
    OccupationOut,
)
from apps.api.source_authorization import public_job_condition
from packages.fx import convert

router = APIRouter(tags=["compare"])

SAMPLE_LIMIT = 4000
TOP_SKILLS = 20
TOP_COMPANIES = 10


def _occupation_condition(q: str):
    phrase = q.strip().lower()
    slug = "-".join(phrase.split())
    return or_(Job.occupation_group == slug, Job.title.ilike(f"%{phrase}%"))


def _area_conditions(
    q: str | None, country: str | None, state: str | None, city: str | None, dedup: bool
) -> list:
    conditions = [Job.is_active.is_(True), public_job_condition()]
    if dedup:
        conditions.append(Job.duplicate_of.is_(None))
    if q:
        conditions.append(_occupation_condition(q))
    if country:
        conditions.append(Job.country == country.upper())
    if state:
        conditions.append(Job.state == state)
    if city:
        conditions.append(Job.city.ilike(city))
    return conditions


def _label(country: str | None, state: str | None, city: str | None) -> str:
    parts = [city, state, country.upper() if country else None]
    return ", ".join(str(part) for part in parts if part) or "全部地区"


def _metrics(
    db: Session,
    *,
    q: str | None,
    country: str | None,
    state: str | None,
    city: str | None,
    days: int,
    dedup: bool,
    currency: str,
    rates: dict,
    now: dt.datetime,
) -> CompareAreaMetrics:
    conditions = _area_conditions(q, country, state, city, dedup)
    cutoff = now - dt.timedelta(days=days)
    recent_conditions = conditions + [
        func.coalesce(Job.posted_at, Job.first_seen_at) >= cutoff
    ]

    active = db.scalar(select(func.count()).select_from(Job).where(*conditions)) or 0
    new_jobs = db.scalar(select(func.count()).select_from(Job).where(*recent_conditions)) or 0
    companies = (
        db.scalar(
            select(func.count(func.distinct(Job.company_normalized)))
            .select_from(Job)
            .where(*conditions)
        )
        or 0
    )
    remote = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(*conditions, Job.remote_type == "remote")
        )
        or 0
    )
    salary_rows = db.execute(
        select(Job.salary_min, Job.salary_max, Job.salary_currency)
        .where(*conditions, or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)))
        .limit(SAMPLE_LIMIT)
    ).all()
    converted: list[float] = []
    for salary_min, salary_max, source_currency in salary_rows:
        amounts = [value for value in (salary_min, salary_max) if value is not None]
        if not amounts:
            continue
        midpoint = sum(amounts) / len(amounts)
        value = convert(midpoint, source_currency, currency, rates)
        if value is not None:
            converted.append(value)

    sample_rows = db.scalars(select(Job).where(*conditions).limit(SAMPLE_LIMIT)).all()
    skill_counter: Counter = Counter()
    company_counter: Counter = Counter()
    for job in sample_rows:
        for skill in job.skills or []:
            skill_counter[skill] += 1
        if job.company:
            company_counter[job.company] += 1

    day_col = func.date(func.coalesce(Job.posted_at, Job.first_seen_at))
    daily = [
        {"date": str(row[0]), "count": row[1]}
        for row in db.execute(
            select(day_col, func.count())
            .where(*recent_conditions)
            .group_by(day_col)
            .order_by(day_col)
        ).all()
    ]
    sources = [
        {"source": row[0], "count": row[1]}
        for row in db.execute(
            select(Job.source, func.count())
            .where(*conditions)
            .group_by(Job.source)
            .order_by(func.count().desc())
        ).all()
    ]

    salary_sample = len(converted)
    return CompareAreaMetrics(
        label=_label(country, state, city),
        active_jobs=active,
        new_jobs=new_jobs,
        unique_companies=companies,
        remote_ratio=round(remote / active, 3) if active else 0.0,
        salary_coverage=round(len(salary_rows) / active, 3) if active else 0.0,
        salary_median=round(median(converted), 2) if converted else None,
        salary_currency=currency,
        salary_sample=salary_sample,
        top_skills=[{"skill": k, "count": v} for k, v in skill_counter.most_common(TOP_SKILLS)],
        top_companies=[
            {"company": k, "count": v} for k, v in company_counter.most_common(TOP_COMPANIES)
        ],
        daily_counts=daily,
        source_counts=sources,
    )


def _build_summary(a: CompareAreaMetrics, b: CompareAreaMetrics, occupation: str | None) -> str:
    subject = f"“{occupation}”" if occupation else "该职位"
    if not a.active_jobs and not b.active_jobs:
        return f"{a.label} 与 {b.label} 均暂无匹配{subject}的活跃职位。"
    smaller, larger = (a, b) if a.active_jobs <= b.active_jobs else (b, a)
    if larger.active_jobs and smaller.active_jobs:
        ratio = larger.active_jobs / smaller.active_jobs
        sentence = (
            f"{larger.label} 的{subject}活跃职位约为 {smaller.label} 的 {ratio:.1f} 倍"
            f"（{larger.active_jobs} 对 {smaller.active_jobs}）。"
        )
    else:
        sentence = f"{larger.label} 有 {larger.active_jobs} 个{subject}职位，{smaller.label} 暂无。"
    remote_diff = (b.remote_ratio - a.remote_ratio) * 100
    sentence += f" 远程职位占比相差 {abs(remote_diff):.0f} 个百分点（{a.label} {a.remote_ratio*100:.0f}% vs {b.label} {b.remote_ratio*100:.0f}%）。"
    if a.salary_median and b.salary_median and a.salary_currency == b.salary_currency:
        higher = a if a.salary_median >= b.salary_median else b
        lower = b if higher is a else a
        percent = (higher.salary_median - lower.salary_median) / lower.salary_median * 100
        sentence += (
            f"薪资中位数 {higher.label} 比 {lower.label} 高约 {percent:.0f}%"
            f"（{higher.salary_median:,.0f} vs {lower.salary_median:,.0f} {higher.salary_currency}）。"
        )
    return sentence


@router.get("/compare", response_model=CompareResponse)
def compare(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="职业，例如 data analyst"),
    area_a_country: str | None = Query(default=None),
    area_a_state: str | None = Query(default=None),
    area_a_city: str | None = Query(default=None),
    area_b_country: str | None = Query(default=None),
    area_b_state: str | None = Query(default=None),
    area_b_city: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_duplicates: bool = Query(default=False),
) -> CompareResponse:
    settings = get_settings()
    rates = settings.fx_rate_map
    target = (currency or settings.fx_base_currency).upper()
    now = dt.datetime.now(dt.UTC)
    dedup = not include_duplicates

    area_a = _metrics(
        db,
        q=q,
        country=area_a_country,
        state=area_a_state,
        city=area_a_city,
        days=days,
        dedup=dedup,
        currency=target,
        rates=rates,
        now=now,
    )
    area_b = _metrics(
        db,
        q=q,
        country=area_b_country,
        state=area_b_state,
        city=area_b_city,
        days=days,
        dedup=dedup,
        currency=target,
        rates=rates,
        now=now,
    )

    job_ratio = None
    if area_a.active_jobs and area_b.active_jobs:
        job_ratio = round(area_b.active_jobs / area_a.active_jobs, 2)
    salary_diff = None
    if area_a.salary_median and area_b.salary_median and area_a.salary_median:
        salary_diff = round(
            (area_b.salary_median - area_a.salary_median) / area_a.salary_median * 100, 1
        )
    last_updated = db.scalar(select(func.max(Job.last_seen_at)).where(public_job_condition()))

    return CompareResponse(
        occupation=q,
        period_days=days,
        area_a=area_a,
        area_b=area_b,
        comparison=CompareComparison(
            job_count_ratio=job_ratio,
            salary_difference_percent=salary_diff,
            remote_ratio_difference=round(area_b.remote_ratio - area_a.remote_ratio, 3),
        ),
        data_quality=CompareDataQuality(
            deduplicated=dedup, last_updated_at=last_updated
        ),
        summary=_build_summary(area_a, area_b, q),
    )


@router.get("/locations", response_model=list[LocationOut])
def locations(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[LocationOut]:
    statement = (
        select(Job.country, Job.state, Job.city, func.count().label("count"))
        .where(Job.is_active.is_(True), public_job_condition(), Job.city.is_not(None))
    )
    if country:
        statement = statement.where(Job.country == country.upper())
    if q:
        statement = statement.where(
            or_(Job.city.ilike(f"%{q}%"), Job.state.ilike(f"%{q}%"))
        )
    statement = (
        statement.group_by(Job.country, Job.state, Job.city)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [
        LocationOut(country=row[0], state=row[1], city=row[2], count=row[3])
        for row in db.execute(statement).all()
    ]


@router.get("/occupations", response_model=list[OccupationOut])
def occupations(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[OccupationOut]:
    statement = (
        select(Job.occupation_group, func.count().label("count"))
        .where(Job.occupation_group.is_not(None), public_job_condition())
    )
    if q:
        statement = statement.where(Job.occupation_group.ilike(f"%{q}%"))
    statement = (
        statement.group_by(Job.occupation_group).order_by(func.count().desc()).limit(limit)
    )
    return [
        OccupationOut(occupation_group=row[0], count=row[1])
        for row in db.execute(statement).all()
    ]
