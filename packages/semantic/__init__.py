"""Pluggable text embeddings for semantic job matching.

Providers:
- ``local``: dependency-free deterministic hashing embeddings (offline default).
- ``openai``: any OpenAI-compatible ``/embeddings`` endpoint via HTTPX.

Job embeddings are computed during enrichment and stored on the row; the
``/match`` endpoint only needs to embed the résumé and compute cosine similarity.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

DEFAULT_DIM = 256
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]+")


def embed_text(title: str | None, description: str | None, limit: int = 4000) -> str:
    body = (description or "")[:limit]
    return f"{title or ''}\n{body}".strip()


class Embedder(Protocol):
    name: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class LocalHashingEmbedder:
    """Deterministic bag-of-words hashing embedding (no external calls)."""

    name = "local"

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self.dim = max(32, int(dim))

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str | None) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN_RE.findall((text or "").lower()):
            if len(token) < 3:
                continue
            digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            index = digest % self.dim
            sign = 1.0 if (digest >> 8) & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class OpenAIEmbedder:
    """OpenAI-compatible embeddings endpoint."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": list(texts)}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json().get("data") or []
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]


def build_embedder(settings: Any) -> Embedder | None:
    """Choose an embedder from settings, or ``None`` when disabled."""
    if not getattr(settings, "enable_semantic_match", True):
        return None
    provider = str(getattr(settings, "llm_provider", "local") or "local").lower()
    if provider == "none":
        return None
    api_key = getattr(settings, "llm_api_key", None)
    if provider in {"openai", "auto"} and api_key:
        return OpenAIEmbedder(
            api_key,
            model=getattr(settings, "llm_model", DEFAULT_MODEL),
            base_url=getattr(settings, "llm_base_url", DEFAULT_BASE_URL),
            timeout=float(getattr(settings, "llm_timeout_seconds", 30.0)),
        )
    if provider == "openai":
        return None
    return LocalHashingEmbedder(getattr(settings, "llm_embedding_dim", DEFAULT_DIM))


def _token_set(text: str | None) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").lower()) if len(token) >= 3}


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]: ...


class LocalCrossEncoder:
    """Offline pairwise scorer based on weighted token overlap (0..1)."""

    name = "local"

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        query_tokens = _token_set(query)
        scores: list[float] = []
        for document in documents:
            document_tokens = _token_set(document)
            if not query_tokens or not document_tokens:
                scores.append(0.0)
                continue
            overlap = len(query_tokens & document_tokens)
            raw = overlap / ((len(query_tokens) ** 0.5) * (len(document_tokens) ** 0.5))
            scores.append(round(min(raw, 1.0), 4))
        return scores


class HttpReranker:
    """Cohere/Jina-style ``/rerank`` endpoint."""

    name = "http"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "top_n": len(documents),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rerank",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
        scores = [0.0] * len(documents)
        for item in results:
            index = item.get("index")
            value = item.get("relevance_score", item.get("score", 0.0))
            if isinstance(index, int) and 0 <= index < len(scores):
                scores[index] = float(value)
        return scores


def build_reranker(settings: Any) -> Reranker | None:
    if not getattr(settings, "enable_rerank", True):
        return None
    provider = str(getattr(settings, "rerank_provider", "local") or "local").lower()
    if provider == "none":
        return None
    api_key = getattr(settings, "rerank_api_key", None)
    if provider in {"http", "auto"} and api_key:
        return HttpReranker(
            api_key,
            model=getattr(settings, "rerank_model", "rerank-english-v3.0"),
            base_url=getattr(settings, "rerank_base_url", "https://api.jina.ai/v1"),
            timeout=float(getattr(settings, "llm_timeout_seconds", 30.0)),
        )
    if provider == "http":
        return None
    return LocalCrossEncoder()


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_DIM",
    "DEFAULT_MODEL",
    "Embedder",
    "HttpReranker",
    "LocalCrossEncoder",
    "LocalHashingEmbedder",
    "OpenAIEmbedder",
    "Reranker",
    "build_embedder",
    "build_reranker",
    "cosine",
    "embed_text",
]
