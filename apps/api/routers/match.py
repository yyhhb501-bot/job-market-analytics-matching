"""Résumé matching: keyword + semantic scores, then optional reranking.

Pipeline: deterministic skill/keyword score -> embedding cosine (when available)
-> cross-encoder rerank of the top candidates. Every stage degrades gracefully.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import Job
from apps.api.ratelimit import rate_limit
from apps.api.schemas import JobOut, MatchRequest, MatchResponse, MatchResult
from apps.api.security import require_api_key
from apps.api.source_authorization import public_job_condition
from packages.enrichment import match_resume
from packages.illustrative_jobs import illustrative_jobs
from packages.semantic import (
    LocalHashingEmbedder,
    build_embedder,
    build_reranker,
    cosine,
    embed_text,
)

logger = logging.getLogger("jobagg.match")

router = APIRouter(tags=["match"])

CANDIDATE_LIMIT = 500
SEMANTIC_WEIGHT = 0.5
RERANK_WEIGHT = 0.5
RERANK_TEXT_LIMIT = 2000

# Anonymous demo endpoint caps (stricter than the member endpoint).
DEMO_RESUME_MAX_CHARS = 8000
DEMO_CANDIDATE_LIMIT = 200
DEMO_RESULT_LIMIT = 10


def _rerank_text(job: Job) -> str:
    body = job.summary or job.description or ""
    return f"{job.title or ''}\n{body[:RERANK_TEXT_LIMIT]}"


async def _run_match(
    db: Session,
    payload: MatchRequest,
    candidate_limit: int,
    result_limit: int,
    *,
    illustrative: bool = False,
) -> MatchResponse:
    """Shared scoring pipeline for the member and anonymous-demo endpoints.

    The resume text is never logged or persisted here.
    """
    statement = select(Job).where(
        Job.is_active.is_(True), Job.duplicate_of.is_(None), public_job_condition()
    )
    if payload.country:
        statement = statement.where(Job.country == payload.country.upper())
    if payload.remote_type:
        statement = statement.where(Job.remote_type == payload.remote_type)
    statement = statement.order_by(Job.first_seen_at.desc()).limit(candidate_limit)
    jobs = list(db.scalars(statement).all())
    if illustrative:
        jobs = [
            job
            for job in illustrative_jobs()
            if (not payload.country or job.country == payload.country.upper())
            and (not payload.remote_type or job.remote_type == payload.remote_type)
        ]

    settings = get_settings()

    embedder = LocalHashingEmbedder() if illustrative else build_embedder(settings)
    if illustrative and jobs:
        vectors = await embedder.embed([embed_text(job.title, job.description) for job in jobs])
        for job, vector in zip(jobs, vectors):
            job.embedding = vector
            job.embedding_model = embedder.name
    resume_embedding: list[float] | None = None
    if embedder is not None:
        try:
            resume_embedding = (await embedder.embed([payload.resume]))[0]
        except Exception as exc:  # noqa: BLE001 - fall back to keyword scoring
            logger.warning("resume embedding failed, using keyword scoring: %s", exc)

    engine = "keyword"

    def _compatible(job: Job) -> bool:
        """A job vector participates in cosine scoring only when it was
        produced by the same embedder as the resume vector (and same dim);
        incompatible or missing vectors degrade to keyword scoring per job."""
        return (
            resume_embedding is not None
            and bool(job.embedding)
            and job.embedding_model == (embedder.name if embedder else None)
            and len(job.embedding) == len(resume_embedding)
        )

    if embedder is not None and resume_embedding is not None and any(map(_compatible, jobs)):
        engine = f"semantic+{embedder.name}"

    scored: list[tuple[int, Job, dict, float | None]] = []
    for job in jobs:
        local = match_resume(job, payload.resume)
        semantic_score: float | None = None
        if _compatible(job):
            semantic_score = round(max(0.0, cosine(resume_embedding, job.embedding)) * 100, 1)

        kw_cov = local.get("keyword_coverage_score", float(local["score"]))
        title_wt = local.get("title_weight_score", 0.0)
        rec_sc = local.get("recency_score", 50.0)

        # Ranked by feature hashing cosine similarity, keyword coverage, title weight, and recency
        if semantic_score is not None:
            blended = 0.40 * semantic_score + 0.30 * kw_cov + 0.15 * title_wt + 0.15 * rec_sc
        else:
            blended = 0.55 * kw_cov + 0.25 * title_wt + 0.20 * rec_sc

        score = min(100, max(0, round(blended)))
        scored.append((score, job, local, semantic_score))
    scored.sort(key=lambda item: item[0], reverse=True)

    rerank_scores: dict[int, float] = {}
    reranker = None if illustrative else build_reranker(settings)
    if reranker is not None and scored:
        top = scored[: max(settings.rerank_top_k, 1)]
        documents = [_rerank_text(job) for _, job, _, _ in top]
        try:
            values = await reranker.rerank(payload.resume, documents)
            for (_, job, _, _), value in zip(top, values):
                rerank_scores[job.id] = round(float(value), 4)
        except Exception as exc:  # noqa: BLE001 - keep the blended order
            logger.warning("rerank failed (%s); keeping blended order", exc)

    final: list[tuple[int, Job, dict, float | None, float | None]] = []
    for score, job, local, semantic_score in scored:
        rerank_score = rerank_scores.get(job.id)
        if rerank_score is not None:
            score = round(RERANK_WEIGHT * rerank_score * 100 + (1 - RERANK_WEIGHT) * score)
        final.append((score, job, local, semantic_score, rerank_score))
    final.sort(key=lambda item: item[0], reverse=True)

    results = [
        MatchResult(
            job=JobOut.model_validate(job),
            score=score,
            matched_skills=local["matched_skills"],
            missing_skills=local["missing_skills"],
            shared_keywords=local["shared_keywords"],
            semantic_score=semantic_score,
            rerank_score=rerank_score,
            keyword_coverage_score=local.get("keyword_coverage_score"),
            title_weight_score=local.get("title_weight_score"),
            recency_score=local.get("recency_score"),
        )
        for score, job, local, semantic_score, rerank_score in final[:result_limit]
    ]
    return MatchResponse(
        engine=engine,
        reranked=bool(rerank_scores),
        results=results,
        data_scope="illustrative_examples" if illustrative else "public_jobs",
    )


@router.post(
    "/match",
    response_model=MatchResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit("match"))],
)
async def match_jobs(payload: MatchRequest, db: Session = Depends(get_db)) -> MatchResponse:
    return await _run_match(db, payload, CANDIDATE_LIMIT, payload.limit)


@router.post(
    "/demo/match",
    response_model=MatchResponse,
    dependencies=[Depends(rate_limit("demo_match"))],
)
async def demo_match_jobs(payload: MatchRequest, db: Session = Depends(get_db)) -> MatchResponse:
    """Anonymous, capacity-limited demonstration of the matching pipeline.

    No account, phone number, or API key is required. The demo is stricter
    than the member endpoint: shorter resume cap, fewer candidates considered,
    at most DEMO_RESULT_LIMIT results, and a dedicated per-IP rate limit.
    Submitted text is neither stored nor logged.
    """
    if len(payload.resume) > DEMO_RESUME_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"演示模式简历文本最长 {DEMO_RESUME_MAX_CHARS} 字符",
        )
    return await _run_match(
        db, payload, DEMO_CANDIDATE_LIMIT, min(payload.limit, DEMO_RESULT_LIMIT)
    )


@router.post(
    "/demo/examples/match",
    response_model=MatchResponse,
    dependencies=[Depends(rate_limit("demo_match"))],
)
async def match_illustrative_examples(
    payload: MatchRequest, db: Session = Depends(get_db)
) -> MatchResponse:
    """Explicitly selected fictional examples; no private job is used or stored."""
    if len(payload.resume) > DEMO_RESUME_MAX_CHARS:
        raise HTTPException(
            status_code=422, detail=f"演示模式简历文本最长 {DEMO_RESUME_MAX_CHARS} 字符"
        )
    return await _run_match(
        db, payload, DEMO_CANDIDATE_LIMIT, min(payload.limit, DEMO_RESULT_LIMIT), illustrative=True
    )
