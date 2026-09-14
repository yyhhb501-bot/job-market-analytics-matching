from __future__ import annotations

from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def seed(session) -> None:
    persist_job(
        session,
        NormalizedJob(
            source="seek",
            source_job_id="m1",
            title="Data Analyst",
            company="Acme AU",
            description="SQL and Python reporting",
            city="Melbourne",
            state="VIC",
            country="AU",
            remote_type="remote",
            salary_min=90000,
            salary_max=110000,
            salary_currency="AUD",
            salary_period="year",
        ),
    )
    persist_job(
        session,
        NormalizedJob(
            source="seek",
            source_job_id="m2",
            title="Data Analyst",
            company="Globex AU",
            description="SQL dashboards",
            city="Melbourne",
            state="VIC",
            country="AU",
            salary_min=80000,
            salary_max=100000,
            salary_currency="AUD",
            salary_period="year",
        ),
    )
    persist_job(
        session,
        NormalizedJob(
            source="indeed",
            source_job_id="s1",
            title="Data Analyst",
            company="Initech US",
            description="Tableau and SQL",
            city="San Francisco",
            state="CA",
            country="US",
            salary_min=120000,
            salary_max=150000,
            salary_currency="USD",
            salary_period="year",
        ),
    )
    session.commit()


def test_compare_two_areas(client, session):
    seed(session)
    response = client.get(
        "/api/v1/compare",
        params={
            "q": "data analyst",
            "area_a_country": "AU",
            "area_a_city": "Melbourne",
            "area_b_country": "US",
            "area_b_city": "San Francisco",
            "currency": "USD",
            "days": 30,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["area_a"]["active_jobs"] == 2
    assert body["area_b"]["active_jobs"] == 1
    assert body["area_a"]["remote_ratio"] == 0.5
    assert body["area_a"]["unique_companies"] == 2
    assert body["area_a"]["salary_median"] is not None
    assert body["area_a"]["top_skills"]
    assert body["comparison"]["remote_ratio_difference"] == -0.5
    assert body["data_quality"]["deduplicated"] is True
    assert body["summary"]


def test_compare_empty_area(client, session):
    seed(session)
    body = client.get(
        "/api/v1/compare",
        params={"q": "data analyst", "area_a_country": "AU", "area_b_country": "US"},
    ).json()
    assert body["area_a"]["active_jobs"] == 2
    assert body["area_b"]["active_jobs"] == 1


def test_locations_and_occupations(client, session):
    seed(session)
    locations = client.get("/api/v1/locations", params={"q": "melb"}).json()
    assert any(row["city"] == "Melbourne" for row in locations)

    occupations = client.get("/api/v1/occupations").json()
    assert any(row["occupation_group"] == "data-analyst" for row in occupations)
