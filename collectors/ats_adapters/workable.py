"""Workable public widget adapter.

Endpoint: ``https://apply.workable.com/api/v1/widget/accounts/{account}?details=true``
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
    country_from_name,
    parse_datetime,
    parse_salary_range,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.workable")


class WorkableCollector(BaseCollector):
    name = Source.WORKABLE.value
    display_name = "Workable"
    BASE_URL = "https://apply.workable.com/api/v1/widget/accounts/{account}"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        accounts = load_board_tokens(self.settings, self.name)
        if not accounts:
            logger.info("workable: no boards configured, skipping")
            return
        async with self._client() as client:
            for account in accounts:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client,
                        self.BASE_URL.format(account=account),
                        board=account,
                        params={"details": "true"},
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(account, exc)
                    logger.warning("workable: board %s failed: %s", account, exc)
                    continue
                employer = payload.get("name") or account.replace("-", " ").title()
                for raw in payload.get("jobs", []):
                    job = self._parse(account, employer, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, account: str, employer: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id") or raw.get("shortcode")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location") or {}
        salary = raw.get("salary") or {}
        salary_min, salary_max, currency, period = parse_salary_range(salary.get("formatted"))

        description_parts = [raw.get("description"), raw.get("requirements"), raw.get("benefits")]
        description = strip_html("\n".join(part for part in description_parts if part))

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=raw.get("url") or raw.get("shortlink"),
            apply_url=raw.get("application_url") or raw.get("url"),
            company=employer,
            description=trim(description),
            country=country_from_name(location.get("country")) or country_from_name(location.get("countryCode")),
            state=location.get("region"),
            city=location.get("city"),
            remote_type=RemoteType.REMOTE.value if raw.get("telecommuting") else None,
            employment_type=(raw.get("employment_type") or "").lower().replace(" ", "_") or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=currency,
            salary_period=period,
            posted_at=parse_datetime(raw.get("created_at") or raw.get("published_on")),
            raw_payload=raw,
        )
