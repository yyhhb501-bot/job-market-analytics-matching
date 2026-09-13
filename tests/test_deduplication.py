from __future__ import annotations

from packages.deduplication import (
    content_hash,
    dedup_key,
    normalize_company,
    normalize_text,
    normalize_url,
)
from packages.job_schema import NormalizedJob


def make_job(**overrides) -> NormalizedJob:
    data = {
        "source": "indeed",
        "source_job_id": "abc-1",
        "title": "Senior Data Engineer",
        "company": "Acme, Inc.",
        "description": "Build pipelines with Python and Spark.",
        "city": "Austin",
        "country": "US",
        "apply_url": "https://example.com/jobs/42",
    }
    data.update(overrides)
    return NormalizedJob(**data)


def test_normalize_text_strips_punctuation_and_case():
    assert normalize_text("  Senior  Data-Engineer!! ") == "senior data engineer"


def test_normalize_company_drops_legal_suffixes():
    assert normalize_company("Acme, Inc.") == "acme"
    assert normalize_company("Woolworths Group") == "woolworths"
    assert normalize_company("Globex Pty Ltd") == "globex"


def test_normalize_url_removes_tracking_and_www():
    url = "https://www.Example.com/jobs/42/?utm_source=newsletter&gh_src=xyz#apply"
    assert normalize_url(url) == "https://example.com/jobs/42"


def test_dedup_key_is_source_agnostic_but_content_hash_is_not():
    indeed_job = make_job(source="indeed", source_job_id="1")
    seek_job = make_job(source="seek", source_job_id="2")
    assert dedup_key(indeed_job) == dedup_key(seek_job)
    assert content_hash(indeed_job) != content_hash(seek_job)


def test_description_difference_changes_dedup_key():
    a = make_job(description="Python and Spark")
    b = make_job(description="A completely different job description")
    assert dedup_key(a) != dedup_key(b)
