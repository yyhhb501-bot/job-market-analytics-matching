"""Pinpoint public postings feed adapter.

Feed: ``https://{company}.pinpointhq.com/postings.json``

Docs: https://developers.pinpointhq.com/docs/jobs-json-endpoint
"""

from __future__ import annotations

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

logger = logging.getLogger("jobagg.collectors.pinpoint")

FEED_URL = "https://{company}.pinpointhq.com/postings.json"


class PinpointCollector(BaseCollector):
    name = Source.PINPOINT.value
    display_name = "Pinpoint"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        companies = load_board_tokens(self.settings, self.name)
        if not companies:
            logger.info("pinpoint: no boards configured, skipping")
            return

        async with self._client() as client:
            for company in companies:
                try:
                    response = await client.get(FEED_URL.format(company=company))
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("pinpoint: %s failed: %s", company, exc)
                    continue
                for raw in payload.get("data") or []:
                    job = self._parse(company, raw)
                    if job is not None:
                        yield job

    def _parse(self, company: str, raw: dict) -> NormalizedJob | None:
        job = raw.get("job") or {}
        job_id = raw.get("id") or job.get("id")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location") or {}
        city = raw.get("city") or location.get("city") or location.get("name")
        state = raw.get("state") or location.get("region")
        country = country_from_name(raw.get("country") or location.get("country")) or infer_country(
            location.get("name") or city
        )

        workplace = str(raw.get("workplace_type") or "").lower()
        if workplace == "remote":
            remote_type = RemoteType.REMOTE.value
        elif workplace == "hybrid":
            remote_type = RemoteType.HYBRID.value
        else:
            remote_type = None

        url = raw.get("url")
        if not url and raw.get("path"):
            url = f"https://{company}.pinpointhq.com{raw['path']}"

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=raw.get("company") or company.replace("-", " ").title(),
            description=trim(strip_html(raw.get("description") or raw.get("description_html"))),
            country=country,
            state=state,
            city=city,
            remote_type=remote_type,
            employment_type=normalize_employment_type(
                raw.get("employment_type") or job.get("employment_type")
            ),
            posted_at=parse_datetime(
                raw.get("created_at") or raw.get("published_at") or job.get("created_at")
            ),
            raw_payload=raw,
        )
