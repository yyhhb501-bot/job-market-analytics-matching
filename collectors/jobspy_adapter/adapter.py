"""Adapter around the ``python-jobspy`` library.

Contains no scraping logic of its own; it only maps JobSpy's DataFrame into the
platform's :class:`NormalizedJob`. Disabled by default (``ENABLE_JOBSPY``) so a
rate-limit on one aggregator cannot affect the whole pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from collectors.base import BaseCollector, CollectorError, SearchParams
from collectors.utils import parse_salary_number, split_location, trim
from packages.job_schema import NormalizedJob, Source

logger = logging.getLogger("jobagg.collectors.jobspy")

SITE_SOURCE = {
    "indeed": Source.INDEED.value,
    "glassdoor": Source.GLASSDOOR.value,
    "google": Source.GOOGLE.value,
    "linkedin": Source.LINKEDIN.value,
    "zip_recruiter": Source.ZIPRECRUITER.value,
    "bayt": "bayt",
}

COUNTRY_INDEED = {
    "US": "USA",
    "AU": "australia",
    "CA": "canada",
    "GB": "uk",
    "NZ": "new zealand",
}

_INTERVAL_PERIOD = {
    "yearly": "year",
    "monthly": "month",
    "weekly": "week",
    "daily": "day",
    "hourly": "hour",
}


class JobSpyCollector(BaseCollector):
    name = "jobspy"
    display_name = "JobSpy (Indeed/Glassdoor/Google)"

    def _sites(self, params: SearchParams) -> list[str]:
        sites = params.extra.get("sites")
        if sites:
            return [site.strip().lower() for site in sites]
        return ["indeed", "glassdoor", "google"]

    async def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        try:
            import pandas as pd
            from jobspy import scrape_jobs
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise CollectorError("python-jobspy / pandas is not installed") from exc

        sites = self._sites(params)
        country = params.country_code or "US"

        def _run():
            return scrape_jobs(
                site_name=sites,
                search_term=params.keywords or "",
                location=params.location or "",
                results_wanted=params.results_wanted,
                country_indeed=COUNTRY_INDEED.get(country, "USA"),
                linkedin_fetch_description=False,
                description_format="markdown",
                enforce_annual_salary=True,
                verbose=0,
            )

        try:
            frame = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("jobspy: scrape failed: %s", exc)
            return

        if frame is None or frame.empty:
            return

        for _, row in frame.iterrows():
            job = self._parse(pd, row, country)
            if job is not None:
                yield job

    def _parse(self, pd, row, country: str) -> NormalizedJob | None:
        def value(key):
            if key not in row:
                return None
            candidate = row[key]
            try:
                if pd.isna(candidate):
                    return None
            except (TypeError, ValueError):
                pass
            return candidate

        title = str(value("title") or "").strip()
        job_id = value("id")
        url = value("job_url") or value("job_url_direct")
        if not title or (job_id is None and not url):
            return None
        site = str(value("site") or "indeed").lower()
        source = SITE_SOURCE.get(site, site)

        location = value("location")
        city, state = split_location(str(location) if location else None)

        interval = str(value("interval") or "").lower()
        remote = value("is_remote")
        return NormalizedJob(
            source=source,
            source_job_id=str(job_id) if job_id is not None else str(url),
            title=title,
            canonical_url=str(url) if url else None,
            apply_url=str(value("job_url_direct") or url) if url else None,
            company=str(value("company")) if value("company") else None,
            description=trim(str(value("description")) if value("description") else None),
            country=country,
            state=state,
            city=city,
            remote_type="remote" if remote is True else None,
            employment_type=str(value("job_type")).lower() if value("job_type") else None,
            salary_min=parse_salary_number(value("min_amount")),
            salary_max=parse_salary_number(value("max_amount")),
            salary_currency=str(value("currency")) if value("currency") else None,
            salary_period=_INTERVAL_PERIOD.get(interval),
            posted_at=value("date_posted"),
            raw_payload={k: (None if value(k) is None else str(value(k))) for k in (
                "id", "site", "job_url", "company", "location", "date_posted"
            )},
        )
