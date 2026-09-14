"""Page-offset planning for LinkedIn search result pages."""

from __future__ import annotations

from collections.abc import Iterator

from clients.linkedin_local_agent.search.query_builder import Query


def iter_start_offsets(results_per_page: int, max_pages: int) -> Iterator[int]:
    """Yield ``start`` offsets for a bounded number of result pages."""
    page_size = max(int(results_per_page), 1)
    for page in range(max(int(max_pages), 0)):
        yield page * page_size


def page_key(query: Query, start: int) -> str:
    """Stable checkpoint key for one (query, page)."""
    return (
        f"{query.channel}|{query.occupation_group or ''}|{query.keyword}|"
        f"{query.geo_id}|{start}"
    )


def is_last_page(stub_count: int, results_per_page: int) -> bool:
    """A short page means LinkedIn has no more results for this query."""
    return stub_count < max(int(results_per_page), 1)


__all__ = ["is_last_page", "iter_start_offsets", "page_key"]
