"""Ashby public job-board adapter.

Endpoint: ``https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.ats_adapters.config import load_board_tokens
from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import (
    infer_country,
    parse_datetime,
    parse_salary_range,
    split_location,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.ashby")


class AshbyCollector(BaseCollector):
    name = Source.ASHBY.value
    display_name = "Ashby"
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        orgs = load_board_tokens(self.settings, self.name)
        if not orgs:
            logger.info("ashby: no boards configured, skipping")
            return
        async with self._client() as client:
            for org in orgs:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client,
                        self.BASE_URL.format(org=org),
                        board=org,
                        params={"includeCompensation": "true"},
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(org, exc)
                    logger.warning("ashby: board %s failed: %s", org, exc)
                    continue
                for raw in payload.get("jobs", []):
                    job = self._parse(org, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, org: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location")
        address = (raw.get("address") or {}).get("postalAddress") or {}
        city = address.get("addressLocality")
        state = address.get("addressRegion")
        if not city:
            city, state = split_location(location)
        country = infer_country(address.get("addressCountry") or location)

        compensation = raw.get("compensation") or {}
        summary = compensation.get("compensationTierSummary")
        salary_min, salary_max, currency, period = parse_salary_range(summary)

        remote_type = RemoteType.REMOTE.value if raw.get("isRemote") else None
        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=raw.get("jobUrl") or raw.get("applyUrl"),
            apply_url=raw.get("applyUrl") or raw.get("jobUrl"),
            company=org.replace("-", " ").title(),
            description=trim(strip_html(raw.get("descriptionHtml"))),
            country=country,
            state=state,
            city=city,
            remote_type=remote_type,
            employment_type=(raw.get("employmentType") or "").lower() or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            salary_period=period,
            posted_at=parse_datetime(raw.get("publishedAt")),
            raw_payload=raw,
        )
