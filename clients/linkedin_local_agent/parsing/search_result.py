"""Parse LinkedIn job *search result* HTML into lightweight :class:`JobStub`s.

We deliberately avoid opening detail pages here: search cards carry most of the
metadata needed to pre-filter (title, company, location), and only survivors
are fetched individually.
"""

from __future__ import annotations

import re

from clients.linkedin_local_agent.models import JobStub
from clients.linkedin_local_agent.parsing._html import first_group, strip_tags

_URN = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"', re.IGNORECASE)
_JOB_VIEW_ID = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})")
# Matches either attribute order of the title heading used across layouts.
_TITLE = re.compile(
    r'class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>', re.IGNORECASE | re.DOTALL
)
_COMPANY = re.compile(
    r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</h4>', re.IGNORECASE | re.DOTALL
)
_LOCATION = re.compile(
    r'class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL
)
_LINK = re.compile(
    r'href="(https://[a-z.]*linkedin\.com/jobs/view/[^"]+)"', re.IGNORECASE
)


def _card_slices(page_html: str) -> list[tuple[str, str]]:
    """Split the page into ``(job_id, card_html)`` pairs."""
    matches = list(_URN.finditer(page_html))
    cards: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        # The urn is on the card wrapper; its title/company/link children follow.
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        cards.append((match.group(1), page_html[match.start():end]))
    return cards


def _job_id_from_link(link: str | None) -> str | None:
    if not link:
        return None
    match = _JOB_VIEW_ID.search(link)
    return match.group(1) if match else None


def parse_search_results(page_html: str) -> list[JobStub]:
    """Extract job stubs from a search results page, preserving page order."""
    stubs: list[JobStub] = []
    seen: set[str] = set()
    for job_id, card in _card_slices(page_html):
        link = first_group(_LINK.pattern, card)
        resolved_id = job_id or _job_id_from_link(link)
        if not resolved_id or resolved_id in seen:
            continue
        title = strip_tags(first_group(_TITLE.pattern, card))
        if not title:
            continue
        seen.add(resolved_id)
        stubs.append(
            JobStub(
                job_id=resolved_id,
                title=title,
                company=strip_tags(first_group(_COMPANY.pattern, card)),
                location=strip_tags(first_group(_LOCATION.pattern, card)),
                url=link or f"https://www.linkedin.com/jobs/view/{resolved_id}",
            )
        )
    return stubs


__all__ = ["parse_search_results"]
