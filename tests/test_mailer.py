from __future__ import annotations

from types import SimpleNamespace

from apps.api.config import Settings
from apps.api.mailer import is_email_configured, render_alert, send_saved_search_alert


def make_job(**overrides) -> SimpleNamespace:
    data = {
        "id": 1,
        "title": "Data Engineer",
        "company": "Acme",
        "source": "seek",
        "city": "Sydney",
        "state": "NSW",
        "country": "AU",
        "salary_min": 120000.0,
        "salary_max": 140000.0,
        "salary_currency": "AUD",
        "salary_period": "year",
        "apply_url": "https://www.seek.com.au/job/1",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def configured_settings(**overrides) -> Settings:
    base = {
        "enable_email_alerts": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 2525,
        "alert_from_email": "jobs@example.com",
        "web_base_url": "http://localhost:3000",
    }
    base.update(overrides)
    return Settings(**base)


def test_is_email_configured():
    assert not is_email_configured(
        Settings(enable_email_alerts=True, smtp_host=None, alert_from_email=None)
    )
    assert is_email_configured(configured_settings())


def test_render_alert_contains_jobs_and_links():
    settings = configured_settings()
    message = render_alert(settings, "AU data", "me@example.com", [make_job()])
    assert "1 job(s)" in message.subject
    assert "Data Engineer" in message.text
    assert "http://localhost:3000/jobs/1" in message.text
    assert "AUD 120,000 - 140,000 / year" in message.text
    assert "Data Engineer" in message.html


def test_send_saved_search_alert_uses_smtp():
    settings = configured_settings(smtp_use_tls=False)
    captured: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, username, password):
            captured["login"] = (username, password)

        def send_message(self, message):
            captured["message"] = message

    sent = send_saved_search_alert(
        settings, "AU data", "me@example.com", [make_job()], smtp_factory=FakeSMTP
    )
    assert sent is True
    assert captured["host"] == "smtp.example.com"
    assert captured["port"] == 2525
    message = captured["message"]
    assert message["To"] == "me@example.com"
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Data Engineer" in body


def test_send_skipped_when_not_configured():
    opened: list[int] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            opened.append(1)

    sent = send_saved_search_alert(
        Settings(enable_email_alerts=False),
        "AU data",
        "me@example.com",
        [make_job()],
        smtp_factory=FakeSMTP,
    )
    assert sent is False
    assert opened == []
