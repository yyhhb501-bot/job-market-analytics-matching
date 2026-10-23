"""SmartRecruiters public postings adapter.

List:   ``https://api.smartrecruiters.com/v1/companies/{company}/postings``
Detail: ``https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}``

The list response has no description, so we fetch the detail for each posting
we actually keep (bounded by ``results_wanted``) to keep cross-source
deduplication accurate.
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
from collectors.utils import (
    country_from_name,
    normalize_employment_type,
    parse_datetime,
    strip_html,
    trim,
)
from packages.job_schema import NormalizedJob, RemoteType, Source

logger = logging.getLogger("jobagg.collectors.smartrecruiters")

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
PAGE_SIZE = 100


class SmartRecruitersCollector(BaseCollector):
    name = Source.SMARTRECRUITERS.value
    display_name = "SmartRecruiters"

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        companies = load_board_tokens(self.settings, self.name)
        if not companies:
            logger.info("smartrecruiters: no companies configured, skipping")
            return

        async with self._client() as client:
            for company in companies:
                collected = 0
                offset = 0
                while collected < params.results_wanted:
                    limit = min(PAGE_SIZE, params.results_wanted - collected)
                    if not await self._pre_request():
                        return
                    try:
                        payload = await self._board_json(
                            client,
                            LIST_URL.format(company=company),
                            board=company,
                            params={"limit": limit, "offset": offset},
                        )
                    except (RateLimitedError, AccessBlockedError):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        self._note_board_failure(company, exc)
                        logger.warning("smartrecruiters: %s failed: %s", company, exc)
                        break

                    content = payload.get("content") or []
                    if not content:
                        break
                    for raw in content:
                        detail = await self._fetch_detail(client, company, raw)
                        job = self._parse(company, raw, detail)
                        if job is not None:
                            yield job
                            collected += 1
                            if collected >= params.results_wanted:
                                self._note_board_incomplete(company)
                                break
                    offset += len(content)
                    if len(content) < limit:
                        break
                    await asyncio.sleep(0.2)

    async def _fetch_detail(self, client, company: str, raw: dict) -> dict | None:
        posting_id = raw.get("id")
        if not posting_id:
            return None
        if not await self._note_detail():
            return None
        try:
            response = await client.get(
                DETAIL_URL.format(company=company, posting_id=posting_id)
            )
            self._raise_for_status(response)
            return response.json()
        except (RateLimitedError, AccessBlockedError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("smartrecruiters: detail %s/%s failed: %s", company, posting_id, exc)
            return None

    def _parse(self, company: str, raw: dict, detail: dict | None = None) -> NormalizedJob | None:
        job_id = raw.get("id") or raw.get("uuid")
        title = (raw.get("name") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location") or {}
        country = country_from_name(location.get("country")) or country_from_name(
            location.get("countryCode")
        )
        remote_type = RemoteType.REMOTE.value if location.get("remote") else None

        description = None
        if detail:
            sections = (detail.get("jobAd") or {}).get("sections") or {}
            parts = [
                (sections.get(key) or {}).get("text")
                for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
            ]
            description = strip_html("\n".join(part for part in parts if part))

        employment = normalize_employment_type(
            (raw.get("typeOfEmployment") or {}).get("label")
        )
        url = raw.get("postingUrl") or f"https://jobs.smartrecruiters.com/{company}/{job_id}"

        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=(raw.get("company") or {}).get("name") or company.replace("-", " ").title(),
            description=trim(description),
            country=country,
            state=location.get("region"),
            city=location.get("city"),
            remote_type=remote_type,
            employment_type=employment,
            posted_at=parse_datetime(raw.get("releasedDate")),
            raw_payload=raw,
        )
