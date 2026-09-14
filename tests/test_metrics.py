from __future__ import annotations

from apps.api.metrics import record_import, record_run
from apps.api.ratelimit import RedisFixedWindowLimiter, SlidingWindowLimiter


def test_metrics_endpoint_exposes_prometheus_format(client):
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "http_requests_total" in body
    assert "collector_runs_total" in body
    assert "job_freshness_seconds" in body


def test_record_run_and_import_emit_samples(client):
    record_run("unit-test", "success", {"seen": 3, "inserted": 2, "duplicates": 1, "errors": 0})
    record_import(accepted=2, duplicate=1, rejected=0)
    body = client.get("/metrics").text
    assert 'collector_runs_total{source="unit-test",status="success"}' in body
    assert 'collector_jobs_total{action="inserted",source="unit-test"} 2.0' in body
    assert 'import_batch_jobs_total{result="accepted"}' in body


def test_sliding_window_limiter_blocks_after_limit():
    limiter = SlidingWindowLimiter(limit=2)
    assert limiter.allow("client")
    assert limiter.allow("client")
    assert not limiter.allow("client")
    assert limiter.allow("other-client")


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True


class BrokenRedis:
    def incr(self, key: str) -> int:
        raise RuntimeError("redis down")


def test_redis_limiter_counts_and_sets_expiry():
    fake = FakeRedis()
    limiter = RedisFixedWindowLimiter(fake, limit=2, prefix="ratelimit:test")
    assert limiter.allow("203.0.113.1")
    assert limiter.allow("203.0.113.1")
    assert not limiter.allow("203.0.113.1")
    assert limiter.allow("203.0.113.2")
    assert all(seconds == 61 for seconds in fake.expires.values())


def test_redis_limiter_fails_open_when_backend_down():
    limiter = RedisFixedWindowLimiter(BrokenRedis(), limit=1)
    assert limiter.allow("client")
    assert limiter.allow("client")
