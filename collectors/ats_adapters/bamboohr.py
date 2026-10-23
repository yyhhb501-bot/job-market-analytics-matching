"""BambooHR public careers adapter.

List:   ``https://{company}.{domain}/careers/list``
Detail: ``https://{company}.{domain}/careers/{id}/detail``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.ats_adapters.config import load_board_entries
from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import (
    country_from_name,
    infer_country,
    normalize_employment_type,
    parse_datetime,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.bamboohr")

DEFAULT_DOMAIN = "bamboohr.com"


class BambooHRCollector(BaseCollector):
    name = Source.BAMBOOHR.value
    display_name = "BambooHR"

    def _entries(self) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for entry in load_board_entries(self.settings, self.name):
            token = entry.get("token")
            if not token:
                continue
            entries.append((str(token), str(entry.get("domain") or DEFAULT_DOMAIN)))
        return entries

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        entries = self._entries()
        if not entries:
            logger.info("bamboohr: no companies configured, skipping")
            return

        async with self._client() as client:
            for company, domain in entries:
                base = f"https://{company}.{domain}"
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client, f"{base}/careers/list", board=company
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(company, exc)
                    logger.warning("bamboohr: %s failed: %s", company, exc)
                    continue

                for raw in payload.get("result") or []:
                    detail = await self._fetch_detail(client, base, raw.get("id"))
                    job = self._parse(company, base, raw, detail)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    async def _fetch_detail(self, client, base: str, job_id) -> dict | None:
        if job_id is None:
            return None
        if not await self._note_detail():
            return None
        try:
            response = await client.get(f"{base}/careers/{job_id}/detail")
            self._raise_for_status(response)
            return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("bamboohr: detail %s failed: %s", job_id, exc)
            return None

    def _parse(
        self, company: str, base: str, raw: dict, detail: dict | None
    ) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("jobOpeningName") or "").strip()
        if job_id is None or not title:
            return None

        info = ((detail or {}).get("result") or {}).get("jobOpening") or {}
        ats_location = raw.get("atsLocation") or {}
        location_bits = raw.get("location") or {}
        city = ats_location.get("city") or location_bits.get("city") or info.get("location", {}).get("city")
        state = ats_location.get("state") or location_bits.get("state")
        country = country_from_name(ats_location.get("country")) or infer_country(city)

        parts = [info.get("description"), info.get("requirements")]
        details = info.get("details")
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict):
                    parts.append(item.get("value") or item.get("content"))
        description = strip_html("\n".join(part for part in parts if part))

        is_remote = raw.get("isRemote") or info.get("isRemote")
        employment = raw.get("employmentStatusLabel") or raw.get("employmentType")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=f"{base}/careers/{job_id}",
            apply_url=f"{base}/careers/{job_id}",
            company=company.replace("-", " ").title(),
            description=trim(description),
            country=country,
            state=state,
            city=city,
            remote_type=RemoteType.REMOTE.value if is_remote else None,
            employment_type=normalize_employment_type(employment),
            posted_at=parse_datetime(info.get("postedDate") or info.get("createDate")),
            raw_payload=raw,
        )
