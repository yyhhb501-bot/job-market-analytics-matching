"""Parse a LinkedIn job *detail* page into a :class:`CollectedJob`.

LinkedIn embeds a schema.org ``JobPosting`` JSON-LD block on public job pages,
which is far more stable than the DOM. We use it first and fall back to the
rendered description markup when it is missing.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from clients.linkedin_local_agent.models import CollectedJob, JobStub
from clients.linkedin_local_agent.parsing._html import strip_tags

_JSONLD = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_DESCRIPTION_BLOCK = re.compile(
    r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_APPLY_LINK = re.compile(
    r'href="(https?://[^"]+)"[^>]*data-tracking-control-name="public_jobs_apply-link[^"]*"',
    re.IGNORECASE,
)

_COUNTRY_CODES = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "australia": "AU",
    "australia ": "AU",
}

_EMPLOYMENT_TYPES = {
    "full_time": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "part_time": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "contractor": "contract",
    "contract": "contract",
    "temporary": "temporary",
    "intern": "internship",
    "internship": "internship",
    "casual": "casual",
    "volunteer": "other",
    "other": "other",
}


def _iter_ld_blocks(page_html: str) -> list[Any]:
    blocks: list[Any] = []
    for raw in _JSONLD.findall(page_html):
        try:
            blocks.append(json.loads(raw.strip()))
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def _find_job_posting(blocks: list[Any]) -> dict | None:
    queue = list(blocks)
    while queue:
        item = queue.pop(0)
        if isinstance(item, list):
            queue.extend(item)
        elif isinstance(item, dict):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "JobPosting" in types:
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    return None


def extract_job_posting(page_html: str) -> dict | None:
    return _find_job_posting(_iter_ld_blocks(page_html))


def parse_iso_datetime(value: Any) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def map_employment_type(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    return _EMPLOYMENT_TYPES.get(value.strip().lower())


def _country_code(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if len(text) == 2:
        return text.upper()
    return _COUNTRY_CODES.get(text)


def _first_location(posting: dict) -> dict:
    location = posting.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else {}
    return location if isinstance(location, dict) else {}


def _address_value(value: Any) -> str | None:
    """Address fields may be plain strings or schema.org objects (``{"name": ...}``)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name") or value.get("@id")
        return str(name) if name else None
    return None


def _remote_type(stub: JobStub, posting: dict) -> str:
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        return "remote"
    text = f"{stub.location} {stub.title}".lower()
    if stub.channel == "remote" or "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if stub.location:
        return "onsite"
    return "unknown"


def parse_detail(stub: JobStub, page_html: str) -> CollectedJob:
    """Build a :class:`CollectedJob` from a detail page (JSON-LD first)."""
    posting = extract_job_posting(page_html) or {}
    address = _first_location(posting).get("address") or {}
    if not isinstance(address, dict):
        address = {}

    description = strip_tags(posting.get("description"))
    if not description:
        block = re.search(_DESCRIPTION_BLOCK, page_html, re.IGNORECASE | re.DOTALL)
        if block:
            description = strip_tags(block.group(1))

    apply_match = _APPLY_LINK.search(page_html)
    apply_url = posting.get("url") or (apply_match.group(1) if apply_match else None)

    organization = posting.get("hiringOrganization")
    if isinstance(organization, list):
        organization = organization[0] if organization else {}
    company = stub.company
    if isinstance(organization, dict) and organization.get("name"):
        company = str(organization["name"])
    title = str(posting.get("title") or stub.title)

    return CollectedJob(
        stub=JobStub(
            job_id=stub.job_id,
            title=title,
            company=company,
            location=stub.location,
            url=stub.url,
            geo_id=stub.geo_id,
            channel=stub.channel,
        ),
        description=description or None,
        apply_url=apply_url,
        country=_country_code(_address_value(address.get("addressCountry"))),
        state=_address_value(address.get("addressRegion")),
        city=_address_value(address.get("addressLocality")),
        remote_type=_remote_type(stub, posting),
        employment_type=map_employment_type(posting.get("employmentType")),
        posted_at=parse_iso_datetime(posting.get("datePosted")),
    )


__all__ = [
    "extract_job_posting",
    "map_employment_type",
    "parse_detail",
    "parse_iso_datetime",
]
