"""Data shapes exchanged inside the local collector."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]")


def normalize(value: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace (dedup helper)."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = _NON_WORD.sub(" ", text.lower())
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(slots=True)
class JobStub:
    """Basic info parsed from a LinkedIn search card (no detail page opened)."""

    job_id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    geo_id: str | None = None
    channel: str = "local"  # local | remote

    @property
    def id_key(self) -> str:
        return f"job_id:{self.job_id}"

    @property
    def title_company_key(self) -> str:
        return f"tc:{normalize(self.title)}|{normalize(self.company)}"

    def dedup_keys(self) -> tuple[str, str]:
        return (self.id_key, self.title_company_key)


@dataclass(slots=True)
class CollectedJob:
    """A job enriched with its full description, ready to upload."""

    stub: JobStub
    description: str | None = None
    apply_url: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    posted_at: dt.datetime | None = None
    collected_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def to_payload(self, source: str = "linkedin_user_import") -> dict:
        return {
            "source": source,
            "source_job_id": self.stub.job_id,
            "title": self.stub.title,
            "company": self.stub.company or None,
            "description": self.description,
            "country": self.country,
            "state": self.state,
            "city": self.city,
            "remote_type": self.remote_type,
            "employment_type": self.employment_type,
            "canonical_url": self.stub.url or None,
            "apply_url": self.apply_url,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "collected_at": self.collected_at.isoformat(),
            "raw_payload": {
                "linkedin_geo_id": self.stub.geo_id,
                "channel": self.stub.channel,
                "search_location": self.stub.location,
            },
        }


__all__ = ["CollectedJob", "JobStub", "normalize"]
