from __future__ import annotations

import asyncio

from apps.api.config import Settings
from packages.semantic import HttpReranker, LocalCrossEncoder, build_reranker


def test_local_cross_encoder_ranks_relevant_first():
    scores = asyncio.run(
        LocalCrossEncoder().rerank(
            "python aws pipelines", ["python aws data pipelines", "marketing sales funnel"]
        )
    )
    assert scores[0] > scores[1]
    assert 0.0 <= scores[0] <= 1.0


def test_local_cross_encoder_handles_empty():
    assert asyncio.run(LocalCrossEncoder().rerank("", ["anything"])) == [0.0]


def test_build_reranker_selection():
    assert isinstance(
        build_reranker(Settings(enable_rerank=True, rerank_provider="local")),
        LocalCrossEncoder,
    )
    assert build_reranker(Settings(enable_rerank=False)) is None
    assert build_reranker(Settings(enable_rerank=True, rerank_provider="none")) is None
    assert build_reranker(Settings(enable_rerank=True, rerank_provider="http")) is None
    assert isinstance(
        build_reranker(
            Settings(enable_rerank=True, rerank_provider="http", rerank_api_key="key")
        ),
        HttpReranker,
    )
