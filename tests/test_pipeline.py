from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.models import Job
from apps.worker import pipeline
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob


def make_job(**overrides) -> NormalizedJob:
    data = {
        "source": "indeed",
        "source_job_id": "abc-1",
        "title": "Senior Data Engineer",
        "company": "Acme, Inc.",
        "description": "Build pipelines with Python and Spark.",
        "city": "Austin",
        "country": "US",
        "apply_url": "https://example.com/jobs/42",
    }
    data.update(overrides)
    return NormalizedJob(**data)


def test_layer1_exact_source_id_updates_in_place(session):
    assert persist_job(session, make_job()) == "inserted"
    assert persist_job(session, make_job(description="Updated description")) == "updated"
    session.commit()
    assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_layer2_same_apply_url_is_duplicate(session):
    first = make_job(source="greenhouse", source_job_id="g-1", title="Backend Engineer")
    second = make_job(source="indeed", source_job_id="i-1", title="Backend Developer")
    assert persist_job(session, first) == "inserted"
    assert persist_job(session, second) == "duplicate"
    session.commit()
    rows = session.scalars(select(Job).order_by(Job.id)).all()
    assert len(rows) == 2
    assert rows[1].duplicate_of == rows[0].id


def test_layer3_cross_platform_description_match_is_duplicate(session):
    first = make_job(source="linkedin", source_job_id="l-1", apply_url="https://linkedin.com/jobs/1")
    second = make_job(source="seek", source_job_id="s-1", apply_url="https://seek.com.au/job/9")
    assert persist_job(session, first) == "inserted"
    assert persist_job(session, second) == "duplicate"
    session.commit()
    rows = session.scalars(select(Job).order_by(Job.id)).all()
    assert rows[1].duplicate_of == rows[0].id


def test_persist_job_safe_retries_on_integrity_error(session, monkeypatch):
    calls = {"n": 0}

    def fake_persist(session, job, run_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("stmt", {}, Exception("duplicate"))
        return "inserted"

    monkeypatch.setattr(pipeline, "persist_job", fake_persist)
    assert pipeline.persist_job_safe(session, make_job()) == "inserted"
    assert calls["n"] == 2


def test_models_have_integrity_constraints():
    index_names = {index.name for index in Job.__table__.indexes}
    assert "uq_jobs_dedup_key_active" in index_names
    assert any(fk.column.table.name == "jobs" for fk in Job.__table__.c.duplicate_of.foreign_keys)


def test_persist_job_enriches_skills_and_summary(session):
    persist_job(session, make_job(description="Python and AWS data pipelines."))
    session.commit()
    job = session.scalars(select(Job)).one()
    assert "Python" in (job.skills or [])
    assert job.summary


def test_different_jobs_both_inserted(session):
    persist_job(session, make_job())
    persist_job(
        session,
        make_job(
            source_job_id="abc-2",
            title="Marketing Manager",
            description="Own the growth funnel.",
            apply_url="https://example.com/jobs/99",
        ),
    )
    session.commit()
    assert session.scalar(select(func.count()).select_from(Job)) == 2
