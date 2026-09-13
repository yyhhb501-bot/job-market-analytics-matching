"""Dependency factory factory for simple in-process rate limiting.

Per-process sliding window keyed by client IP. Sufficient for a single API
instance; switch to a Redis-backed limiter when running multiple replicas.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from apps.api.config import get_settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


_limiters: dict[str, SlidingWindowLimiter] = {}
_registry_lock = threading.Lock()


def _get_limiter(scope: str, limit: int) -> SlidingWindowLimiter:
    with _registry_lock:
        limiter = _limiters.get(scope)
        if limiter is None or limiter.limit != limit:
            limiter = SlidingWindowLimiter(limit)
            _limiters[scope] = limiter
        return limiter


def rate_limit(scope: str):
    """Return a FastAPI dependency enforcing the per-minute limit for ``scope``."""

    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = (
            settings.match_rate_limit_per_minute
            if scope == "match"
            else settings.rate_limit_per_minute
        )
        client = request.client.host if request.client else "anonymous"
        if not _get_limiter(scope, limit).allow(client):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )

    return dependency


__all__ = ["SlidingWindowLimiter", "rate_limit"]
