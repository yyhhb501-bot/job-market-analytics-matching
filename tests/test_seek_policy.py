from __future__ import annotations

import datetime as dt

from packages.job_schema import NormalizedJob
from packages.seek_policy import validate_seek_job


def valid_seek_job(**overrides) -> NormalizedJob:
    payload = {
        "source": "seek_user_import",
        "source_job_id": "12345678",
        "title": "Registered Nurse - Aged Care",
        "company": "Example Health Pty Ltd",
        "description": "Provide safe person-centred nursing care, clinical assessment, medication management and documentation for residents. Work with families and the multidisciplinary team to deliver high quality outcomes.",
        "country": "AU",
        "state": "VIC",
        "city": "Melbourne",
        "employment_type": "Full time",
        "canonical_url": "https://www.seek.com.au/job/12345678",
        "posted_at": dt.datetime.now(dt.UTC) - dt.timedelta(days=2),
        "raw_payload": {"detail_status": "complete", "shift_information": "day and night shifts"},
    }
    payload.update(overrides)
    return NormalizedJob(**payload)


def test_accepts_complete_recent_registered_nurse_job():
    valid, score, reasons, metadata = validate_seek_job(valid_seek_job())
    assert valid is True
    assert score >= 75
    assert reasons == []
    assert metadata["specialty_tags"] == ["Aged Care"]


def test_registered_nurse_scope_accepts_variants_and_rejects_other_roles():
    for title in ["Registered Nurses - ICU", "RN", "Registered-Nurse"]:
        assert validate_seek_job(valid_seek_job(
            title=title, raw_payload={"collection_scope": "registered_nurse"}
        ))[0]
    for title in ["Enrolled Nurse", "Clinical Nurse", "Assistant in Nursing"]:
        result = validate_seek_job(valid_seek_job(
            title=title, raw_payload={"collection_scope": "registered_nurse"}
        ))
        assert not result[0]
        assert "title_out_of_scope" in result[2]


def test_accepts_current_au_seek_com_job_urls():
    valid, score, reasons, _ = validate_seek_job(
        valid_seek_job(canonical_url="https://au.seek.com/job/12345678")
    )
    assert valid is True
    assert score >= 75
    assert reasons == []


def test_rejects_enrolled_nurse_only_title_but_keeps_mixed_posting():
    valid, _, reasons, _ = validate_seek_job(valid_seek_job(title="Enrolled Nurse - Residential Care"))
    assert valid is False
    assert "excluded_title" in reasons

    valid, _, reasons, metadata = validate_seek_job(
        valid_seek_job(title="Registered Nurse / Enrolled Nurse")
    )
    assert valid is True
    assert reasons == []
    assert metadata["mixed_nurse_title"] is True


def test_rejects_old_or_incomplete_jobs():
    old = valid_seek_job(posted_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=8))
    valid, _, reasons, _ = validate_seek_job(old)
    assert valid is False
    assert "outside_7_day_window" in reasons

    incomplete = valid_seek_job(description="Short teaser", raw_payload={})
    valid, _, reasons, _ = validate_seek_job(incomplete)
    assert valid is False
    assert "incomplete_description" in reasons


def test_all_search_results_accepts_other_titles_but_still_requires_complete_details():
    raw = {"collection_scope": "all_search_results"}
    valid, _, reasons, _ = validate_seek_job(valid_seek_job(title="Clinical Assessor Delegate", raw_payload=raw))
    assert valid is True
    assert reasons == []
    valid, _, reasons, _ = validate_seek_job(valid_seek_job(title="Clinical Assessor Delegate", description="Teaser", raw_payload=raw))
    assert valid is False
    assert "incomplete_description" in reasons
