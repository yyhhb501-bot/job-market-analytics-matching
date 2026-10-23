"""Adzuna Search API adapter.

Covers the US and Australia (and any other Adzuna market) with one structured,
official API. Enabled with ``ENABLE_ADZUNA=true`` plus ``ADZUNA_APP_ID`` /
``ADZUNA_APP_KEY``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.base import (
    AccessBlockedError,
    BaseCollector,
    CollectorError,
    RateLimitedError,
    SearchParams,
)
from collectors.utils import parse_datetime, parse_salary_number, strip_html, trim
from packages.job_schema import NormalizedJob, Source
from packages.seek_policy import title_in_scope

logger = logging.getLogger("jobagg.collectors.adzuna")

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 20
CURRENCY_BY_COUNTRY = {"US": "USD", "AU": "AUD", "GB": "GBP", "CA": "CAD", "NZ": "NZD"}

_CONTRACT_TIME = {"full_time": "full_time", "part_time": "part_time"}
_CONTRACT_TYPE = {"contract": "contract", "temporary": "temporary", "permanent": "other"}


class AdzunaCollector(BaseCollector):
    name = Source.ADZUNA.value
    display_name = "Adzuna"
    requires_credentials = True

    def validate(self) -> None:
        missing = []
        if not self.settings.adzuna_app_id:
            missing.append("ADZUNA_APP_ID")
        if not self.settings.adzuna_app_key:
            missing.append("ADZUNA_APP_KEY")
        if missing:
            raise CollectorError(f"Adzuna requires {', '.join(missing)}")

    def _countries(self, params: SearchParams) -> list[str]:
        if params.country:
            return [params.country.upper()]
        return self.settings.country_list or ["US", "AU"]

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        self.validate()
        for country in self._countries(params):
            collected = 0
            page = 1
            async with self._client() as client:
                while collected < params.results_wanted and page <= MAX_PAGES:
                    query = {
                        "app_id": self.settings.adzuna_app_id,
                        "app_key": self.settings.adzuna_app_key,
                        "results_per_page": min(RESULTS_PER_PAGE, params.results_wanted - collected),
                        "content-type": "application/json",
                        "sort_by": "date",
                    }
                    if params.keywords:
                        query["what"] = params.keywords
                    if params.location:
                        query["where"] = params.location
                    if not await self._pre_request():
                        return
                    try:
                        response = await client.get(
                            BASE_URL.format(country=country.lower(), page=page), params=query
                        )
                        self._raise_for_status(response)
                        payload = response.json()
                    except (RateLimitedError, AccessBlockedError):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("adzuna: %s page %s failed: %s", country, page, exc)
                        break

                    results = payload.get("results") or []
                    if not results:
                        break
                    for raw in results:
                        job = self._parse(country, raw)
                        if job is not None and (
                            not params.extra.get("nurse_only") or title_in_scope(job.title)
                        ):
                            yield job
                            collected += 1
                            if collected >= params.results_wanted:
                                break
                    page += 1
                    await asyncio.sleep(0.2)

    def _parse(self, country: str, raw: dict) -> NormalizedJob | None:
        job_id = raw.get("id")
        title = (raw.get("title") or "").strip()
        if not job_id or not title:
            return None

        location = raw.get("location") or {}
        area = [part for part in (location.get("area") or []) if part]
        city = area[-1] if area else None
        state = area[-2] if len(area) >= 2 else None

        salary_min = parse_salary_number(raw.get("salary_min"))
        salary_max = parse_salary_number(raw.get("salary_max"))
        has_salary = salary_min is not None or salary_max is not None

        employment_type = _CONTRACT_TIME.get((raw.get("contract_time") or "").lower())
        if employment_type is None:
            employment_type = _CONTRACT_TYPE.get((raw.get("contract_type") or "").lower())

        url = raw.get("redirect_url")
        return NormalizedJob(
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            canonical_url=url,
            apply_url=url,
            company=(raw.get("company") or {}).get("display_name"),
            description=trim(strip_html(raw.get("description"))),
            country=country.upper(),
            state=state,
            city=city,
            employment_type=employment_type,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=CURRENCY_BY_COUNTRY.get(country.upper()) if has_salary else None,
            salary_period="year" if has_salary else None,
            posted_at=parse_datetime(raw.get("created")),
            raw_payload=raw,
        )
