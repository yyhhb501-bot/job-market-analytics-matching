"""Liveness / readiness endpoints.

``/livez`` reports whether the process is up and never touches external
dependencies, so orchestrators only restart genuinely stuck instances.
``/readyz`` (and the backward-compatible ``/health`` alias) report whether the
service can serve traffic: a failing database returns 503 without leaking
exception details to unauthenticated callers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.database import get_db

router = APIRouter(tags=["health"])


@router.get("/livez")
def livez() -> dict[str, str]:
    return {"status": "ok"}


def _readiness(db: Session) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - depends on live DB
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "error"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> JSONResponse:
    return _readiness(db)


@router.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    return _readiness(db)
