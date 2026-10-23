"""Résumé matching: keyword + semantic scores, then optional reranking.

Pipeline: deterministic skill/keyword score -> embedding cosine (when available)
-> cross-encoder rerank of the top candidates. Every stage degrades gracefully.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import get_settings
from apps.api.database import get_db
from apps.api.models import Job
from apps.api.ratelimit import rate_limit
from apps.api.schemas import JobOut, MatchRequest, MatchResponse, MatchResult
from apps.api.security import require_api_key
from packages.enrichment import match_resume
from packages.semantic import build_embedder, build_reranker, cosine

logger = logging.getLogger("jobagg.match")

router = APIRouter(tags=["match"])

CANDIDATE_LIMIT = 500
SEMANTIC_WEIGHT = 0.5
RERANK_WEIGHT = 0.5
RERANK_TEXT_LIMIT = 2000


def _rerank_text(job: Job) -> str:
    body = job.summary or job.description or ""
    return f"{job.title or ''}\n{body[:RERANK_TEXT_LIMIT]}"


@router.post(
    "/match",
    response_model=MatchResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit("match"))],
)
async def match_jobs(payload: MatchRequest, db: Session = Depends(get_db)) -> MatchResponse:
    statement = select(Job).where(
        Job.is_active.is_(True), Job.duplicate_of.is_(None), Job.visibility == "public"
    )
    if payload.country:
        statement = statement.where(Job.country == payload.country.upper())
    if payload.remote_type:
        statement = statement.where(Job.remote_type == payload.remote_type)
    statement = statement.order_by(Job.first_seen_at.desc()).limit(CANDIDATE_LIMIT)
    jobs = list(db.scalars(statement).all())

    settings = get_settings()

    embedder = build_embedder(settings)
    resume_embedding: list[float] | None = None
    if embedder is not None:
        try:
            resume_embedding = (await embedder.embed([payload.resume]))[0]
        except Exception as exc:  # noqa: BLE001 - fall back to keyword scoring
            logger.warning("resume embedding failed, using keyword scoring: %s", exc)

    engine = "keyword"
    if resume_embedding is not None and any(job.embedding for job in jobs):
        engine = f"semantic+{embedder.name}" if embedder else "semantic"

    scored: list[tuple[int, Job, dict, float | None]] = []
    for job in jobs:
        local = match_resume(job, payload.resume)
        semantic_score: float | None = None
        if resume_embedding is not None and job.embedding:
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
    reranker = build_reranker(settings)
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
            score = round(
                RERANK_WEIGHT * rerank_score * 100 + (1 - RERANK_WEIGHT) * score
            )
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
        for score, job, local, semantic_score, rerank_score in final[: payload.limit]
    ]
    return MatchResponse(engine=engine, reranked=bool(rerank_scores), results=results)
