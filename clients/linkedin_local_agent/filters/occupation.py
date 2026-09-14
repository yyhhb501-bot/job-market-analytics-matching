"""Title/occupation filtering driven by config-defined exclusion terms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from clients.linkedin_local_agent.models import normalize


@dataclass(slots=True)
class TitleFilter:
    """Reject obvious off-target titles (e.g. ``Financial Analyst``)."""

    exclusions: list[str] = field(default_factory=list)
    _patterns: list[re.Pattern] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._patterns = [
            re.compile(rf"\b{re.escape(normalize(term))}\b")
            for term in self.exclusions
            if normalize(term)
        ]

    def excluded(self, title: str) -> bool:
        haystack = normalize(title)
        return any(pattern.search(haystack) for pattern in self._patterns)


__all__ = ["TitleFilter"]
