"""Integration tests against a real Redis (opt-in via ``TEST_REDIS_URL``).

The unit tests use fakes; these prove the actual Redis behaviour: shared
counters across limiter instances, TTL expiry, and fail-open on outage.
"""

from __future__ import annotations

import time

from tests.conftest import TEST_REDIS_URL, requires_redis

pytestmark = [requires_redis]


def test_shared_counter_across_limiter_instances(real_redis):
    """Two limiter objects pointing at the same Redis share one budget."""
    from apps.api.ratelimit import RedisFixedWindowLimiter

    first = RedisFixedWindowLimiter(real_redis, limit=2, window=60, prefix="t-shared")
    second = RedisFixedWindowLimiter(real_redis, limit=2, window=60, prefix="t-shared")

    assert first.allow("client-a")
    assert second.allow("client-a")  # same key, different instance
    assert not first.allow("client-a")


def test_window_expiry_allows_again(real_redis):
    from apps.api.ratelimit import RedisFixedWindowLimiter

    limiter = RedisFixedWindowLimiter(real_redis, limit=1, window=1, prefix="t-expiry")
    assert limiter.allow("client-b")
    assert not limiter.allow("client-b")

    time.sleep(1.2)  # window rolls over; the counter key expires
    assert limiter.allow("client-b")


def test_fail_open_when_redis_unreachable():
    """A dead Redis must never block requests (fail open)."""
    import redis

    dead = redis.Redis.from_url(
        "redis://127.0.0.1:1/0",  # nothing listens on port 1
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    from apps.api.ratelimit import RedisFixedWindowLimiter

    limiter = RedisFixedWindowLimiter(dead, limit=1, window=60, prefix="t-dead")
    assert limiter.allow("client-c")


def test_queue_depth_gauge_reads_real_redis(real_redis, session):
    from apps.api import metrics as metrics_module
    from apps.api.metrics import QUEUE_DEPTH

    real_redis.rpush("celery", "task-1", "task-2", "task-3")
    try:
        metrics_module.update_runtime_gauges(db=session, redis_url=TEST_REDIS_URL)
        assert QUEUE_DEPTH.labels("celery")._value.get() == 3
    finally:
        real_redis.delete("celery")


def test_rate_limit_endpoint_via_real_redis(pg_client, real_redis, settings_env):
    """The API dependency uses Redis when RATE_LIMIT_BACKEND=redis."""
    with settings_env(RATE_LIMIT_BACKEND="redis", REDIS_URL=TEST_REDIS_URL):
        response = pg_client.get("/api/v1/jobs")
        assert response.status_code == 200
