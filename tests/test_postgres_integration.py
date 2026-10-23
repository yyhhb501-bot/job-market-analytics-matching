from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

TEST_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_POSTGRES_URL not set")


def test_postgres_full_text_search_and_upsert():
    from apps.api.database import Base, ensure_full_text_index
    from apps.api.filters import build_conditions
    from apps.api.models import Job, SourceAuthorization, utcnow
    from apps.worker.pipeline import persist_job
    from packages.job_schema import NormalizedJob

    engine = create_engine(TEST_URL)
    Base.metadata.create_all(engine)
    ensure_full_text_index(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        job = NormalizedJob(
            source="pgtest",
            source_job_id="1",
            title="Senior Python Engineer",
            company="Acme",
            description="Build Python data pipelines with Spark and Airflow",
            city="Austin",
            country="US",
        )
        assert persist_job(session, job, run_id=1) == "inserted"
        session.add(
            SourceAuthorization(
                source="pgtest",
                evidence_ref="test-license:postgres:pgtest",
                approved=True,
                commercial_display=True,
                valid_from=utcnow(),
            )
        )
        session.commit()

        conditions = build_conditions(q="python pipelines", dialect_name="postgresql")
        rows = session.scalars(select(Job).where(*conditions)).all()
        assert any(row.source == "pgtest" for row in rows)

        # Re-seeing the same source id updates in place (layer-1 dedup).
        assert persist_job(session, job, run_id=2) == "updated"
        session.commit()
        count = session.scalar(
            select(func.count()).select_from(Job).where(Job.source == "pgtest")
        )
        assert count == 1
    finally:
        session.query(Job).filter(Job.source == "pgtest").delete()
        session.query(SourceAuthorization).filter(
            SourceAuthorization.evidence_ref == "test-license:postgres:pgtest"
        ).delete()
        session.commit()
        session.close()
        engine.dispose()
