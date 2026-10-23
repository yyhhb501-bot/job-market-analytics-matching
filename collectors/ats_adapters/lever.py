"""Lever public postings adapter.

Endpoint: ``https://api.lever.co/v0/postings/{company}?mode=json``
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
    parse_salary_number,
    split_location,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.lever")


class LeverCollector(BaseCollector):
    name = Source.LEVER.value
    display_name = "Lever"
    BASE_URL = "https://api.lever.co/v0/postings/{company}"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        companies = load_board_tokens(self.settings, self.name)
        if not companies:
            logger.info("lever: no boards configured, skipping")
            return
        async with self._client() as client:
            for company in companies:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client,
                        self.BASE_URL.format(company=company),
                        board=company,
                        params={"mode": "json"},
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(company, exc)
                    logger.warning("lever: board %s failed: %s", company, exc)
                    continue
                for raw in payload if isinstance(payload, list) else []:
                    job = self._parse(company, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, company: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("text") or "").strip()
        if not job_id or not title:
            return None
        categories = raw.get("categories") or {}
        location = categories.get("location")
        city, state = split_location(location)
        workplace = (raw.get("workplaceType") or "").lower()
        remote_type = RemoteType.REMOTE.value if "remote" in workplace else None

        salary = raw.get("salaryRange") or {}
        salary_min = parse_salary_number(salary.get("min"))
        salary_max = parse_salary_number(salary.get("max"))
        currency = salary.get("currency")
        interval = (salary.get("interval") or "").lower()
        period = {"per-year-salary": "year", "per-month": "month", "per-hour": "hour"}.get(interval)

        description = raw.get("descriptionPlain") or strip_html(raw.get("description"))
        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=raw.get("hostedUrl"),
            apply_url=raw.get("applyUrl") or raw.get("hostedUrl"),
            company=company.replace("-", " ").title(),
            description=trim(description),
            country=infer_country(location),
            state=state,
            city=city,
            remote_type=remote_type,
            employment_type=(categories.get("commitment") or "").lower() or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            salary_period=period,
            posted_at=parse_datetime(raw.get("createdAt")),
            raw_payload=raw,
        )
