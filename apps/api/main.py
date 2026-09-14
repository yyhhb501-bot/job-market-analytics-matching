"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import check_production_settings, get_settings
from apps.api.metrics import record_http
from apps.api.routers import (
    boards,
    compare,
    export,
    health,
    import_jobs,
    jobs,
    match,
    metrics,
    runs,
    saved_searches,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobagg.api")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = check_production_settings(settings)
    if problems:
        raise RuntimeError(
            "Refusing to start with unsafe production settings:\n- " + "\n- ".join(problems)
        )
    if settings.auto_create_tables:
        try:
            from apps.api.database import create_all

            create_all()
        except Exception as exc:  # pragma: no cover - depends on live DB
            logger.warning("auto_create_tables skipped: %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="US + Australia job aggregation search API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(export.router, prefix="/api/v1")  # before jobs so /jobs/export wins
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(saved_searches.router, prefix="/api/v1")
app.include_router(match.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(compare.router, prefix="/api/v1")
app.include_router(boards.router, prefix="/api/v1")
if settings.enable_import_gateway:
    app.include_router(import_jobs.router, prefix="/api/v1")
if settings.enable_metrics:
    app.include_router(metrics.router)


@app.middleware("http")
async def _metrics_middleware(request, call_next):
    if not settings.enable_metrics or request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or "unmatched"
        record_http(request.method, route_path, status_code, time.perf_counter() - start)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}
