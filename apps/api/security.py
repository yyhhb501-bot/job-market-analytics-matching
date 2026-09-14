"""Authentication for write endpoints.

``require_api_key`` guards administrative endpoints. ``require_device_token``
guards the local-collector import API: each device carries its own high-entropy
bearer token (only its SHA-256 hash is stored) that can be revoked without
touching the operator API key.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import CollectorDevice, utcnow

DEVICE_TOKEN_PREFIX = "jagg_"


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


def generate_device_token() -> str:
    """Return a fresh, high-entropy device token (shown to the user once)."""
    return DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    """Hash a device token for storage/lookup (tokens are not user-chosen)."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def require_device_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> CollectorDevice:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    device = (
        db.scalar(select(CollectorDevice).where(CollectorDevice.token_hash == hash_device_token(token)))
        if token
        else None
    )
    if device is None or device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    device.last_seen_at = utcnow()
    db.commit()
    return device


__all__ = [
    "DEVICE_TOKEN_PREFIX",
    "generate_device_token",
    "hash_device_token",
    "require_api_key",
    "require_device_token",
]
