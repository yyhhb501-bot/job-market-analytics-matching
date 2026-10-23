"""JazzHR adapter (per-account API key).

List: ``https://api.resumatorapi.com/v1/jobs?apikey={key}``

Entries::

    {"api_key": "...", "board": "acme.applytojob.com"}

Docs: https://apidoc.jazzhrapis.com/
"""

from __future__ import annotations

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
from packages.job_schema import NormalizedJob, Source

logger = logging.getLogger("jobagg.collectors.jazzhr")

BASE_URL = "https://api.resumatorapi.com/v1/jobs"


class JazzHRCollector(BaseCollector):
    name = Source.JAZZHR.value
    display_name = "JazzHR"

    def _entries(self) -> list[dict]:
        entries = []
        for entry in load_board_entries(self.settings, self.name):
            api_key = entry.get("api_key") or entry.get("token")
            if api_key:
                entries.append({"api_key": str(api_key), "board": entry.get("board")})
        return entries

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        entries = self._entries()
        if not entries:
            logger.info("jazzhr: no accounts with api_key configured, skipping")
            return

        async with self._client() as client:
            for entry in entries:
                if not await self._pre_request():
                    return
                try:
                    payload = await self._board_json(
                        client,
                        BASE_URL,
                        board=str(entry.get("board") or entry["api_key"]),
                        params={"apikey": entry["api_key"]},
                    )
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(str(entry.get("board") or entry["api_key"]), exc)
                    logger.warning("jazzhr: %s failed: %s", entry.get("board"), exc)
                    continue
                for raw in payload if isinstance(payload, list) else []:
                    job = self._parse(entry, raw)
                    if job is not None:
                        yield job

    def _parse(self, entry: dict, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id") or raw.get("job_id")
        title = (raw.get("title") or raw.get("job_title") or "").strip()
        if not job_id or not title:
            return None

        board = entry.get("board")
        board_code = raw.get("board_code")
        url = raw.get("apply_url") or raw.get("url")
        if not url and board and board_code:
            url = f"https://{board}/apply/{board_code}"

        city = raw.get("city")
        state = raw.get("state")
        country = country_from_name(raw.get("country_id")) or infer_country(f"{city or ''} {state or ''}")
        company = raw.get("company") or (board.split(".")[0].replace("-", " ").title() if board else "JazzHR")

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=company,
            description=trim(strip_html(raw.get("description") or raw.get("job_description"))),
            country=country,
            state=state,
            city=city,
            employment_type=normalize_employment_type(
                raw.get("employment_type") or raw.get("type")
            ),
            posted_at=parse_datetime(raw.get("original_open_date") or raw.get("open_date")),
            raw_payload=raw,
        )
