"""Prometheus scrape endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.metrics import update_runtime_gauges

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def metrics(db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    try:
        update_runtime_gauges(db, redis_url=settings.redis_url)
    except Exception:  # noqa: BLE001 - always return the static metrics
        pass
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["router"]
