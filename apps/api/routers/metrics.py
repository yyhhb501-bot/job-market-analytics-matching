"""Prometheus scrape endpoint."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.metrics import update_runtime_gauges

router = APIRouter(tags=["metrics"])


def require_metrics_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Reject scrapers when ``METRICS_TOKEN`` is configured.

    Unauthenticated access stays available when the token is unset so existing
    deployments keep working; production setups can point Prometheus at
    ``Authorization: Bearer <METRICS_TOKEN>``.
    """
    expected = get_settings().metrics_token
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing metrics token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid metrics token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(require_metrics_token)])
def metrics(db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    try:
        update_runtime_gauges(db, redis_url=settings.redis_url)
    except Exception:  # noqa: BLE001 - always return the static metrics
        pass
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["router"]
