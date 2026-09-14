"""Location filtering.

Imported rows are only marked as *seen* after they pass this filter, so a job
that is dropped today (wrong city) can still be picked up later if it is
re-posted as remote or the user's targets change.
"""

from __future__ import annotations

from dataclasses import dataclass

from clients.linkedin_local_agent.models import CollectedJob, JobStub, normalize

_COUNTRY_ALIASES: dict[str, set[str]] = {
    "US": {"us", "usa", "united states", "united states of america"},
    "AU": {"au", "australia"},
}


def is_remote_text(text: str | None) -> bool:
    return "remote" in normalize(text)


def detect_country(normalized_text: str) -> str | None:
    """Best-effort ISO country code from a normalised location string."""
    tokens = set(normalized_text.split())
    for code, aliases in _COUNTRY_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize(alias)
            if " " in normalized_alias:
                if normalized_alias in normalized_text:
                    return code
            elif normalized_alias in tokens:
                return code
    return None


@dataclass(slots=True)
class LocationFilter:
    """Accept/reject rules for one query channel."""

    country: str
    state: str | None = None
    city: str | None = None
    channel: str = "local"

    def _haystack(self, stub: JobStub, collected: CollectedJob | None) -> str:
        return " ".join(
            part
            for part in (
                stub.location,
                collected.city if collected else None,
                collected.state if collected else None,
                collected.country if collected else None,
            )
            if part
        )

    def accepts(self, stub: JobStub, collected: CollectedJob | None = None) -> bool:
        if self.channel == "remote":
            # ``f_WT=2`` already restricted the search; only guard the country.
            return True

        normalized = normalize(self._haystack(stub, collected))
        if not normalized:
            return False

        # Reject remote roles leaking into a city (onsite/hybrid) search.
        if "remote" in normalized and "hybrid" not in normalized:
            return False

        found_country = detect_country(normalized)
        if found_country and self.country and found_country != self.country.upper():
            return False

        if self.city:
            return normalize(self.city) in normalized
        if self.state:
            return normalize(self.state) in normalized
        return True


__all__ = ["LocationFilter", "detect_country", "is_remote_text"]
