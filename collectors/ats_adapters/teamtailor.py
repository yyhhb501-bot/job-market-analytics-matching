"""Teamtailor adapter (per-company API token).

Teamtailor's public job-board API needs an API token, so each config entry must
provide one::

    {"token": "acme", "api_token": "...", "api_version": "20240404"}

Entries without ``api_token`` are skipped. API docs:
https://docs.teamtailor.com/
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

logger = logging.getLogger("jobagg.collectors.teamtailor")

BASE_URL = "https://api.teamtailor.com/v1/jobs"
DEFAULT_API_VERSION = "20240404"


def _remote_type(value: str | None) -> str | None:
    if not value:
        return None
    text = value.lower()
    if "remote" in text and "no" not in text and "not" not in text:
        return RemoteType.REMOTE.value
    if "hybrid" in text:
        return RemoteType.HYBRID.value
    return None


class TeamtailorCollector(BaseCollector):
    name = Source.TEAMTAILOR.value
    display_name = "Teamtailor"

    def _entries(self) -> list[dict]:
        return [
            entry
            for entry in load_board_entries(self.settings, self.name)
            if entry.get("api_token")
        ]

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        entries = self._entries()
        if not entries:
            logger.info("teamtailor: no boards with api_token configured, skipping")
            return

        async with self._client() as client:
            for entry in entries:
                token = str(entry.get("token") or "teamtailor")
                headers = {
                    "Authorization": f"Token token={entry['api_token']}",
                    "X-Api-Version": str(entry.get("api_version") or DEFAULT_API_VERSION),
                    "Accept": "application/vnd.api+json",
                }
                collected = 0
                url: str | None = BASE_URL
                first = True
                while url and collected < params.results_wanted:
                    if not await self._pre_request():
                        return
                    try:
                        payload = await self._board_json(
                            client,
                            url,
                            board=token,
                            headers=headers,
                            params={"page[size]": 30} if first else None,
                        )
                    except (RateLimitedError, AccessBlockedError):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        self._note_board_failure(token, exc)
                        logger.warning("teamtailor: %s failed: %s", token, exc)
                        break
                    first = False
                    for item in payload.get("data") or []:
                        job = self._parse(token, item)
                        if job is not None:
                            yield job
                            collected += 1
                            if collected >= params.results_wanted:
                                self._note_board_incomplete(token)
                                break
                    url = (payload.get("links") or {}).get("next")
                    await asyncio.sleep(0.2)

    def _parse(self, token: str, item: dict) -> NormalizedJob | None:
        attributes = item.get("attributes") or {}
        job_id = item.get("id")
        title = (attributes.get("title") or "").strip()
        if not job_id or not title:
            return None

        city = attributes.get("city")
        country = country_from_name(attributes.get("country-code")) or infer_country(city)
        url = attributes.get("careersite-job-url")
        body = attributes.get("body")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=token.replace("-", " ").title(),
            description=trim(strip_html(body)),
            country=country,
            state=attributes.get("region") or attributes.get("state"),
            city=city,
            remote_type=_remote_type(attributes.get("remote-status")),
            employment_type=normalize_employment_type(
                attributes.get("employment-type") or attributes.get("employment_type")
            ),
            posted_at=parse_datetime(attributes.get("created-at")),
            raw_payload=attributes,
        )
