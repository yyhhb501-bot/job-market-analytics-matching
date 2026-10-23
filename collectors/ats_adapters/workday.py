"""Workday career-site adapter.

List (POST): ``https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs``
Detail (GET): ``...{externalPath}``

Workday is per-company: configure entries as
``{"tenant": "...", "host": "wd5", "site": "..."}`` in ``ats_companies.json``.
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
    infer_country,
    normalize_employment_type,
    parse_datetime,
    split_location,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.workday")

PAGE_SIZE = 20


def _remote_type(value: str | None) -> str | None:
    if not value:
        return None
    text = value.lower()
    if "remote" in text:
        return RemoteType.REMOTE.value
    if "hybrid" in text:
        return RemoteType.HYBRID.value
    if "on-site" in text or "onsite" in text:
        return RemoteType.ONSITE.value
    return None


class WorkdayCollector(BaseCollector):
    name = Source.WORKDAY.value
    display_name = "Workday"

    def _entries(self) -> list[dict]:
        return [
            entry
            for entry in load_board_entries(self.settings, self.name)
            if entry.get("tenant") and entry.get("site")
        ]

    @staticmethod
    def _base(tenant: str, host: str, site: str) -> str:
        return f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        entries = self._entries()
        if not entries:
            logger.info("workday: no boards configured, skipping")
            return

        async with self._client() as client:
            for entry in entries:
                tenant = str(entry["tenant"])
                host = str(entry.get("host") or "wd1")
                site = str(entry["site"])
                base = self._base(tenant, host, site)
                collected = 0
                offset = 0
                while collected < params.results_wanted:
                    body = {
                        "appliedFacets": {},
                        "limit": PAGE_SIZE,
                        "offset": offset,
                        "searchText": params.keywords or "",
                    }
                    if not await self._pre_request():
                        return
                    try:
                        response = await client.post(f"{base}/jobs", json=body)
                        self._raise_for_status(response)
                        payload = response.json()
                        self.board_outcomes[site] = True
                        self.complete_boards.add(site)
                    except (RateLimitedError, AccessBlockedError):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        self._note_board_failure(site, exc)
                        logger.warning("workday: %s/%s failed: %s", tenant, site, exc)
                        break

                    postings = payload.get("jobPostings") or []
                    if not postings:
                        break
                    for raw in postings:
                        detail = await self._fetch_detail(client, base, raw.get("externalPath"))
                        job = self._parse(tenant, host, site, raw, detail)
                        if job is not None:
                            yield job
                            collected += 1
                            if collected >= params.results_wanted:
                                self._note_board_incomplete(site)
                                break
                    offset += PAGE_SIZE
                    if offset >= int(payload.get("total") or 0):
                        break
                    await asyncio.sleep(0.2)

    async def _fetch_detail(self, client, base: str, path: str | None) -> dict | None:
        if not path:
            return None
        if not await self._note_detail():
            return None
        try:
            response = await client.get(f"{base}{path}")
            self._raise_for_status(response)
            return response.json()
        except (RateLimitedError, AccessBlockedError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("workday: detail %s failed: %s", path, exc)
            return None

    def _parse(
        self, tenant: str, host: str, site: str, raw: dict, detail: dict | None
    ) -> NormalizedJob | None:
        path = raw.get("externalPath")
        info = (detail or {}).get("jobPostingInfo") or {}
        title = (info.get("title") or raw.get("title") or "").strip()
        job_id = info.get("jobReqId") or path or title
        if not title or not job_id:
            return None

        location = info.get("location") or raw.get("locationsText")
        city, state = split_location(location)
        url = (
            info.get("externalUrl")
            or f"https://{tenant}.{host}.myworkdayjobs.com/en-US/{site}{path or ''}"
        )
        remote_type = _remote_type(info.get("remoteType")) or _remote_type(location)

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=tenant.replace("-", " ").title(),
            description=trim(strip_html(info.get("jobDescription"))),
            country=infer_country(location),
            state=state,
            city=city,
            remote_type=remote_type,
            employment_type=normalize_employment_type(info.get("timeType")),
            posted_at=parse_datetime(info.get("startDate")),
            expires_at=parse_datetime(info.get("endDate")),
            raw_payload=raw,
        )
