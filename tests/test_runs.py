from __future__ import annotations

from apps.api.models import CollectorRun


def test_runs_list_and_summary(client, session):
    session.add_all(
        [
            CollectorRun(source="seek", status="success", jobs_seen=10, jobs_inserted=5),
            CollectorRun(
                source="seek", status="error", jobs_seen=0, jobs_inserted=0, error="boom"
            ),
            CollectorRun(source="greenhouse", status="success", jobs_seen=3, jobs_inserted=2),
        ]
    )
    session.commit()

    runs = client.get("/api/v1/runs").json()
    assert len(runs) == 3
    assert {"source", "status", "jobs_seen", "jobs_inserted", "error"} <= set(runs[0])

    summary = client.get("/api/v1/runs/summary").json()
    assert summary["total_runs"] == 3
    by_source = {row["source"]: row for row in summary["sources"]}
    assert by_source["seek"]["runs"] == 2
    assert by_source["seek"]["errors"] == 1
    assert by_source["greenhouse"]["successes"] == 1
    assert by_source["greenhouse"]["last_status"] == "success"


def test_source_health_flags_drift(client, session):
    session.add_all(
        [
            CollectorRun(source="seek", status="success", jobs_seen=10),
            CollectorRun(source="seek", status="success", jobs_seen=0),
            CollectorRun(source="seek", status="success", jobs_seen=0),
            CollectorRun(source="seek", status="success", jobs_seen=0),
        ]
    )
    session.commit()

    health = client.get("/api/v1/health/sources").json()
    row = next(item for item in health if item["source"] == "seek")
    assert row["runs"] == 4
    assert row["successes"] == 4
    assert row["consecutive_zero_runs"] == 3
    assert row["last_job_count"] == 0
    assert row["schema_drift"] is True


def test_runs_filter_by_source(client, session):
    session.add(CollectorRun(source="seek", status="success"))
    session.commit()
    assert len(client.get("/api/v1/runs", params={"source": "seek"}).json()) == 1
    assert client.get("/api/v1/runs", params={"source": "nope"}).json() == []
