"""Saved searches: store a filter set and surface newly seen matching jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.alerts import evaluate_search, generate_unsubscribe_token
from apps.api.database import get_db
from apps.api.models import Job, SavedSearch, SavedSearchMatch
from apps.api.ratelimit import rate_limit
from apps.api.schemas import (
    JobOut,
    SavedSearchIn,
    SavedSearchOut,
    SavedSearchRunResult,
    SavedSearchUpdate,
)
from apps.api.security import require_api_key

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


def _get_or_404(session: Session, search_id: int) -> SavedSearch:
    search = session.get(SavedSearch, search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="saved search not found")
    return search


@router.get("", response_model=list[SavedSearchOut], dependencies=[Depends(require_api_key)])
def list_saved_searches(db: Session = Depends(get_db)) -> list[SavedSearch]:
    return list(db.scalars(select(SavedSearch).order_by(SavedSearch.id.desc())).all())


@router.post(
    "",
    response_model=SavedSearchOut,
    status_code=201,
    dependencies=[Depends(require_api_key)],
)
def create_saved_search(payload: SavedSearchIn, db: Session = Depends(get_db)) -> SavedSearch:
    search = SavedSearch(**payload.model_dump())
    search.unsubscribe_token = generate_unsubscribe_token()
    db.add(search)
    db.commit()
    db.refresh(search)
    return search


@router.get("/unsubscribe")
def unsubscribe(token: str = Query(min_length=8), db: Session = Depends(get_db)) -> dict:
    search = db.scalar(select(SavedSearch).where(SavedSearch.unsubscribe_token == token))
    if search is None:
        raise HTTPException(status_code=404, detail="invalid unsubscribe token")
    search.is_active = False
    db.commit()
    return {"status": "unsubscribed", "saved_search_id": search.id, "name": search.name}


@router.get(
    "/{search_id}", response_model=SavedSearchOut, dependencies=[Depends(require_api_key)]
)
def get_saved_search(search_id: int, db: Session = Depends(get_db)) -> SavedSearch:
    return _get_or_404(db, search_id)


@router.patch(
    "/{search_id}", response_model=SavedSearchOut, dependencies=[Depends(require_api_key)]
)
def update_saved_search(
    search_id: int, payload: SavedSearchUpdate, db: Session = Depends(get_db)
) -> SavedSearch:
    search = _get_or_404(db, search_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(search, field, value)
    db.commit()
    db.refresh(search)
    return search


@router.delete("/{search_id}", status_code=204, dependencies=[Depends(require_api_key)])
def delete_saved_search(search_id: int, db: Session = Depends(get_db)) -> None:
    _get_or_404(db, search_id)
    db.query(SavedSearchMatch).filter(SavedSearchMatch.saved_search_id == search_id).delete()
    db.query(SavedSearch).filter(SavedSearch.id == search_id).delete()
    db.commit()


@router.post(
    "/{search_id}/run",
    response_model=SavedSearchRunResult,
    dependencies=[Depends(require_api_key), Depends(rate_limit("run"))],
)
def run_saved_search(
    search_id: int,
    lookback_hours: int = Query(default=24, ge=0, le=24 * 30),
    db: Session = Depends(get_db),
) -> SavedSearchRunResult:
    search = _get_or_404(db, search_id)
    result = evaluate_search(db, search, lookback_hours=lookback_hours)
    return SavedSearchRunResult(
        saved_search_id=search.id,
        new_matches=result["new_matches"],
        total_matches=result["total_matches"],
        items=[JobOut.model_validate(job) for job in result["items"]],
    )


@router.get(
    "/{search_id}/matches",
    response_model=list[JobOut],
    dependencies=[Depends(require_api_key)],
)
def list_matches(
    search_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    _get_or_404(db, search_id)
    jobs = db.scalars(
        select(Job)
        .join(SavedSearchMatch, SavedSearchMatch.job_id == Job.id)
        .where(SavedSearchMatch.saved_search_id == search_id, Job.visibility == "public")
        .order_by(SavedSearchMatch.matched_at.desc(), SavedSearchMatch.id.desc())
        .limit(limit)
    ).all()
    return [JobOut.model_validate(job) for job in jobs]
