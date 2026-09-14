"""Rate limiting with a Redis backend and an in-process fallback.

``RATE_LIMIT_BACKEND`` selects the implementation:

* ``memory`` — per-process sliding window (single instance only)
* ``redis``  — shared fixed-window counter across API replicas
* ``auto``   — Redis when reachable, otherwise memory (default)

Redis failures fail *open* (requests allowed) so an outage cannot take the API
down; the fallback is logged.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Protocol

from fastapi import HTTPException, Request, status

from apps.api.config import Settings, get_settings

logger = logging.getLogger("jobagg.ratelimit")


class Limiter(Protocol):
    limit: int

    def allow(self, key: str) -> bool: ...


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


class RedisFixedWindowLimiter:
    """Shared counter: ``INCR`` a per-minute bucket key and check the limit."""

    def __init__(self, client, limit: int, window: float = 60.0, prefix: str = "ratelimit") -> None:
        self.client = client
        self.limit = limit
        self.window = window
        self.prefix = prefix

    def allow(self, key: str) -> bool:
        bucket = int(time.time() // self.window)
        redis_key = f"{self.prefix}:{key}:{bucket}"
        try:
            count = int(self.client.incr(redis_key))
            if count == 1:
                self.client.expire(redis_key, int(self.window) + 1)
            return count <= self.limit
        except Exception as exc:  # noqa: BLE001 - fail open, never block the API
            logger.warning("redis rate limiter unavailable, allowing request: %s", exc)
            return True


_limiters: dict[tuple, Limiter] = {}
_registry_lock = threading.Lock()
_redis_clients: dict[str, object | None] = {}


def _redis_client(url: str):
    if url in _redis_clients:
        return _redis_clients[url]
    client = None
    try:
        import redis

        candidate = redis.Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0)
        candidate.ping()
        client = candidate
    except Exception as exc:  # noqa: BLE001 - fall back to memory
        logger.warning("redis rate limiter unavailable (%s); using in-memory limiter", exc)
    _redis_clients[url] = client
    return client


def _build_limiter(scope: str, limit: int, settings: Settings) -> Limiter:
    backend = (settings.rate_limit_backend or "memory").lower()
    if backend in ("redis", "auto"):
        client = _redis_client(settings.redis_url)
        if client is not None:
            return RedisFixedWindowLimiter(client, limit, prefix=f"ratelimit:{scope}")
    return SlidingWindowLimiter(limit)


def _get_limiter(scope: str, limit: int, settings: Settings) -> Limiter:
    backend = (settings.rate_limit_backend or "memory").lower()
    key = (scope, backend, limit, settings.redis_url)
    with _registry_lock:
        limiter = _limiters.get(key)
        if limiter is None:
            limiter = _build_limiter(scope, limit, settings)
            _limiters[key] = limiter
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
        if not _get_limiter(scope, limit, settings).allow(client):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )

    return dependency


__all__ = [
    "Limiter",
    "RedisFixedWindowLimiter",
    "SlidingWindowLimiter",
    "rate_limit",
]
