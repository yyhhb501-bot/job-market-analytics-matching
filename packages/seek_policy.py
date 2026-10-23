"""Validation, classification and quotas for authorised SEEK AU imports.

This module is deliberately pure Python so the API gateway, tests and any
future local collector share exactly the same acceptance rules.  It does not
make network requests and it does not attempt to bypass SEEK controls.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping

SEEK_IMPORT_SOURCE = "seek_user_import"
SEEK_SOURCE_NAMES = frozenset({"seek", SEEK_IMPORT_SOURCE})
SEEK_DAILY_TARGET = 600
SEEK_HOURLY_LIMIT = 50
SEEK_LOOKBACK_DAYS = 7
SEEK_MIN_COMPLETENESS = 75

PREFERRED_TITLE_PATTERNS = (
    re.compile(r"\bregistered\s+nurse\b", re.I),
    re.compile(r"\bRN\b", re.I),
    re.compile(r"\bclinical\s+nurse\b", re.I),
)
ALLOWED_TITLE_PATTERNS = PREFERRED_TITLE_PATTERNS + (
    re.compile(r"\bpractice\s+nurse\b", re.I),
    re.compile(r"\bcommunity\s+nurse\b", re.I),
    re.compile(r"\baged\s+care\s+(?:registered\s+)?nurse\b", re.I),
    re.compile(r"\bmental\s+health\s+nurse\b", re.I),
    re.compile(r"\btheatre\s+nurse\b", re.I),
    re.compile(r"\bemergency\s+nurse\b", re.I),
    re.compile(r"\bICU\s+nurse\b", re.I),
    re.compile(r"\bpaediatric\s+nurse\b", re.I),
    re.compile(r"\boncology\s+nurse\b", re.I),
    re.compile(r"\bscrub\s*scout\s+nurse\b", re.I),
    re.compile(r"\bperioperative\s+nurse\b", re.I),
)
EXCLUDED_TITLE_PATTERNS = (
    re.compile(r"\benrolled\s+nurse\b", re.I),
    re.compile(r"\bassistant\s+in\s+nursing\b", re.I),
    re.compile(r"\bAIN\b", re.I),
    re.compile(r"\bpersonal\s+care\s+worker\b", re.I),
    re.compile(r"\bnurse\s+assistant\b", re.I),
    re.compile(r"\bnursing\s+student\b", re.I),
)

STATE_ALIASES = {
    "NEW SOUTH WALES": "NSW",
    "VICTORIA": "VIC",
    "QUEENSLAND": "QLD",
    "WESTERN AUSTRALIA": "WA",
    "SOUTH AUSTRALIA": "SA",
    "TASMANIA": "TAS",
    "AUSTRALIAN CAPITAL TERRITORY": "ACT",
    "NORTHERN TERRITORY": "NT",
}
STATES = frozenset({"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"})

SPECIALTY_PATTERNS = {
    "Aged Care": re.compile(r"aged\s+care|residential\s+care|elderly", re.I),
    "Mental Health": re.compile(r"mental\s+health|psychiatr", re.I),
    "Emergency": re.compile(r"\bemergency\b|\bED\s+nurse", re.I),
    "ICU": re.compile(r"\bICU\b|intensive\s+care|critical\s+care", re.I),
    "Theatre": re.compile(r"theatre|operating\s+room|scrub\s*scout|perioperative", re.I),
    "Community": re.compile(r"community\s+nurs|community\s+care|home\s+care", re.I),
    "General Practice": re.compile(r"general\s+practice|\bGP\b|practice\s+nurse", re.I),
    "Paediatrics": re.compile(r"paediatric|pediatric|children", re.I),
    "Oncology": re.compile(r"oncolog", re.I),
}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _raw(job: object) -> Mapping[str, object]:
    payload = getattr(job, "raw_payload", None)
    return payload if isinstance(payload, Mapping) else {}


def normalise_state(value: object) -> str | None:
    text = _text(value).upper()
    if not text:
        return None
    if text in STATES:
        return text
    for name, code in STATE_ALIASES.items():
        if name in text:
            return code
    return None


def has_seek_url(value: object) -> bool:
    url = _text(value)
    return bool(
        re.match(
            r"^https://(?:(?:www\.)?seek\.com\.au|au\.seek\.com)/job/\d+(?:[/?#]|$)",
            url,
            re.I,
        )
    )


def title_in_scope(title: object) -> bool:
    text = _text(title)
    if not any(pattern.search(text) for pattern in ALLOWED_TITLE_PATTERNS):
        return False
    # A mixed Registered/Enrolled posting is explicitly allowed.  An Enrolled
    # Nurse-only title remains excluded.
    return any(pattern.search(text) for pattern in PREFERRED_TITLE_PATTERNS) or any(
        pattern.search(text) for pattern in ALLOWED_TITLE_PATTERNS[3:]
    )


def title_is_excluded(title: object) -> bool:
    text = _text(title)
    if not text:
        return True
    has_registered_signal = any(pattern.search(text) for pattern in PREFERRED_TITLE_PATTERNS)
    return any(pattern.search(text) for pattern in EXCLUDED_TITLE_PATTERNS) and not has_registered_signal


def is_mixed_nurse_title(title: object) -> bool:
    text = _text(title)
    return bool(
        any(pattern.search(text) for pattern in PREFERRED_TITLE_PATTERNS)
        and any(pattern.search(text) for pattern in EXCLUDED_TITLE_PATTERNS)
    )


def specialty_tags(job: object) -> list[str]:
    raw = _raw(job)
    supplied = raw.get("specialty_tags")
    if isinstance(supplied, list):
        values = [_text(item) for item in supplied if _text(item)]
        if values:
            return list(dict.fromkeys(values))
    text = " ".join(
        _text(value)
        for value in (getattr(job, "title", None), getattr(job, "description", None), raw.get("detail_text"))
    )
    return [name for name, pattern in SPECIALTY_PATTERNS.items() if pattern.search(text)]


def posted_at(job: object) -> dt.datetime | None:
    value = getattr(job, "posted_at", None)
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return None


def completeness_score(job: object) -> int:
    raw = _raw(job)
    title = _text(getattr(job, "title", None))
    company = _text(getattr(job, "company", None))
    location = _text(getattr(job, "city", None)) or _text(getattr(job, "state", None))
    description = _text(getattr(job, "description", None))
    work_type = _text(getattr(job, "employment_type", None))
    specialty = specialty_tags(job)
    score = 0
    score += 10 if title else 0
    score += 10 if company else 0
    score += 10 if location or _text(raw.get("location_text")) else 0
    score += 15 if posted_at(job) else 0
    score += 25 if len(description) >= 120 or raw.get("detail_status") == "complete" else 0
    score += 10 if has_seek_url(getattr(job, "canonical_url", None)) else 0
    score += 5 if work_type else 0
    score += 5 if getattr(job, "salary_min", None) is not None else 0
    score += 5 if specialty else 0
    score += 5 if _text(raw.get("shift_information")) else 0
    return score


def validate_seek_job(job: object, *, now: dt.datetime | None = None) -> tuple[bool, int, list[str], dict[str, object]]:
    """Return ``(valid, score, reasons, metadata)`` for one SEEK job."""
    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    raw = _raw(job)
    reasons: list[str] = []
    source = _text(getattr(job, "source", None))
    if source not in SEEK_SOURCE_NAMES:
        reasons.append("source_not_seek")
    if _text(getattr(job, "country", None)).upper() != "AU":
        reasons.append("country_not_au")
    title = _text(getattr(job, "title", None))
    if not title:
        reasons.append("missing_title")
    elif raw.get("collection_scope") == "registered_nurse":
        if not re.search(r"\bregistered[\s-]+nurses?\b|\bRNs?\b", title, re.I):
            reasons.append("title_out_of_scope")
    elif raw.get("collection_scope") == "all_search_results":
        pass  # User explicitly requested every listing on the search page.
    elif title_is_excluded(title):
        reasons.append("excluded_title")
    elif not title_in_scope(title):
        reasons.append("title_out_of_scope")
    if not _text(getattr(job, "company", None)):
        reasons.append("missing_company")
    if not (_text(getattr(job, "city", None)) or normalise_state(getattr(job, "state", None)) or _text(raw.get("location_text"))):
        reasons.append("missing_location")
    description = _text(getattr(job, "description", None))
    if len(description) < 120 and raw.get("detail_status") != "complete":
        reasons.append("incomplete_description")
    if not has_seek_url(getattr(job, "canonical_url", None)):
        reasons.append("invalid_seek_url")
    if getattr(job, "closed", None) is True or raw.get("closed") is True:
        reasons.append("job_closed")
    published = posted_at(job)
    if published is None:
        reasons.append("missing_posted_at")
    else:
        age = now - published.astimezone(dt.UTC)
        if age.total_seconds() < -300 or age > dt.timedelta(days=SEEK_LOOKBACK_DAYS):
            reasons.append("outside_7_day_window")
    score = completeness_score(job)
    if score < SEEK_MIN_COMPLETENESS:
        reasons.append("completeness_below_75")
    metadata = {
        "mixed_nurse_title": is_mixed_nurse_title(title),
        "specialty_tags": specialty_tags(job),
        "state_code": normalise_state(getattr(job, "state", None)),
        "quality_score": score,
    }
    return not reasons, score, reasons, metadata


__all__ = [
    "SEEK_DAILY_TARGET",
    "SEEK_HOURLY_LIMIT",
    "SEEK_IMPORT_SOURCE",
    "SEEK_LOOKBACK_DAYS",
    "SEEK_MIN_COMPLETENESS",
    "SEEK_SOURCE_NAMES",
    "completeness_score",
    "normalise_state",
    "specialty_tags",
    "title_in_scope",
    "validate_seek_job",
]
