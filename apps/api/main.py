"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import get_settings
from apps.api.routers import export, health, jobs, match, runs, saved_searches

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jobagg.api")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment.lower() == "production" and "*" in settings.cors_origin_list:
        raise RuntimeError(
            "CORS_ORIGINS=* is not allowed in production; set explicit origins"
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


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}
