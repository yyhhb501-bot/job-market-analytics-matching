from __future__ import annotations

from apps.worker.pipeline import persist_job
from packages.fx import convert, parse_rates
from packages.job_schema import NormalizedJob


def aud_job() -> NormalizedJob:
    return NormalizedJob(
        source="seek",
        source_job_id="fx-1",
        title="Data Engineer",
        company="Acme",
        description="Python pipelines",
        city="Sydney",
        country="AU",
        salary_min=100000,
        salary_max=120000,
        salary_currency="AUD",
        salary_period="year",
    )


def test_parse_rates_defaults_and_override():
    assert parse_rates(None)["USD"] == 1.0
    rates = parse_rates('{"AUD": 0.5}')
    assert rates["AUD"] == 0.5
    assert rates["USD"] == 1.0
    assert parse_rates("not json")["USD"] == 1.0


def test_convert_roundtrip():
    rates = {"USD": 1.0, "AUD": 0.66}
    assert convert(100000, "AUD", "USD", rates) == 66000
    assert round(convert(66000, "USD", "AUD", rates)) == 100000
    assert convert(100, "USD", "JPY", rates) is None


def test_fx_endpoint(client):
    body = client.get("/api/v1/fx").json()
    assert body["base"] == "USD"
    assert "AUD" in body["rates"]


def test_search_currency_conversion(client, session):
    persist_job(session, aud_job())
    session.commit()

    body = client.get("/api/v1/jobs", params={"currency": "USD"}).json()
    item = body["items"][0]
    assert item["salary_display_currency"] == "USD"
    assert item["salary_display_min"] == 66000
    assert item["salary_display_max"] == 79200


def test_search_without_currency_has_no_display_fields(client, session):
    persist_job(session, aud_job())
    session.commit()
    item = client.get("/api/v1/jobs").json()["items"][0]
    assert item["salary_display_currency"] is None
