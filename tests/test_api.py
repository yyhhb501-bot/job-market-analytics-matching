from __future__ import annotations

from sqlalchemy import select

from apps.api.models import Job, SourceAuthorization, utcnow
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def seed(session) -> None:
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
            description="SQL dashboards for the Sydney team",
            city="Sydney",
            state="NSW",
            country="AU",
        ),
    )
    session.add_all(
        SourceAuthorization(
            source=source,
            evidence_ref=f"test-license:api:{source}",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
        for source in ("indeed", "seek")
    )
    session.commit()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_search_returns_all_jobs(client, session):
    seed(session)
    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2


def test_search_filters_by_country_and_text(client, session):
    seed(session)
    response = client.get("/api/v1/jobs", params={"country": "AU"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["city"] == "Sydney"

    response = client.get("/api/v1/jobs", params={"q": "spark"})
    assert response.json()["total"] == 1


def test_stats(client, session):
    seed(session)
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_jobs"] == 2
    assert {row["source"] for row in body["by_source"]} == {"indeed", "seek"}


def test_relevance_sort_falls_back_on_sqlite(client, session):
    seed(session)
    response = client.get("/api/v1/jobs", params={"q": "spark", "sort": "relevance"})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_invalid_sort_is_rejected(client):
    assert client.get("/api/v1/jobs", params={"sort": "bogus"}).status_code == 422


def test_opensearch_backend_is_used_when_configured(client, session, monkeypatch):
    seed(session)
    from packages.search import SearchHits

    ids = list(session.scalars(select(Job.id).order_by(Job.id.desc())).all())
    calls = []

    class FakeBackend:
        def search(self, **kwargs):
            calls.append(kwargs)
            return SearchHits(ids=ids, total=len(ids))

    monkeypatch.setattr(
        "apps.api.routers.jobs.build_search_backend", lambda settings: FakeBackend()
    )
    body = client.get("/api/v1/jobs", params={"sort": "id", "order": "asc"}).json()
    assert len(calls) == 1
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == ids


def test_opensearch_failure_falls_back_to_postgres(client, session, monkeypatch):
    seed(session)

    class BoomBackend:
        def search(self, **kwargs):
            raise RuntimeError("opensearch down")

    monkeypatch.setattr(
        "apps.api.routers.jobs.build_search_backend", lambda settings: BoomBackend()
    )
    body = client.get("/api/v1/jobs").json()
    assert body["total"] == 2


def test_match_endpoint(client, session):
    seed(session)
    response = client.post("/api/v1/match", json={"resume": "Python Spark data pipelines"})
    assert response.status_code == 200
    body = response.json()
    results = body["results"]
    assert results
    assert results[0]["score"] > 0
    assert results[0]["job"]["title"] == "Senior Data Engineer"
    assert body["reranked"] is True
    assert 0.0 <= results[0]["rerank_score"] <= 1.0


def test_get_job_by_id_and_404(client, session):
    seed(session)
    job_id = client.get("/api/v1/jobs").json()["items"][0]["id"]
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200
    assert client.get("/api/v1/jobs/999999").status_code == 404
