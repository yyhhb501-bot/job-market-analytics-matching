"""Canonical job model shared by every collector.

Every adapter must emit :class:`NormalizedJob` so the rest of the pipeline
(persistence, deduplication, ranking, search) stays source-agnostic.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Source(StrEnum):
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    GOOGLE = "google"
    REMOTEOK = "remoteok"
    LINKEDIN = "linkedin"
    ZIPRECRUITER = "ziprecruiter"
    SEEK = "seek"
    USAJOBS = "usajobs"
    ADZUNA = "adzuna"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKABLE = "workable"
    SMARTRECRUITERS = "smartrecruiters"
    RECRUITEE = "recruitee"
    BREEZY = "breezy"
    WORKDAY = "workday"
    PERSONIO = "personio"
    TEAMTAILOR = "teamtailor"
    BAMBOOHR = "bamboohr"
    JAZZHR = "jazzhr"
    PINPOINT = "pinpoint"
    RIPPLING = "rippling"
    JOBVITE = "jobvite"


ATS_SOURCES: frozenset[str] = frozenset(
    {
        Source.GREENHOUSE.value,
        Source.LEVER.value,
        Source.ASHBY.value,
        Source.WORKABLE.value,
        Source.SMARTRECRUITERS.value,
        Source.RECRUITEE.value,
        Source.BREEZY.value,
        Source.WORKDAY.value,
        Source.PERSONIO.value,
        Source.TEAMTAILOR.value,
        Source.BAMBOOHR.value,
        Source.JAZZHR.value,
        Source.PINPOINT.value,
        Source.RIPPLING.value,
        Source.JOBVITE.value,
    }
)


class Country(StrEnum):
    US = "US"
    AU = "AU"


class RemoteType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Visibility(StrEnum):
    """Whether a job is part of the public market data or user-private import."""

    PUBLIC = "public"
    PRIVATE = "private"


class CollectionMode(StrEnum):
    """How a job entered the platform."""

    PLATFORM = "platform"
    USER_LOCAL = "user_local"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    CASUAL = "casual"
    OTHER = "other"


class SalaryPeriod(StrEnum):
    YEAR = "year"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"


class NormalizedJob(BaseModel):
    """A single job posting in the platform's unified shape."""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    source: str
    source_job_id: str
    title: str
    canonical_url: str | None = None
    company: str | None = None
    description: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    apply_url: str | None = None
    raw_payload: dict[str, Any] | None = Field(default=None)

    def best_url(self) -> str | None:
        return self.apply_url or self.canonical_url


__all__ = [
    "ATS_SOURCES",
    "CollectionMode",
    "Country",
    "EmploymentType",
    "NormalizedJob",
    "RemoteType",
    "SalaryPeriod",
    "Source",
    "Visibility",
]
