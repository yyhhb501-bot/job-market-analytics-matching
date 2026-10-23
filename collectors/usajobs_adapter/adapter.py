"""USAJOBS Search API adapter.

Docs: https://developer.usajobs.gov/api-reference/
Requires a registered email + API key. The API demands the caller's email in
``User-Agent`` and the key in ``Authorization-Key``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    CollectorError,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import parse_datetime, parse_salary_number
from packages.job_schema import NormalizedJob, Source

logger = logging.getLogger("jobagg.collectors.usajobs")

_RATE_INTERVAL = {
    "per year": "year",
    "per annum": "year",
    "pa": "year",
    "per month": "month",
    "per hour": "hour",
    "ph": "hour",
    "bi-weekly": "week",
    "per week": "week",
    "per day": "day",
}


class USAJobsCollector(BaseCollector):
    name = Source.USAJOBS.value
    display_name = "USAJOBS"
    requires_credentials = True
    BASE_URL = "https://data.usajobs.gov/api/search"

    def validate(self) -> None:
        missing = []
        if not self.settings.usajobs_email:
            missing.append("USAJOBS_EMAIL")
        if not self.settings.usajobs_api_key:
            missing.append("USAJOBS_API_KEY")
        if missing:
            raise CollectorError(f"USAJOBS requires {', '.join(missing)}")

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        self.validate()
        headers = {
            "User-Agent": self.settings.usajobs_email,
            "Authorization-Key": self.settings.usajobs_api_key,
            "Accept": "application/json",
        }
        page = 1
        collected = 0
        async with self._client(headers=headers) as client:
            while collected < params.results_wanted:
                query = {
                    "Keyword": params.keywords or "",
                    "ResultsPerPage": min(500, params.results_wanted - collected),
                    "Page": page,
                }
                if params.location:
                    query["LocationName"] = params.location
                if not await self._pre_request():
                    return
                try:
                    response = await client.get(
                        self.BASE_URL, params=query, headers={"Host": "data.usajobs.gov"}
                    )
                    self._raise_for_status(response)
                    payload = response.json()
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("usajobs: page %s failed: %s", page, exc)
                    break

                items = (payload.get("SearchResult") or {}).get("SearchResultItems") or []
                if not items:
                    break
                for item in items:
                    job = self._parse(item.get("MatchedObjectDescriptor") or item)
                    if job is not None:
                        yield job
                        collected += 1
                page += 1

    def _parse(self, descriptor: dict) -> NormalizedJob | None:
        job_id = descriptor.get("PositionID") or descriptor.get("MatchedObjectId")
        title = (descriptor.get("PositionTitle") or "").strip()
        if not job_id or not title:
            return None

        locations = descriptor.get("PositionLocation") or []
        primary = locations[0] if locations else {}
        country = "US"
        if (primary.get("CountryCode") or "").lower().startswith("australia"):
            country = "AU"

        remuneration = descriptor.get("PositionRemuneration") or []
        salary_min = salary_max = None
        currency = "USD"
        period = None
        if remuneration:
            top = remuneration[0]
            salary_min = parse_salary_number(top.get("MinimumRange"))
            salary_max = parse_salary_number(top.get("MaximumRange"))
            period = _RATE_INTERVAL.get((top.get("RateIntervalCode") or "").lower())

        apply_uris = descriptor.get("ApplyURI") or []
        apply_url = apply_uris[0] if apply_uris else descriptor.get("PositionURI")

        details = (descriptor.get("UserArea") or {}).get("Details") or {}
        summary = details.get("JobSummary")
        offerings = details.get("PositionOfferingType") or []
        employment_type = (offerings[0].get("Name") if offerings else None) or None

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=descriptor.get("PositionURI"),
            apply_url=apply_url,
            company=descriptor.get("OrganizationName") or descriptor.get("DepartmentName"),
            description=summary,
            country=country,
            state=primary.get("CountrySubDivisionCode"),
            city=primary.get("CityName"),
            employment_type=employment_type.lower() if employment_type else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency if salary_min or salary_max else None,
            salary_period=period,
            posted_at=parse_datetime(descriptor.get("PublicationStartDate")),
            expires_at=parse_datetime(descriptor.get("ApplicationCloseDate")),
            raw_payload=descriptor,
        )
