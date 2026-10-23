"""Recruitee public offers adapter.

Endpoint: ``https://{company}.recruitee.com/api/offers/``
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
    normalize_employment_type,
    parse_datetime,
    parse_salary_number,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.recruitee")

LIST_URL = "https://{company}.recruitee.com/api/offers/"


class RecruiteeCollector(BaseCollector):
    name = Source.RECRUITEE.value
    display_name = "Recruitee"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        companies = load_board_tokens(self.settings, self.name)
        if not companies:
            logger.info("recruitee: no companies configured, skipping")
            return

        async with self._client() as client:
            for company in companies:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client, LIST_URL.format(company=company), board=company
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(company, exc)
                    logger.warning("recruitee: %s failed: %s", company, exc)
                    continue

                offers = payload.get("offers") if isinstance(payload, dict) else payload
                for raw in offers or []:
                    job = self._parse(company, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, company: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        salary = raw.get("salary") or {}
        salary_min = parse_salary_number(salary.get("min"))
        salary_max = parse_salary_number(salary.get("max"))
        has_salary = salary_min is not None or salary_max is not None
        period = (salary.get("period") or "").lower() or None
        if period not in {"year", "month", "week", "day", "hour"}:
            period = "year" if has_salary else None

        description = strip_html(
            "\n".join(
                part for part in (raw.get("description"), raw.get("requirements")) if part
            )
        )
        url = raw.get("careers_url") or raw.get("url")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=raw.get("careers_apply_url") or url,
            company=(raw.get("company_name") or company.replace("-", " ").title()),
            description=trim(description),
            country=country_from_name(raw.get("country_code")) or country_from_name(raw.get("country")),
            state=raw.get("state_name") or raw.get("state"),
            city=raw.get("city"),
            remote_type=RemoteType.REMOTE.value if raw.get("remote") else None,
            employment_type=normalize_employment_type(raw.get("employment_type_code")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=(salary.get("currency") or "").upper() or None if has_salary else None,
            salary_period=period,
            posted_at=parse_datetime(raw.get("created_at") or raw.get("published_at")),
            raw_payload=raw,
        )
