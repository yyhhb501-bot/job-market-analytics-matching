from __future__ import annotations

import json

import httpx
import pytest

from clients.linkedin_local_agent.config import config_from_dict
from clients.linkedin_local_agent.filters.location import LocationFilter, detect_country
from clients.linkedin_local_agent.filters.occupation import TitleFilter
from clients.linkedin_local_agent.models import JobStub
from clients.linkedin_local_agent.parsing.job_detail import (
    parse_detail,
    parse_iso_datetime,
)
from clients.linkedin_local_agent.parsing.search_result import parse_search_results
from clients.linkedin_local_agent.search.geo_ids import validate_geo_id
from clients.linkedin_local_agent.search.pagination import (
    is_last_page,
    iter_start_offsets,
    page_key,
)
from clients.linkedin_local_agent.search.query_builder import (
    Query,
    build_queries,
    build_search_url,
)
from clients.linkedin_local_agent.storage.checkpoint import Checkpoint
from clients.linkedin_local_agent.storage.seen_jobs import (
    STATE_DUPLICATE,
    STATE_FILTERED_LOCATION,
    STATE_UPLOADED,
    SeenStore,
)
from clients.linkedin_local_agent.uploader.api_client import (
    ImportClient,
    UploadError,
    chunked,
)


def _config_dict() -> dict:
    return {
        "api_base_url": "http://localhost:8010/",
        "occupation_groups": {
            "data-analyst": {
                "primary": ["Data Analyst", "BI Analyst"],
                "secondary": ["Insights Analyst"],
                "exclusions": ["Financial Analyst"],
            }
        },
        "locations": {
            "centers": [
                {"country": "AU", "state": "VIC", "city": "Melbourne", "geo_id": "123"}
            ],
            "countries": [{"country": "AU", "geo_id": "101452733"}],
        },
        "search": {"max_queries": 10, "results_per_page": 25, "max_pages_per_query": 2},
    }


# --- config -----------------------------------------------------------------


def test_config_from_dict_parses_groups_and_locations():
    config = config_from_dict(_config_dict())
    assert config.api_base_url == "http://localhost:8010"
    assert config.occupation_groups[0].name == "data-analyst"
    assert config.centers[0].city == "Melbourne"
    assert config.countries[0].country == "AU"
    assert config.search.results_per_page == 25


# --- query builder ----------------------------------------------------------


def test_build_queries_makes_city_and_remote_channels():
    config = config_from_dict(_config_dict())
    queries = build_queries(config)
    channels = {query.channel for query in queries}
    assert channels == {"local", "remote"}
    # 3 keywords: 3 local + 3 remote
    assert len(queries) == 6


def test_search_url_pins_geoid_and_workplace_filter():
    search = config_from_dict(_config_dict()).search
    remote = build_search_url(
        Query(keyword="Data Analyst", geo_id="103644278", channel="remote", country="US"),
        25,
        search,
    )
    assert "geoId=103644278" in remote
    assert "f_WT=2" in remote
    assert "start=25" in remote

    local = build_search_url(
        Query(
            keyword="Data Analyst",
            geo_id="123",
            channel="local",
            country="AU",
            city="Melbourne",
        ),
        0,
        search,
    )
    assert "distance=25" in local
    assert "f_WT" not in local


# --- pagination / geo -------------------------------------------------------


def test_pagination_offsets_and_last_page():
    assert list(iter_start_offsets(25, 3)) == [0, 25, 50]
    assert is_last_page(10, 25) is True
    assert is_last_page(25, 25) is False

    key = page_key(
        Query(keyword="x", geo_id="1", channel="local", country="AU", occupation_group="g"),
        25,
    )
    assert key == "local|g|x|1|25"


def test_validate_geo_id():
    assert validate_geo_id("103644278")
    assert not validate_geo_id("REPLACE_WITH_X")
    assert not validate_geo_id("")


# --- filters ----------------------------------------------------------------


def test_title_filter_excludes_offtopic_titles():
    title_filter = TitleFilter(["Financial Analyst", "Laboratory Analyst"])
    assert title_filter.excluded("Senior Financial Analyst")
    assert not title_filter.excluded("Data Analyst")


def test_location_filter_rejects_remote_and_wrong_city():
    melbourne = LocationFilter(country="AU", state="VIC", city="Melbourne", channel="local")
    assert melbourne.accepts(JobStub(job_id="1", title="t", location="Melbourne, Victoria, Australia"))
    assert not melbourne.accepts(JobStub(job_id="2", title="t", location="Sydney, NSW, Australia"))
    assert not melbourne.accepts(JobStub(job_id="3", title="t", location="Melbourne (Remote)"))

    remote = LocationFilter(country="AU", channel="remote")
    assert remote.accepts(JobStub(job_id="4", title="t", location="Australia (Remote)"))


def test_detect_country():
    assert detect_country("melbourne victoria australia") == "AU"
    assert detect_country("austin texas united states") == "US"
    assert detect_country("somewhere unknown") is None


# --- parsing ----------------------------------------------------------------


def test_parse_search_results_extracts_cards():
    page = """
    <ul>
      <li><div class="base-card" data-entity-urn="urn:li:jobPosting:4123456789">
        <a class="base-card__full-link" href="https://au.linkedin.com/jobs/view/x-4123456789">
          <h3 class="base-search-card__title">Data Analyst</h3>
          <h4 class="base-search-card__subtitle"><a>Acme Pty Ltd</a></h4>
          <span class="job-search-card__location">Melbourne, Victoria, Australia</span>
        </a>
      </div></li>
    </ul>
    """
    stubs = parse_search_results(page)
    assert len(stubs) == 1
    stub = stubs[0]
    assert stub.job_id == "4123456789"
    assert stub.title == "Data Analyst"
    assert stub.company == "Acme Pty Ltd"
    assert stub.location == "Melbourne, Victoria, Australia"


def test_parse_search_results_deduplicates_and_ignores_empty():
    page = """
    <div data-entity-urn="urn:li:jobPosting:111">
      <h3 class="base-search-card__title">Analyst</h3>
    </div>
    <div data-entity-urn="urn:li:jobPosting:111">
      <h3 class="base-search-card__title">Analyst</h3>
    </div>
    <div data-entity-urn="urn:li:jobPosting:222">
      <h4 class="base-search-card__subtitle">No title here</h4>
    </div>
    """
    stubs = parse_search_results(page)
    assert [stub.job_id for stub in stubs] == ["111"]


def test_parse_detail_reads_jsonld_jobposting():
    stub = JobStub(
        job_id="4123456789",
        title="Data Analyst",
        company="Acme",
        location="Melbourne, Victoria, Australia",
        url="https://www.linkedin.com/jobs/view/4123456789",
        channel="local",
    )
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Data Analyst",
        "description": "<p>SQL &amp; dashboards</p>",
        "datePosted": "2026-01-02T03:04:05Z",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "Acme Pty Ltd"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "addressLocality": "Melbourne",
                "addressRegion": "VIC",
                "addressCountry": "Australia",
            },
        },
        "url": "https://example.com/apply",
    }
    html = f'<script type="application/ld+json">{json.dumps(posting)}</script>'

    job = parse_detail(stub, html)
    assert job.description == "SQL & dashboards"
    assert job.country == "AU"
    assert job.state == "VIC"
    assert job.city == "Melbourne"
    assert job.employment_type == "full_time"
    assert job.remote_type == "onsite"
    assert job.apply_url == "https://example.com/apply"
    assert job.posted_at is not None and job.posted_at.year == 2026


def test_parse_iso_datetime_handles_invalid():
    assert parse_iso_datetime("not-a-date") is None
    assert parse_iso_datetime(None) is None
    assert parse_iso_datetime("2026-01-02T00:00:00Z").tzinfo is not None


# --- storage ----------------------------------------------------------------


def test_seen_store_only_blocks_terminal_states(tmp_path):
    store = SeenStore.load(tmp_path / "seen.json")
    stub = JobStub(job_id="1", title="Data Analyst", company="Acme")

    store.mark(stub, STATE_FILTERED_LOCATION)
    assert not store.is_blocked(stub)  # can be re-considered later

    store.mark(stub, STATE_UPLOADED)
    assert store.is_blocked(stub)

    # A later non-terminal state does not downgrade the terminal one.
    store.mark(stub, STATE_FILTERED_LOCATION)
    assert store.is_blocked(stub)

    store.save()
    reloaded = SeenStore.load(tmp_path / "seen.json")
    assert reloaded.is_blocked(stub)


def test_seen_store_blocks_on_title_company_key(tmp_path):
    store = SeenStore.load(tmp_path / "seen.json")
    original = JobStub(job_id="1", title="Data Analyst", company="Acme Pty Ltd")
    store.mark(original, STATE_DUPLICATE)
    same_role = JobStub(job_id="999", title="Data Analyst", company="Acme Pty Ltd")
    assert store.is_blocked(same_role)


def test_checkpoint_round_trip(tmp_path):
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    checkpoint.mark_page_done("local|g|kw|1|0")
    checkpoint.mark_uploaded(["1", "2"])
    checkpoint.bump("discovered", 5)
    checkpoint.save()

    reloaded = Checkpoint.load(tmp_path / "checkpoint.json")
    assert reloaded.is_page_done("local|g|kw|1|0")
    assert reloaded.uploaded_job_ids == {"1", "2"}
    assert reloaded.stats["discovered"] == 5
    reloaded.reset()
    assert reloaded.completed_pages == set()


# --- uploader ---------------------------------------------------------------


def test_chunked_respects_server_limit():
    chunks = list(chunked(list(range(1200)), 500))
    assert [len(chunk) for chunk in chunks] == [500, 500, 200]


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://test.local",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer jagg_token"},
    )


def test_upload_posts_batch_and_returns_counts():
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "batch_id": 1,
                "status": "completed",
                "received_count": 1,
                "accepted_count": 1,
                "duplicate_count": 0,
                "rejected_count": 0,
                "errors": [],
            },
        )

    client = ImportClient("http://test.local", "jagg_token", client=_mock_client(handler))
    try:
        result = client.upload([{"source_job_id": "1", "title": "Data Analyst"}])
    finally:
        client.close()
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path == "/api/v1/import/jobs"
    assert "Idempotency-Key" in seen_requests[0].headers
    assert result["accepted_count"] == 1


def test_upload_raises_on_error_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid device token"})

    client = ImportClient("http://test.local", "jagg_token", client=_mock_client(handler))
    try:
        with pytest.raises(UploadError) as excinfo:
            client.upload([{"source_job_id": "1", "title": "x"}])
        assert excinfo.value.status_code == 401
    finally:
        client.close()


# --- manual scoped runs + status ---------------------------------------------


def _multi_scope_config():
    data = _config_dict()
    data["locations"] = {
        "centers": [
            {"country": "AU", "state": "VIC", "city": "Melbourne", "geo_id": "123"},
            {"country": "US", "state": "TX", "city": "Austin", "geo_id": "456"},
        ],
        "countries": [
            {"country": "AU", "geo_id": "101452733"},
            {"country": "US", "geo_id": "103644278"},
        ],
    }
    return config_from_dict(data)


def test_scope_queries_filters_by_country_code_and_name():
    from clients.linkedin_local_agent.main import scope_queries

    config = _multi_scope_config()
    by_code = scope_queries(config, country="US")
    by_name = scope_queries(config, country="United States")
    assert by_code and {q.country for q in by_code} == {"US"}
    assert [q.label for q in by_name] == [q.label for q in by_code]


def test_scope_queries_filters_by_city_keyword_and_channel():
    from clients.linkedin_local_agent.main import scope_queries

    config = _multi_scope_config()
    city = scope_queries(config, city="Melbourne")
    assert city and all(q.city == "Melbourne" for q in city)

    keyword = scope_queries(config, keyword="BI Analyst")
    assert keyword and all(q.keyword == "BI Analyst" for q in keyword)

    remote = scope_queries(config, channel="remote")
    assert remote and all(q.channel == "remote" for q in remote)

    narrowed = scope_queries(config, country="US", keyword="BI Analyst")
    assert len(narrowed) == 2  # local Austin + country-wide remote


def test_scope_queries_returns_empty_for_unknown_values():
    """An unmatched scope must yield nothing so the CLI can fail loudly."""
    from clients.linkedin_local_agent.main import scope_queries

    config = _multi_scope_config()
    assert scope_queries(config, country="Narnia") == []
    assert scope_queries(config, keyword="Astronaut") == []
    assert scope_queries(config)  # no filters -> whole matrix


def test_cli_errors_when_manual_scope_matches_nothing(tmp_path, capsys):
    from clients.linkedin_local_agent.main import main

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config_dict()), encoding="utf-8")

    code = main(["--config", str(config_path), "--list-queries", "--country", "Narnia"])
    assert code == 2


def test_cli_pages_and_limit_override_config_without_mutating_it(tmp_path):
    import argparse

    from clients.linkedin_local_agent.config import load_config
    from clients.linkedin_local_agent.main import _apply_overrides

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config_dict()), encoding="utf-8")
    config = load_config(config_path)
    original_pages = config.search.max_pages_per_query

    args = argparse.Namespace(pages=1, limit=20)
    updated = _apply_overrides(config, args)
    assert updated.search.max_pages_per_query == 1
    assert updated.search.max_detail_fetches == 20
    assert config.search.max_pages_per_query == original_pages  # unchanged


def test_apply_overrides_is_a_noop_without_flags():
    import argparse

    from clients.linkedin_local_agent.main import _apply_overrides

    config = config_from_dict(_config_dict())
    result = _apply_overrides(config, argparse.Namespace(pages=None, limit=None))
    assert result is config


def test_collect_status_reports_local_state(tmp_path):
    from clients.linkedin_local_agent.main import collect_status

    data = _config_dict()
    data["storage"] = {"data_dir": str(tmp_path)}
    config = config_from_dict(data)

    empty = collect_status(config)
    assert empty["seen_keys_tracked"] == 0
    assert empty["device_token_set"] is False
    assert empty["queries"] == len(build_queries(config))

    seen = SeenStore(tmp_path / "seen.json")
    seen.entries = {"1": {"status": STATE_UPLOADED, "job_id": "1"}}
    seen.save()
    checkpoint = Checkpoint(tmp_path / "checkpoint.json")
    checkpoint.mark_page_done("k1")
    checkpoint.mark_uploaded(["1"])
    checkpoint.bump("discovered", 3)
    checkpoint.save()

    status = collect_status(config)
    assert status["seen_keys_tracked"] == 1
    assert status["seen_by_status"] == {STATE_UPLOADED: 1}
    assert status["checkpoint"]["completed_pages"] == 1
    assert status["checkpoint"]["uploaded_job_ids"] == 1
    assert status["checkpoint"]["stats"]["discovered"] == 3
