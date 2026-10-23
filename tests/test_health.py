"""Health endpoint contract: liveness vs readiness.

``/livez`` never fails on a broken database. ``/readyz`` and ``/health`` must
return 503 (so orchestrators stop routing traffic) without echoing database
exception details to unauthenticated callers.
"""

from __future__ import annotations

from apps.api.database import get_db


class _BrokenSession:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("psycopg: connection refused to 10.0.0.5:5432 (secret host)")


def test_livez_ignores_database(client):
    assert client.get("/livez").status_code == 200


def test_readyz_ok(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_alias_ok(client):
    assert client.get("/health").status_code == 200


def test_readyz_fails_closed_when_database_down(client):
    client.app.dependency_overrides[get_db] = lambda: iter([_BrokenSession()])
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    # The raw exception (which can contain hostnames/credentials) must not leak.
    assert "psycopg" not in response.text
    assert "10.0.0.5" not in response.text


def test_health_alias_fails_closed_when_database_down(client):
    client.app.dependency_overrides[get_db] = lambda: iter([_BrokenSession()])
    assert client.get("/health").status_code == 503


def test_livez_ok_when_database_down(client):
    client.app.dependency_overrides[get_db] = lambda: iter([_BrokenSession()])
    assert client.get("/livez").status_code == 200
