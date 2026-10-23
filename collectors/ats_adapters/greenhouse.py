"""Greenhouse public job board adapter.

Endpoint: ``https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true``
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
from collectors.utils import infer_country, parse_datetime, split_location, strip_html, trim
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.greenhouse")


class GreenhouseCollector(BaseCollector):
    name = Source.GREENHOUSE.value
    display_name = "Greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        tokens = load_board_tokens(self.settings, self.name)
        if not tokens:
            logger.info("greenhouse: no boards configured, skipping")
            return
        async with self._client() as client:
            for token in tokens:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client,
                        self.BASE_URL.format(token=token),
                        board=token,
                        params={"content": "true"},
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001 - keep going across boards
                    self._note_board_failure(token, exc)
                    logger.warning("greenhouse: board %s failed: %s", token, exc)
                    continue
                for raw in payload.get("jobs", []):
                    job = self._parse(token, raw)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, token: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("title") or "").strip()
        if job_id is None or not title:
            return None
        location = (raw.get("location") or {}).get("name")
        city, state = split_location(location)
        country = infer_country(location)
        url = raw.get("absolute_url")
        remote_type = RemoteType.REMOTE.value if location and "remote" in location.lower() else None
        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=raw.get("company_name") or token.replace("-", " ").title(),
            description=trim(strip_html(raw.get("content"))),
            country=country,
            state=state,
            city=city,
            remote_type=remote_type,
            posted_at=parse_datetime(raw.get("first_published") or raw.get("updated_at")),
            raw_payload=raw,
        )
