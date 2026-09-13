"""Breezy HR public positions adapter.

Endpoint: ``https://{company}.breezy.hr/json``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.ats_adapters.config import load_board_tokens
from collectors.base import BaseCollector, SearchParams
from collectors.utils import (
    country_from_name,
    infer_country,
    normalize_employment_type,
    parse_datetime,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.breezy")

LIST_URL = "https://{company}.breezy.hr/json"


class BreezyCollector(BaseCollector):
    name = Source.BREEZY.value
    display_name = "Breezy HR"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        companies = load_board_tokens(self.settings, self.name)
        if not companies:
            logger.info("breezy: no companies configured, skipping")
            return

        async with self._client() as client:
            for company in companies:
                try:
                    response = await client.get(LIST_URL.format(company=company))
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("breezy: %s failed: %s", company, exc)
                    continue

                for raw in payload if isinstance(payload, list) else []:
                    job = self._parse(company, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, company: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("_id") or raw.get("id")
        title = (raw.get("name") or raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location") or {}
        if isinstance(location, str):
            location = {"name": location}
        state = (location.get("state") or {}).get("name") if isinstance(location.get("state"), dict) else location.get("state")
        country = (location.get("country") or {}).get("name") if isinstance(location.get("country"), dict) else location.get("country")
        city = location.get("city") or location.get("name")

        url = raw.get("url")
        if not url and raw.get("friendly_id"):
            url = f"https://{company}.breezy.hr/p/{raw['friendly_id']}"

        employment = (raw.get("type") or {}).get("name") if isinstance(raw.get("type"), dict) else raw.get("type")
        company_field = raw.get("company")
        if isinstance(company_field, dict):
            company_field = company_field.get("name")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=company_field or company.replace("-", " ").title(),
            description=trim(strip_html(raw.get("description"))),
            country=country_from_name(country) or infer_country(city),
            state=state,
            city=city,
            remote_type=RemoteType.REMOTE.value
            if location.get("is_remote") or raw.get("remote")
            else None,
            employment_type=normalize_employment_type(employment),
            posted_at=parse_datetime(raw.get("published_date") or raw.get("created_at")),
            raw_payload=raw,
        )
