"""Configuration for the local LinkedIn collector.

The config is plain JSON (see ``config.example.json``) so the client has no
extra dependencies. The device token is read from an environment variable by
default so it never has to be written into the config file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DEVICE_TOKEN_ENV = "JOBAGG_DEVICE_TOKEN"
DEFAULT_API_BASE_URL = "http://localhost:8010"
DEFAULT_SOURCE = "linkedin_user_import"


@dataclass(slots=True)
class BrowserConfig:
    profile_dir: str = "~/.jobagg/linkedin-profile"
    headless: bool = False
    page_load_timeout: int = 45
    challenge_timeout: int = 600
    window_size: str = "1400,1000"

    @property
    def resolved_profile_dir(self) -> Path:
        return Path(self.profile_dir).expanduser()


@dataclass(slots=True)
class SearchConfig:
    date_posted_seconds: int = 604800  # f_TPR: last 7 days
    distance_miles: int = 25  # f_Distance for local (city) searches
    results_per_page: int = 25
    max_pages_per_query: int = 3
    delay_seconds: float = 3.0
    delay_jitter_seconds: float = 2.0
    max_detail_fetches: int = 150
    max_queries: int = 40


@dataclass(slots=True)
class LocationCenter:
    country: str
    geo_id: str
    city: str | None = None
    state: str | None = None
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CountryTarget:
    country: str
    geo_id: str
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OccupationGroup:
    name: str
    primary: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)

    def keywords(self, max_primary: int = 4, max_secondary: int = 4) -> list[str]:
        """Primary terms first, then a bounded number of secondary synonyms."""
        chosen: list[str] = []
        for term in [*self.primary[:max_primary], *self.secondary[:max_secondary]]:
            cleaned = term.strip()
            if cleaned and cleaned not in chosen:
                chosen.append(cleaned)
        return chosen


@dataclass(slots=True)
class StorageConfig:
    data_dir: str = "~/.jobagg/linkedin-collector"

    @property
    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).expanduser()


@dataclass(slots=True)
class AgentConfig:
    api_base_url: str = DEFAULT_API_BASE_URL
    source: str = DEFAULT_SOURCE
    device_token: str | None = None
    device_token_env: str = DEFAULT_DEVICE_TOKEN_ENV
    occupation_groups: list[OccupationGroup] = field(default_factory=list)
    centers: list[LocationCenter] = field(default_factory=list)
    countries: list[CountryTarget] = field(default_factory=list)
    search: SearchConfig = field(default_factory=SearchConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    def resolve_token(self) -> str | None:
        if self.device_token:
            return self.device_token
        return os.environ.get(self.device_token_env) or None


def _occupation_groups(raw: dict[str, Any] | None) -> list[OccupationGroup]:
    groups: list[OccupationGroup] = []
    for name, body in (raw or {}).items():
        body = body or {}
        groups.append(
            OccupationGroup(
                name=str(name),
                primary=[str(term) for term in body.get("primary", [])],
                secondary=[str(term) for term in body.get("secondary", [])],
                exclusions=[str(term) for term in body.get("exclusions", [])],
            )
        )
    return groups


def _centers(raw: list[dict[str, Any]] | None) -> list[LocationCenter]:
    return [
        LocationCenter(
            country=str(item["country"]).upper(),
            geo_id=str(item["geo_id"]),
            city=item.get("city"),
            state=item.get("state"),
            keywords=[str(k) for k in item.get("keywords", [])],
        )
        for item in (raw or [])
    ]


def _countries(raw: list[dict[str, Any]] | None) -> list[CountryTarget]:
    return [
        CountryTarget(
            country=str(item["country"]).upper(),
            geo_id=str(item["geo_id"]),
            keywords=[str(k) for k in item.get("keywords", [])],
        )
        for item in (raw or [])
    ]


def config_from_dict(data: dict[str, Any]) -> AgentConfig:
    browser_raw = data.get("browser", {}) or {}
    search_raw = data.get("search", {}) or {}
    storage_raw = data.get("storage", {}) or {}
    return AgentConfig(
        api_base_url=str(data.get("api_base_url", DEFAULT_API_BASE_URL)).rstrip("/"),
        source=str(data.get("source", DEFAULT_SOURCE)),
        device_token=data.get("device_token"),
        device_token_env=str(data.get("device_token_env", DEFAULT_DEVICE_TOKEN_ENV)),
        occupation_groups=_occupation_groups(data.get("occupation_groups")),
        centers=_centers(data.get("locations", {}).get("centers") if data.get("locations") else None),
        countries=_countries(
            data.get("locations", {}).get("countries") if data.get("locations") else None
        ),
        search=SearchConfig(
            date_posted_seconds=int(search_raw.get("date_posted_seconds", 604800)),
            distance_miles=int(search_raw.get("distance_miles", 25)),
            results_per_page=int(search_raw.get("results_per_page", 25)),
            max_pages_per_query=int(search_raw.get("max_pages_per_query", 3)),
            delay_seconds=float(search_raw.get("delay_seconds", 3.0)),
            delay_jitter_seconds=float(search_raw.get("delay_jitter_seconds", 2.0)),
            max_detail_fetches=int(search_raw.get("max_detail_fetches", 150)),
            max_queries=int(search_raw.get("max_queries", 40)),
        ),
        browser=BrowserConfig(
            profile_dir=str(browser_raw.get("profile_dir", "~/.jobagg/linkedin-profile")),
            headless=bool(browser_raw.get("headless", False)),
            page_load_timeout=int(browser_raw.get("page_load_timeout", 45)),
            challenge_timeout=int(browser_raw.get("challenge_timeout", 600)),
            window_size=str(browser_raw.get("window_size", "1400,1000")),
        ),
        storage=StorageConfig(
            data_dir=str(storage_raw.get("data_dir", "~/.jobagg/linkedin-collector"))
        ),
    )


def load_config(path: str | Path) -> AgentConfig:
    with open(path, encoding="utf-8") as handle:
        return config_from_dict(json.load(handle))


__all__ = [
    "AgentConfig",
    "BrowserConfig",
    "CountryTarget",
    "LocationCenter",
    "OccupationGroup",
    "SearchConfig",
    "StorageConfig",
    "config_from_dict",
    "load_config",
]
