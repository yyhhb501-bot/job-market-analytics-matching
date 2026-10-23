from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Self

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import Board, SourceAuthorization


def require_authorization_admin(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = get_settings().api_key
    if (
        not expected
        or not expected.strip()
        or not x_api_key
        or not secrets.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


class AuthorizationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str = Field(min_length=1, max_length=50)
    source_board_id: int | None = Field(default=None, gt=0)
    evidence_ref: str = Field(min_length=1, max_length=4000)
    approved: bool = False
    commercial_display: bool = False
    valid_from: datetime
    valid_until: datetime | None = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("validity timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        return self


class AuthorizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_board_id: int | None
    evidence_ref: str
    approved: bool
    commercial_display: bool
    valid_from: datetime
    valid_until: datetime | None
    created_at: datetime
    updated_at: datetime


router = APIRouter(
    prefix="/admin/source-authorizations",
    tags=["source-authorizations"],
    dependencies=[Depends(require_authorization_admin)],
)


def _get_or_404(db: Session, authorization_id: int) -> SourceAuthorization:
    row = db.get(SourceAuthorization, authorization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="source authorization not found")
    return row


def _validate_board(db: Session, payload: AuthorizationIn) -> None:
    if payload.source_board_id is None:
        return
    board = db.get(Board, payload.source_board_id)
    if board is None or board.provider != payload.source:
        raise HTTPException(status_code=422, detail="board must exist and match source")


@router.get("", response_model=list[AuthorizationOut])
def list_authorizations(
    db: Session = Depends(get_db),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[SourceAuthorization]:
    statement = select(SourceAuthorization)
    if source is not None:
        statement = statement.where(SourceAuthorization.source == source)
    return list(
        db.scalars(statement.order_by(SourceAuthorization.id.desc()).offset(offset).limit(limit))
    )


@router.post("", response_model=AuthorizationOut, status_code=201)
def create_authorization(
    payload: AuthorizationIn, db: Session = Depends(get_db)
) -> SourceAuthorization:
    _validate_board(db, payload)
    row = SourceAuthorization(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{authorization_id}", response_model=AuthorizationOut)
def get_authorization(authorization_id: int, db: Session = Depends(get_db)) -> SourceAuthorization:
    return _get_or_404(db, authorization_id)


@router.put("/{authorization_id}", response_model=AuthorizationOut)
def update_authorization(
    authorization_id: int, payload: AuthorizationIn, db: Session = Depends(get_db)
) -> SourceAuthorization:
    row = _get_or_404(db, authorization_id)
    _validate_board(db, payload)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{authorization_id}", status_code=204)
def delete_authorization(authorization_id: int, db: Session = Depends(get_db)) -> None:
    db.delete(_get_or_404(db, authorization_id))
    db.commit()
