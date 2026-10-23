"""Personio public XML feed adapter.

Feed: ``https://{company}.jobs.personio.de/xml`` (or ``.com`` for
international boards; override with a ``domain`` field on the config entry).
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from xml.etree.ElementTree import Element

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
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.personio")

DEFAULT_DOMAIN = "jobs.personio.de"


def _text(element: Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


class PersonioCollector(BaseCollector):
    name = Source.PERSONIO.value
    display_name = "Personio"

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
            logger.info("personio: no boards configured, skipping")
            return

        async with self._client() as client:
            for token, domain in entries:
                if not await self._pre_request():
                    return
                try:
                    response = await client.get(f"https://{token}.{domain}/xml")
                    self._raise_for_status(response)
                    root = ET.fromstring(response.content)
                    self.board_outcomes[token] = True
                    self.complete_boards.add(token)
                except (RateLimitedError, AccessBlockedError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._note_board_failure(token, exc)
                    logger.warning("personio: %s failed: %s", token, exc)
                    continue
                for position in root.findall("position"):
                    job = self._parse(token, domain, position)
                    if job is not None:
                        yield job
                await asyncio.sleep(0.2)

    def _parse(self, token: str, domain: str, position: Element) -> NormalizedJob | None:
        job_id = _text(position, "id")
        title = _text(position, "name")
        if not job_id or not title:
            return None

        office = _text(position, "office") or _text(position, "subcompany")
        descriptions = [
            value.text
            for value in position.findall("jobDescriptions/jobDescription/value")
            if value.text
        ]
        url = f"https://{token}.{domain}/job/{job_id}"
        employment = _text(position, "schedule") or _text(position, "employmentType")

        raw_payload = {
            key: position.findtext(key)
            for key in (
                "id",
                "name",
                "subcompany",
                "office",
                "department",
                "employmentType",
                "schedule",
                "seniority",
                "createdAt",
            )
        }
        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=_text(position, "subcompany") or token.replace("-", " ").title(),
            description=trim(strip_html("\n".join(descriptions))),
            country=infer_country(office),
            city=office,
            remote_type=RemoteType.REMOTE.value
            if office and "remote" in office.lower()
            else None,
            employment_type=normalize_employment_type(employment),
            posted_at=parse_datetime(_text(position, "createdAt")),
            raw_payload=raw_payload,
        )
