"""Thin HTTP client for ``POST /api/v1/import/jobs``.

The platform is the single writer: the collector only ever uploads JSON, and
the server applies normalisation, dedup and enrichment.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx

MAX_BATCH = 500


class UploadError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"import upload failed ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


def chunked(items: list[Any], size: int = MAX_BATCH) -> Iterator[list[Any]]:
    step = max(1, min(size, MAX_BATCH))
    for start in range(0, len(items), step):
        yield items[start : start + step]


class ImportClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        source: str = "linkedin_user_import",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ValueError("a device token is required (set JOBAGG_DEVICE_TOKEN)")
        self.base_url = base_url.rstrip("/")
        self.source = source
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def observe(self, observations: list[dict]) -> dict:
        response = self._client.post('/api/v1/import/observations', json={'observations': observations})
        if response.status_code >= 400:
            raise UploadError(response.status_code, response.text[:500])
        return response.json()

    def __enter__(self) -> ImportClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upload(
        self,
        jobs: list[dict],
        *,
        query: str | None = None,
        geo_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"source": self.source, "jobs": jobs}
        if query:
            payload["query"] = query
        if geo_id:
            payload["geo_id"] = geo_id
        headers = {"Idempotency-Key": idempotency_key or uuid.uuid4().hex}
        response = self._client.post("/api/v1/import/jobs", json=payload, headers=headers)
        if response.status_code >= 400:
            raise UploadError(response.status_code, response.text[:500])
        return response.json()


__all__ = ["MAX_BATCH", "ImportClient", "UploadError", "chunked"]
