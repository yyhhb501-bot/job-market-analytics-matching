from __future__ import annotations


def seed(session):
    from apps.worker.pipeline import persist_job
    from packages.job_schema import NormalizedJob

    persist_job(
        session,
        NormalizedJob(
            source="indeed",
            source_job_id="1",
            title="Senior Data Engineer",
            company="Acme",
            description="Python and Spark pipelines",
            city="Austin",
            state="TX",
            country="US",
        ),
    )
    persist_job(
        session,
        NormalizedJob(
            source="seek",
            source_job_id="2",
            title="Data Analyst",
            company="Oz Corp",
            description="SQL dashboards",
            city="Sydney",
            state="NSW",
            country="AU",
        ),
    )
    session.commit()


def test_export_csv(client, session):
    seed(session)
    response = client.get("/api/v1/jobs/export", params={"format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "Senior Data Engineer" in response.text
    assert "source_job_id" in response.text
    assert "attachment" in response.headers.get("content-disposition", "")


def test_export_json(client, session):
    seed(session)
    response = client.get("/api/v1/jobs/export", params={"format": "json"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {"id", "title", "company", "source"} <= set(data[0])


def test_export_xlsx(client, session):
    seed(session)
    response = client.get("/api/v1/jobs/export", params={"format": "xlsx"})
    assert response.status_code == 200
    assert response.content[:2] == b"PK"  # xlsx is a zip archive


def test_export_respects_filters(client, session):
    seed(session)
    response = client.get("/api/v1/jobs/export", params={"format": "json", "country": "AU"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["country"] == "AU"
