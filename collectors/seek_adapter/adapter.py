"""Legacy SEEK Australia server-side adapter (disabled by default).

The former public search endpoint returned HTTP 404 when checked on 2026-09-21.
Keep ``ENABLE_SEEK=false`` and use the user-triggered local browser extension in
``clients/seek_edge_extension`` unless SEEK has granted written/API access.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from apps.api.config import Settings
from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import (
    parse_datetime,
    parse_salary_range,
    split_location,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.seek")


class SeekCollector(BaseCollector):
    name = Source.SEEK.value
    display_name = "SEEK (AU)"
    SEARCH_URL = "https://www.seek.com.au/api/chalice-search/v4/search"
    PAGE_SIZE = 30

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        # SEEK's documented rate floor: space requests via the shared throttle.
        self.min_interval_seconds = 60.0 / max(self.settings.seek_requests_per_minute, 1)

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        where = params.location or "All Australia"
        keywords = params.keywords or ""
        collected = 0
        page = 1
        headers = {"Accept": "application/json", "Referer": "https://www.seek.com.au/"}

        async with self._client(headers=headers) as client:
            while collected < params.results_wanted:
                if not await self._pre_request():
                    return
                query = {
                    "siteKey": "AU-Main",
                    "sourcesystem": "houston",
                    "where": where,
                    "keywords": keywords,
                    "page": page,
                    "pageSize": self.PAGE_SIZE,
                    "locale": "en-AU",
                }
                try:
                    payload = await self._board_json(
                        client, self.SEARCH_URL, board="search", params=query, headers=headers
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("seek: page %s failed: %s", page, exc)
                    return

                rows = payload.get("data") or []
                if not rows:
                    break
                for raw in rows:
                    job = self._parse(raw)
                    if job is not None:
                        yield job
                        collected += 1
                        if collected >= params.results_wanted:
                            break
                page += 1

    def _parse(self, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id") or raw.get("jobId")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        advertiser = raw.get("advertiser") or {}
        company = (
            raw.get("companyName")
            or advertiser.get("description")
            or advertiser.get("name")
        )
        location = raw.get("location") or raw.get("area") or raw.get("locationHierarchy")
        city, state = split_location(location if isinstance(location, str) else None)

        salary_min, salary_max, currency, period = parse_salary_range(
            raw.get("salary"), default_currency="AUD"
        )
        url = raw.get("jobUrl") or raw.get("url") or f"https://www.seek.com.au/job/{job_id}"
        description = raw.get("teaser") or raw.get("description")
        work_type = (raw.get("workType") or "").lower().replace(" ", "_") or None

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=company,
            description=trim(strip_html(description)),
            country="AU",
            state=state,
            city=city,
            remote_type=RemoteType.REMOTE.value
            if isinstance(location, str) and "remote" in location.lower()
            else None,
            employment_type=work_type,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            salary_period=period,
            posted_at=parse_datetime(raw.get("listingDate")),
            raw_payload=raw,
        )
