from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.api.config import Settings
from packages.search import (
    OpenSearchBackend,
    build_bool_query,
    build_search_backend,
    build_search_body,
    job_to_document,
    parse_search_response,
)


def fake_job(**overrides) -> SimpleNamespace:
    data = {
        "id": 1,
        "source": "seek",
        "title": "Data Engineer",
        "company": "Acme",
        "company_normalized": "acme",
        "description": "Python pipelines",
        "country": "AU",
        "state": "NSW",
        "city": "Sydney",
        "remote_type": "remote",
        "employment_type": "full_time",
        "salary_min": 100000.0,
        "salary_max": 120000.0,
        "posted_at": datetime(2026, 1, 1, tzinfo=UTC),
        "first_seen_at": datetime(2026, 1, 2, tzinfo=UTC),
        "is_active": True,
        "duplicate_of": None,
        "skills": ["Python"],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_job_to_document():
    document = job_to_document(fake_job())
    assert document["id"] == 1
    assert document["salary_top"] == 120000.0
    assert document["is_duplicate"] is False
    assert document["posted_at"].startswith("2026-01-01")
    assert document["skills"] == ["Python"]


def test_job_to_document_falls_back_to_salary_min():
    document = job_to_document(fake_job(salary_max=None))
    assert document["salary_top"] == 100000.0


def test_build_bool_query_includes_filters():
    query = build_bool_query(
        q="data", sources=["seek"], countries=["AU"], min_salary=100000, include_duplicates=False
    )
    bool_query = query["bool"]
    assert bool_query["filter"][0] == {"term": {"is_active": True}}
    assert {"term": {"is_duplicate": False}} in bool_query["filter"]
    assert {"terms": {"source": ["seek"]}} in bool_query["filter"]
    assert {"terms": {"country": ["AU"]}} in bool_query["filter"]
    assert {"range": {"salary_top": {"gte": 100000}}} in bool_query["filter"]
    assert bool_query["must"][0]["multi_match"]["query"] == "data"


def test_build_bool_query_without_q_has_no_must():
    assert build_bool_query()["bool"]["must"] == []
    assert {"term": {"is_duplicate": False}} in build_bool_query()["bool"]["filter"]
    assert build_bool_query(include_duplicates=True)["bool"]["filter"][0] == {
        "term": {"is_active": True}
    }


def test_build_search_body_sorting_and_paging():
    body = build_search_body(
        q="x", sort="relevance", order="desc", page=2, page_size=25, include_duplicates=False
    )
    assert body["from"] == 25
    assert body["size"] == 25
    assert body["sort"][0] == "_score"

    body2 = build_search_body(
        q=None, sort="posted_at", order="asc", page=1, page_size=10, include_duplicates=True
    )
    assert body2["sort"] == [{"posted_at": {"order": "asc"}}]


def test_parse_search_response():
    hits = parse_search_response(
        {"hits": {"total": {"value": 3}, "hits": [{"_id": "5"}, {"_id": "2"}]}}
    )
    assert hits.ids == [5, 2]
    assert hits.total == 3


def test_build_search_backend_selection():
    assert build_search_backend(Settings(search_backend="postgres")) is None
    assert (
        build_search_backend(Settings(search_backend="opensearch", opensearch_url=None)) is None
    )
    backend = build_search_backend(
        Settings(search_backend="opensearch", opensearch_url="http://x:9200")
    )
    assert isinstance(backend, OpenSearchBackend)


class FakeResponse:
    def __init__(self, status_code: int = 200, data=None) -> None:
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, search_data=None, head_status: int = 200) -> None:
        self.search_data = search_data
        self.head_status = head_status
        self.calls: list[tuple] = []

    def head(self, url):
        self.calls.append(("head", url))
        return FakeResponse(self.head_status)

    def put(self, url, **kwargs):
        self.calls.append(("put", url))
        return FakeResponse(200)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if url.endswith("/_search"):
            return FakeResponse(200, self.search_data)
        return FakeResponse(200, {"errors": False})

    def close(self):
        pass


def test_backend_ensure_index_creates_when_missing():
    client = FakeClient(head_status=404)
    OpenSearchBackend("http://x", client=client).ensure_index()
    assert any(call[0] == "put" for call in client.calls)


def test_backend_search_parses_hits():
    data = {"hits": {"total": {"value": 1}, "hits": [{"_id": "7"}]}}
    backend = OpenSearchBackend("http://x", client=FakeClient(search_data=data))
    hits = backend.search(q="data", page=1, page_size=10)
    assert hits.ids == [7]
    assert hits.total == 1


def test_backend_index_jobs_writes_bulk_body():
    client = FakeClient()
    OpenSearchBackend("http://x", client=client).index_jobs([job_to_document(fake_job())])
    post_calls = [call for call in client.calls if call[0] == "post"]
    assert post_calls and post_calls[0][1] == "/_bulk"
