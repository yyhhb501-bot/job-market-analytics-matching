"""Turn occupation groups + locations into concrete LinkedIn search queries.

Each run covers two channels per (keyword, area):

* **local**  — keyword + a city/state ``geoId`` (onsite/hybrid roles), and
* **remote** — keyword + a *country* ``geoId`` with ``f_WT=2`` (remote roles).

Results are merged and deduplicated later; this mirrors the proven strategy of
the reference collector instead of a single ``keyword + city`` search.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from clients.linkedin_local_agent.config import AgentConfig, SearchConfig

SEARCH_URL = "https://www.linkedin.com/jobs/search/"
REMOTE_WORKPLACE_FILTER = "2"  # f_WT=2 -> Remote


@dataclass(slots=True)
class Query:
    keyword: str
    geo_id: str
    channel: str  # "local" | "remote"
    country: str
    state: str | None = None
    city: str | None = None
    occupation_group: str | None = None

    @property
    def label(self) -> str:
        area = ", ".join(part for part in (self.city, self.state, self.country) if part)
        return f"[{self.channel}] {self.keyword} @ {area}"


def build_search_url(query: Query, start: int, search: SearchConfig) -> str:
    """Build a LinkedIn jobs search URL for one page (``start`` is an offset)."""
    params: dict[str, str] = {
        "keywords": query.keyword,
        "geoId": query.geo_id,
        "start": str(max(start, 0)),
        "sortBy": "DD",  # newest first
    }
    if search.date_posted_seconds > 0:
        params["f_TPR"] = f"r{int(search.date_posted_seconds)}"
    if query.channel == "remote":
        params["f_WT"] = REMOTE_WORKPLACE_FILTER
    else:
        params["distance"] = str(max(int(search.distance_miles), 0))
    return f"{SEARCH_URL}?{urlencode(params)}"


def build_queries(config: AgentConfig) -> list[Query]:
    """Expand the config into the city + remote query matrix, capped by config."""
    queries: list[Query] = []
    max_keywords = 8

    for group in config.occupation_groups:
        keywords = group.keywords()[:max_keywords]
        for keyword in keywords:
            for center in config.centers:
                queries.append(
                    Query(
                        keyword=keyword,
                        geo_id=center.geo_id,
                        channel="local",
                        country=center.country,
                        state=center.state,
                        city=center.city,
                        occupation_group=group.name,
                    )
                )
            for country in config.countries:
                queries.append(
                    Query(
                        keyword=keyword,
                        geo_id=country.geo_id,
                        channel="remote",
                        country=country.country,
                        occupation_group=group.name,
                    )
                )

    if config.search.max_queries > 0:
        queries = queries[: config.search.max_queries]
    return queries


__all__ = ["Query", "build_queries", "build_search_url"]
