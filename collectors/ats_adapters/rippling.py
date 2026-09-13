"""Rippling ATS public board adapter.

List:   ``https://ats.rippling.com/api/v2/board/{board}/jobs``
Detail: ``https://ats.rippling.com/api/v2/board/{board}/jobs/{id}``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.ats_adapters.config import load_board_tokens
from collectors.base import BaseCollector, SearchParams
from collectors.utils import country_from_name, parse_datetime, strip_html, trim
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.rippling")

LIST_URL = "https://ats.rippling.com/api/v2/board/{board}/jobs"
DETAIL_URL = "https://ats.rippling.com/api/v2/board/{board}/jobs/{job_id}"
PAGE_SIZE = 20

_WORKPLACE = {
    "remote": RemoteType.REMOTE.value,
    "hybrid": RemoteType.HYBRID.value,
    "onsite": RemoteType.ONSITE.value,
}


def _employment_type(value: str | None) -> str | None:
    text = (value or "").lower()
    if "part" in text:
        return "part_time"
    if "contract" in text or "temporary" in text:
        return "contract"
    if "intern" in text:
        return "internship"
    if "full" in text or "salaried" in text or text.endswith("ft"):
        return "full_time"
    return None


class RipplingCollector(BaseCollector):
    name = Source.RIPPLING.value
    display_name = "Rippling"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        boards = load_board_tokens(self.settings, self.name)
        if not boards:
            logger.info("rippling: no boards configured, skipping")
            return

        async with self._client() as client:
            for board in boards:
                collected = 0
                page = 0
                while collected < params.results_wanted:
                    try:
                        response = await client.get(
                            LIST_URL.format(board=board),
                            params={"page": page, "pageSize": PAGE_SIZE},
                        )
                        response.raise_for_status()
                        payload = response.json()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("rippling: %s failed: %s", board, exc)
                        break

                    items = payload.get("items") or []
                    if not items:
                        break
                    for raw in items:
                        detail = await self._fetch_detail(client, board, raw.get("id"))
                        job = self._parse(board, raw, detail)
                        if job is not None:
                            yield job
                            collected += 1
                            if collected >= params.results_wanted:
                                break
                    page += 1
                    if page >= int(payload.get("totalPages") or 0):
                        break
                    await asyncio.sleep(0.2)

    async def _fetch_detail(self, client, board: str, job_id) -> dict | None:
        if not job_id:
            return None
        try:
            response = await client.get(DETAIL_URL.format(board=board, job_id=job_id))
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("rippling: detail %s failed: %s", job_id, exc)
            return None

    def _parse(self, board: str, raw: dict, detail: dict | None) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("name") or "").strip()
        if not job_id or not title:
            return None

        locations = raw.get("locations") or []
        location = locations[0] if locations else {}
        info = detail or {}
        description = info.get("description") or {}

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=raw.get("url"),
            apply_url=raw.get("url"),
            company=info.get("companyName") or board.replace("-", " ").title(),
            description=trim(
                strip_html(
                    "\n".join(
                        part
                        for part in (description.get("company"), description.get("role"))
                        if part
                    )
                )
            ),
            country=country_from_name(location.get("countryCode") or location.get("country")),
            state=location.get("stateCode") or location.get("state"),
            city=location.get("city"),
            remote_type=_WORKPLACE.get(str(location.get("workplaceType") or "").lower()),
            employment_type=_employment_type(
                (info.get("employmentType") or {}).get("id")
                or (info.get("employmentType") or {}).get("label")
            ),
            posted_at=parse_datetime(info.get("createdOn")),
            raw_payload=raw,
        )
