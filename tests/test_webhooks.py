from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.config import Settings
from apps.api.url_safety import UnsafeUrlError, validate_webhook_url
from apps.api.webhooks import (
    build_payload,
    build_slack_payload,
    build_teams_payload,
    build_webhook_payload,
    normalize_webhook_url,
    send_webhook,
    sign_payload,
)


def make_job(job_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        source="seek",
        title="Data Engineer",
        company="Acme",
        city="Sydney",
        state="NSW",
        country="AU",
        remote_type=None,
        employment_type=None,
    )


def test_normalize_webhook_url():
    assert normalize_webhook_url(None) is None
    assert normalize_webhook_url("  ") is None
    assert normalize_webhook_url("https://hooks.example.com/jobs") == "https://hooks.example.com/jobs"
    with pytest.raises(ValueError):
        normalize_webhook_url("ftp://hooks.example.com")
    with pytest.raises(ValueError):
        normalize_webhook_url("not-a-url")


def test_build_payload_limits_jobs():
    settings = Settings(web_base_url="http://localhost:3000", webhook_max_jobs=1)
    search = SimpleNamespace(id=5, name="AU data")
    payload = build_payload(settings, search, [make_job(1), make_job(2)])
    assert payload["event"] == "saved_search.matches"
    assert payload["new_matches"] == 2
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["url"] == "http://localhost:3000/jobs/1"


def test_slack_and_teams_payloads():
    settings = Settings(web_base_url="http://localhost:3000", webhook_max_jobs=5)
    search = SimpleNamespace(id=1, name="AU data", webhook_kind="slack")
    jobs = [make_job(1)]

    slack = build_slack_payload(settings, search, jobs)
    assert "text" in slack
    assert "http://localhost:3000/jobs/1" in slack["text"]

    teams = build_teams_payload(settings, search, jobs)
    assert teams["@type"] == "MessageCard"
    assert "http://localhost:3000/jobs/1" in teams["text"]


def test_build_webhook_payload_dispatch():
    settings = Settings(web_base_url="http://localhost:3000")
    jobs = [make_job(1)]
    search = SimpleNamespace(id=1, name="X", webhook_kind="slack")
    assert "text" in build_webhook_payload(settings, search, jobs)

    search.webhook_kind = "teams"
    assert build_webhook_payload(settings, search, jobs)["@type"] == "MessageCard"

    search.webhook_kind = "generic"
    assert build_webhook_payload(settings, search, jobs)["event"] == "saved_search.matches"


def test_beat_schedule_has_daily_digest_and_sweep():
    from apps.worker.celery_app import celery_app

    assert "daily-digest" in celery_app.conf.beat_schedule
    assert "daily-sweep" in celery_app.conf.beat_schedule


def test_validate_webhook_url_blocks_private_and_metadata():
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url(
            "http://internal.example.com", resolver=lambda host: {"127.0.0.1"}
        )
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url(
            "http://metadata.example.com", resolver=lambda host: {"169.254.169.254"}
        )
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url(
            "http://docker.example.com", resolver=lambda host: {"10.1.2.3"}
        )


def test_validate_webhook_url_allows_public_and_private_escape_hatch():
    public = validate_webhook_url(
        "https://example.com/hook", resolver=lambda host: {"93.184.216.34"}
    )
    assert public == "https://example.com/hook"

    internal = validate_webhook_url(
        "http://10.0.0.5/hook",
        allow_private=True,
        resolver=lambda host: {"10.0.0.5"},
    )
    assert internal == "http://10.0.0.5/hook"


def test_validate_webhook_url_allowlist():
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url(
            "https://evil.example.com/hook",
            allowed_hosts=["hooks.slack.com"],
            resolver=lambda host: {"93.184.216.34"},
        )


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.status_code)


def test_send_webhook_success_and_failure():
    client = FakeClient(200)
    assert (
        send_webhook("https://hooks.example.com/x", {"a": 1}, client=client, validate=False)
        is True
    )
    assert client.calls[0][0] == "https://hooks.example.com/x"

    bad = FakeClient(500)
    assert (
        send_webhook("https://hooks.example.com/x", {}, client=bad, validate=False) is False
    )


def test_send_webhook_blocks_private_target():
    client = FakeClient()
    ok = send_webhook(
        "http://internal.example.com",
        {},
        settings=Settings(webhook_allow_private=False),
        client=client,
        resolver=lambda host: {"10.0.0.1"},
    )
    assert ok is False
    assert client.calls == []


def test_send_webhook_signs_payload():
    client = FakeClient(200)
    settings = Settings(webhook_signing_secret="topsecret", webhook_allow_private=True)
    assert send_webhook(
        "http://internal.example.com/x",
        {"a": 1},
        settings=settings,
        client=client,
        resolver=lambda host: {"10.0.0.1"},
    )
    headers = client.calls[0][1]["headers"]
    assert headers["X-JobAgg-Signature"].startswith("sha256=")
    assert headers["X-JobAgg-Signature"] == sign_payload("topsecret", client.calls[0][1]["content"])
