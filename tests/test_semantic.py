from __future__ import annotations

import asyncio
import math

from sqlalchemy import select

from apps.api.config import Settings
from apps.api.models import Job, SourceAuthorization, utcnow
from apps.worker.pipeline import persist_job
from packages.job_schema import NormalizedJob
from packages.semantic import (
    LocalHashingEmbedder,
    build_embedder,
    cosine,
    embed_text,
)


def test_cosine_similarity():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([], []) == 0.0
    assert cosine([1.0], [1.0, 2.0]) == 0.0


def test_local_embedder_is_deterministic_and_normalized():
    embedder = LocalHashingEmbedder()
    first = asyncio.run(embedder.embed(["python aws docker"]))[0]
    second = asyncio.run(embedder.embed(["python aws docker"]))[0]
    assert first == second
    assert abs(math.sqrt(sum(value * value for value in first)) - 1.0) < 1e-6


def test_related_text_scores_higher_than_unrelated():
    embedder = LocalHashingEmbedder()
    job, resume, other = asyncio.run(
        embedder.embed(
            [
                "Python AWS data pipelines",
                "I build Python AWS pipelines",
                "Marketing sales funnel growth",
            ]
        )
    )
    assert cosine(job, resume) > cosine(job, other)


def test_build_embedder_selection():
    assert isinstance(
        build_embedder(Settings(enable_semantic_match=True, llm_provider="local")),
        LocalHashingEmbedder,
    )
    assert build_embedder(Settings(enable_semantic_match=False)) is None
    assert build_embedder(Settings(enable_semantic_match=True, llm_provider="none")) is None
    assert build_embedder(Settings(enable_semantic_match=True, llm_provider="openai")) is None


def test_embed_text_combines_title_and_description():
    assert embed_text("Data Engineer", "Python") == "Data Engineer\nPython"


def test_match_uses_semantic_when_embeddings_present(client, session):
    persist_job(
        session,
        NormalizedJob(
            source="test",
            source_job_id="sem-1",
            title="Python Engineer",
            company="Acme",
            description="Python AWS Docker data pipelines",
            city="Austin",
            country="US",
        ),
    )
    session.add(
        SourceAuthorization(
            source="test",
            evidence_ref="test-license:semantic:test",
            approved=True,
            commercial_display=True,
            valid_from=utcnow(),
        )
    )
    session.commit()

    job = session.scalars(select(Job)).one()
    job.embedding = asyncio.run(
        LocalHashingEmbedder().embed([embed_text(job.title, job.description)])
    )[0]
    session.commit()

    body = client.post("/api/v1/match", json={"resume": "Python AWS pipelines"}).json()
    assert body["engine"].startswith("semantic")
    assert body["results"][0]["semantic_score"] is not None
    assert body["results"][0]["score"] > 0
