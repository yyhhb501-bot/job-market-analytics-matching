"""Jobvite Job Feed adapter (per-account key + secret).

Feed: ``https://api.jobvite.com/api/v2/job?api={key}&sc={secret}``

Entries::

    {"api": "...", "sc": "...", "site": "career-site-name"}

The Job Feed is a paid Jobvite feature; entries without credentials are skipped.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from collectors.ats_adapters.config import load_board_entries
from collectors.base import BaseCollector, SearchParams
from collectors.utils import (
    country_from_name,
    normalize_employment_type,
    parse_datetime,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, Source

logger = logging.getLogger("jobagg.collectors.jobvite")

FEED_URL = "https://api.jobvite.com/api/v2/job"


class JobviteCollector(BaseCollector):
    name = Source.JOBVITE.value
    display_name = "Jobvite"

    def _entries(self) -> list[dict]:
        entries: list[dict] = []
        for entry in load_board_entries(self.settings, self.name):
            api = entry.get("api") or entry.get("api_key") or entry.get("token")
            secret = entry.get("sc") or entry.get("secret")
            if api and secret:
                entries.append({"api": str(api), "sc": str(secret), "site": entry.get("site")})
        return entries

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        entries = self._entries()
        if not entries:
            logger.info("jobvite: no accounts with api/sc configured, skipping")
            return

        async with self._client() as client:
            for entry in entries:
                try:
                    response = await client.get(
                        FEED_URL, params={"api": entry["api"], "sc": entry["sc"]}
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("jobvite: %s failed: %s", entry.get("site"), exc)
                    continue

                jobs = payload.get("jobs") if isinstance(payload, dict) else payload
                for raw in jobs or []:
                    job = self._parse(entry, raw)
                    if job is not None:
                        yield job

    def _parse(self, entry: dict, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id") or raw.get("jobId") or raw.get("eId")
        title = (raw.get("title") or raw.get("jobTitle") or "").strip()
        if not job_id or not title:
            return None

        site = entry.get("site")
        url = raw.get("applyUrl") or raw.get("detailUrl")
        if not url and site:
            url = f"https://jobs.jobvite.com/{site}/job/{job_id}/apply"

        city = raw.get("city")
        state = raw.get("state")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=raw.get("company") or (site.replace("-", " ").title() if site else "Jobvite"),
            description=trim(
                strip_html(raw.get("description") or raw.get("jobDescription"))
            ),
            country=country_from_name(raw.get("country")) or country_from_name(
                raw.get("countryCode")
            ),
            state=state,
            city=city,
            employment_type=normalize_employment_type(
                raw.get("jobType") or raw.get("employmentType")
            ),
            posted_at=parse_datetime(raw.get("datePosted") or raw.get("datePostedUtc")),
            raw_payload=raw,
        )
