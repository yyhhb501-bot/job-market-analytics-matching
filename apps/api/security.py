"""API key authentication for write endpoints.

When ``API_KEY`` is unset the dependency is a no-op (local development only).
Set it for any deployment reachable beyond localhost.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from apps.api.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings = get_settings()
    if not settings.api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


__all__ = ["require_api_key"]
