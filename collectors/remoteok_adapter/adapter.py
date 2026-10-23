"""RemoteOK public JSON feed adapter.

The feed returns every currently listed remote job (first array element is the
legal/attribution notice). We filter locally by keyword so one request covers a
whole collection run.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import infer_country, parse_datetime, parse_salary_number, strip_html, trim
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.remoteok")

FEED_URL = "https://remoteok.com/api"


class RemoteOKCollector(BaseCollector):
    name = Source.REMOTEOK.value
    display_name = "RemoteOK"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        async with self._client() as client:
            if not await self._pre_request():
                return
            try:
                response = await client.get(FEED_URL)
                self._raise_for_status(response)
                payload = response.json()
            except (RateLimitedError, AccessBlockedError):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("remoteok: feed failed: %s", exc)
                return

        if not isinstance(payload, list):
            return

        collected = 0
        for raw in payload:
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("position"):
                continue  # skip the legal notice / malformed entries
            if not self._matches(raw, params):
                continue
            job = self._parse(raw)
            if job is not None:
                yield job
                collected += 1
                if collected >= params.results_wanted:
                    break

    def _matches(self, raw: dict, params: SearchParams) -> bool:
        if not params.keywords:
            return True
        haystack = " ".join(
            str(raw.get(key) or "") for key in ("position", "company", "description", "tags")
        ).lower()
        return params.keywords.lower() in haystack

    def _parse(self, raw: dict) -> NormalizedJob | None:
        title = (raw.get("position") or "").strip()
        if not title:
            return None

        location = raw.get("location")
        salary_min = parse_salary_number(raw.get("salary_min"))
        salary_max = parse_salary_number(raw.get("salary_max"))
        has_salary = salary_min is not None or salary_max is not None
        url = raw.get("url") or raw.get("apply_url")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(raw.get("id")),
            title=title,
            canonical_url=url,
            apply_url=raw.get("apply_url") or url,
            company=raw.get("company"),
            description=trim(strip_html(raw.get("description"))),
            country=infer_country(location if isinstance(location, str) else None),
            city=location if isinstance(location, str) else None,
            remote_type=RemoteType.REMOTE.value,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="USD" if has_salary else None,
            salary_period="year" if has_salary else None,
            posted_at=parse_datetime(raw.get("date") or raw.get("epoch")),
            raw_payload=raw,
        )
