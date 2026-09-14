"""Optional OpenSearch backend with a PostgreSQL fallback.

The API talks to this module only when ``SEARCH_BACKEND=opensearch`` and an
``OPENSEARCH_URL`` is set; any error falls back to the existing PostgreSQL
query path. Documents are derived from the ``jobs`` table and (re)indexed by
the worker's ``reindex`` command / Celery task.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("jobagg.search")

INDEX_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "source": {"type": "keyword"},
            "country": {"type": "keyword"},
            "state": {"type": "keyword"},
            "city": {"type": "keyword"},
            "company_normalized": {"type": "keyword"},
            "remote_type": {"type": "keyword"},
            "employment_type": {"type": "keyword"},
            "skills": {"type": "keyword"},
            "salary_min": {"type": "double"},
            "salary_max": {"type": "double"},
            "salary_top": {"type": "double"},
            "posted_at": {"type": "date"},
            "first_seen_at": {"type": "date"},
            "is_active": {"type": "boolean"},
            "is_duplicate": {"type": "boolean"},
            "visibility": {"type": "keyword"},
            "title": {"type": "text"},
            "company": {"type": "text"},
            "description": {"type": "text"},
        }
    }
}

_SORT_FIELDS = {
    "posted_at": "posted_at",
    "first_seen_at": "first_seen_at",
    "last_seen_at": "first_seen_at",
    "salary_max": "salary_max",
    "id": "id",
}


@dataclass
class SearchHits:
    ids: list[int]
    total: int


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def job_to_document(job: Any) -> dict[str, Any]:
    salary_top = job.salary_max if job.salary_max is not None else job.salary_min
    return {
        "id": job.id,
        "source": job.source,
        "title": job.title,
        "company": job.company,
        "company_normalized": job.company_normalized,
        "description": job.description,
        "country": job.country,
        "state": job.state,
        "city": job.city,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_top": salary_top,
        "posted_at": _iso(job.posted_at),
        "first_seen_at": _iso(job.first_seen_at),
        "is_active": bool(job.is_active),
        "is_duplicate": job.duplicate_of is not None,
        "visibility": getattr(job, "visibility", None) or "public",
        "skills": job.skills or [],
    }


def build_bool_query(
    *,
    q: str | None = None,
    sources: list[str] | None = None,
    countries: list[str] | None = None,
    states: list[str] | None = None,
    cities: list[str] | None = None,
    companies: list[str] | None = None,
    remote_types: list[str] | None = None,
    employment_types: list[str] | None = None,
    min_salary: float | None = None,
    posted_after: datetime | None = None,
    include_duplicates: bool = False,
) -> dict[str, Any]:
    filters: list[dict] = [
        {"term": {"is_active": True}},
        {"term": {"visibility": "public"}},
    ]
    if not include_duplicates:
        filters.append({"term": {"is_duplicate": False}})

    term_fields = (
        ("source", sources),
        ("country", countries),
        ("state", states),
        ("city", cities),
        ("company_normalized", companies),
        ("remote_type", remote_types),
        ("employment_type", employment_types),
    )
    for field_name, values in term_fields:
        cleaned = [str(value) for value in (values or []) if value]
        if cleaned:
            filters.append({"terms": {field_name: cleaned}})

    if min_salary is not None:
        filters.append({"range": {"salary_top": {"gte": min_salary}}})
    if posted_after is not None:
        filters.append({"range": {"posted_at": {"gte": _iso(posted_after)}}})

    must: list[dict] = []
    if q and q.strip():
        must.append(
            {
                "multi_match": {
                    "query": q.strip(),
                    "fields": ["title^3", "company^2", "skills^2", "description"],
                }
            }
        )
    return {"bool": {"must": must, "filter": filters}}


def build_search_body(
    *,
    q: str | None,
    sort: str,
    order: str,
    page: int,
    page_size: int,
    include_duplicates: bool,
    **filters: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": build_bool_query(q=q, include_duplicates=include_duplicates, **filters),
        "from": max(page - 1, 0) * page_size,
        "size": page_size,
    }
    if sort == "relevance" and q and q.strip():
        body["sort"] = ["_score", {"posted_at": "desc"}]
    else:
        field = _SORT_FIELDS.get(sort, "posted_at")
        body["sort"] = [{field: {"order": order}}]
    return body


def parse_search_response(data: dict[str, Any]) -> SearchHits:
    hits_block = data.get("hits") or {}
    total_block = hits_block.get("total") or {}
    total = total_block.get("value", 0) if isinstance(total_block, dict) else int(total_block or 0)
    ids: list[int] = []
    for hit in hits_block.get("hits", []):
        try:
            ids.append(int(hit["_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return SearchHits(ids=ids, total=int(total))


class OpenSearchBackend:
    def __init__(
        self,
        url: str,
        index: str = "jobs",
        username: str | None = None,
        password: str | None = None,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.index = index
        auth = (username, password) if username else None
        self._client = client or httpx.Client(
            base_url=url.rstrip("/"), auth=auth, timeout=timeout
        )

    def ensure_index(self) -> None:
        response = self._client.head(f"/{self.index}")
        if response.status_code == 404:
            self._client.put(f"/{self.index}", json=INDEX_MAPPING).raise_for_status()

    def index_jobs(self, documents: list[dict[str, Any]]) -> None:
        if not documents:
            return
        lines: list[str] = []
        for document in documents:
            lines.append(json.dumps({"index": {"_index": self.index, "_id": document["id"]}}))
            lines.append(json.dumps(document, default=str))
        body = "\n".join(lines) + "\n"
        response = self._client.post(
            "/_bulk",
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
        )
        response.raise_for_status()

    def search(
        self,
        *,
        q: str | None = None,
        sort: str = "posted_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 25,
        include_duplicates: bool = False,
        **filters: Any,
    ) -> SearchHits:
        body = build_search_body(
            q=q,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
            include_duplicates=include_duplicates,
            **filters,
        )
        response = self._client.post(f"/{self.index}/_search", json=body)
        response.raise_for_status()
        return parse_search_response(response.json())

    def close(self) -> None:
        self._client.close()


def build_search_backend(settings: Any) -> OpenSearchBackend | None:
    """Return a backend only when explicitly enabled and configured."""
    if str(getattr(settings, "search_backend", "postgres")).lower() != "opensearch":
        return None
    url = getattr(settings, "opensearch_url", None)
    if not url:
        logger.warning("SEARCH_BACKEND=opensearch but OPENSEARCH_URL is not set")
        return None
    return OpenSearchBackend(
        url,
        index=getattr(settings, "opensearch_index", "jobs"),
        username=getattr(settings, "opensearch_username", None),
        password=getattr(settings, "opensearch_password", None),
        timeout=float(getattr(settings, "opensearch_timeout_seconds", 10.0)),
    )


__all__ = [
    "INDEX_MAPPING",
    "OpenSearchBackend",
    "SearchHits",
    "build_bool_query",
    "build_search_backend",
    "build_search_body",
    "job_to_document",
    "parse_search_response",
]
