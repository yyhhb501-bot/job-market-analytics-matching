from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.config import Settings
from apps.api.ratelimit import rate_limit
from apps.api.security import require_api_key


def test_require_api_key_fails_closed_when_unset(monkeypatch):
    monkeypatch.setattr("apps.api.security.get_settings", lambda: Settings(api_key=None))
    with pytest.raises(HTTPException) as exc:
        require_api_key(None)
    assert exc.value.status_code == 503


def test_require_api_key_enforced(monkeypatch):
    monkeypatch.setattr(
        "apps.api.security.get_settings", lambda: Settings(api_key="secret")
    )
    with pytest.raises(HTTPException) as exc:
        require_api_key("wrong")
    assert exc.value.status_code == 401
    require_api_key("secret")


def test_write_endpoint_requires_key(client, monkeypatch):
    monkeypatch.setattr(
        "apps.api.security.get_settings", lambda: Settings(api_key="secret")
    )
    assert client.post("/api/v1/saved-searches", json={"name": "x"}).status_code == 401
    ok = client.post(
        "/api/v1/saved-searches",
        json={"name": "x"},
        headers={"X-API-Key": "secret"},
    )
    assert ok.status_code == 201


def test_saved_search_reads_require_key(client, monkeypatch):
    monkeypatch.setattr(
        "apps.api.security.get_settings", lambda: Settings(api_key="secret")
    )
    assert client.get("/api/v1/saved-searches").status_code == 401
    ok = client.get("/api/v1/saved-searches", headers={"X-API-Key": "secret"})
    assert ok.status_code == 200


def test_rate_limit_dependency(monkeypatch):
    monkeypatch.setattr(
        "apps.api.ratelimit.get_settings",
        lambda: Settings(
            rate_limit_enabled=True, rate_limit_per_minute=2, match_rate_limit_per_minute=2
        ),
    )
    dependency = rate_limit("unit-test-scope")
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"))
    dependency(request)
    dependency(request)
    with pytest.raises(HTTPException) as exc:
        dependency(request)
    assert exc.value.status_code == 429
