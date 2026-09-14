"""Collector contract shared by all adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from apps.api.config import Settings
from apps.api.metrics import record_http_error
from packages.job_schema import NormalizedJob


class CollectorError(RuntimeError):
    """Raised when a collector cannot run (missing credentials, blocked, ...)."""


@dataclass(slots=True)
class SearchParams:
    keywords: str | None = None
    location: str | None = None
    country: str | None = None
    results_wanted: int = 50
    remote_only: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def country_code(self) -> str | None:
        return self.country.upper() if self.country else None


class BaseCollector(ABC):
    """Base class every source adapter must implement.

    Subclasses override :meth:`stream` as an ``async`` generator. A single
    failing source must never take the whole run down, so adapters catch their
    own per-item/per-board errors and keep yielding.
    """

    name: str = "base"
    display_name: str = "Base"
    requires_credentials: bool = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_enabled(self) -> bool:
        return True

    def validate(self) -> None:
        """Raise :class:`CollectorError` if required config is missing."""

    def _record_response(self, response: httpx.Response) -> None:
        """Count upstream error responses (429/403/5xx) per collector."""
        try:
            if response.status_code >= 400:
                record_http_error(self.name, response.status_code)
        except Exception:  # noqa: BLE001 - metrics must never break a request
            pass

    def _client(self, **kwargs) -> httpx.AsyncClient:
        headers = {"User-Agent": self.settings.user_agent, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", None) or {})
        hooks = dict(kwargs.pop("event_hooks", None) or {})
        hooks["response"] = [*hooks.get("response", []), self._record_response]
        return httpx.AsyncClient(
            headers=headers,
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            event_hooks=hooks,
            **kwargs,
        )

    @abstractmethod
    def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        """Yield normalised jobs for the given search."""
        raise NotImplementedError

    async def collect(self, params: SearchParams) -> list[NormalizedJob]:
        return [job async for job in self.stream(params)]
