"""Collector contract shared by all adapters.

Every upstream request must go through :meth:`BaseCollector._pre_request`
(throttle + daily visit budget) and :meth:`BaseCollector._board_json` /
``response.raise_for_status`` replacement so failures are classified into
four run outcomes: ``success`` / ``partial`` / ``retryable`` / ``blocked``.
Access limits (CAPTCHA, 403, login walls) raise :class:`AccessBlockedError`
and are never retried automatically; rate limits carry the server's
``Retry-After`` hint so the task layer can wait exactly as long as required.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from apps.api.config import Settings
from apps.api.metrics import record_http_error
from packages.job_schema import NormalizedJob


class CollectorError(RuntimeError):
    """Raised when a collector cannot run (missing credentials, blocked, ...)."""


class RetryableCollectorError(CollectorError):
    """Transient upstream failure (network, timeout, 5xx): Celery may retry."""


class RateLimitedError(RetryableCollectorError):
    """HTTP 429. Carries the server's ``Retry-After`` hint in seconds."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AccessBlockedError(CollectorError):
    """CAPTCHA / checkpoint / 401/403: stop and wait for a human, never retry."""


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (seconds or HTTP-date) into seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return max(float(value), 0.0)
    try:
        from email.utils import parsedate_to_datetime

        target = parsedate_to_datetime(value)
        return max((target.timestamp() - time.time()), 0.0)
    except (TypeError, ValueError):
        return None


def classify_exception(exc: Exception) -> tuple[str, float | None]:
    """Map an upstream failure to ``(outcome, retry_after_seconds)``.

    Outcomes: ``retryable`` (Celery may retry) or ``blocked`` (do not retry).
    """
    if isinstance(exc, RateLimitedError):
        return "retryable", exc.retry_after
    if isinstance(exc, AccessBlockedError):
        return "blocked", None
    if isinstance(exc, RetryableCollectorError | CollectorError):
        return "retryable", None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "retryable", parse_retry_after(exc.response.headers.get("retry-after"))
        if status in (401, 403):
            return "blocked", None
        return "retryable", None
    if isinstance(exc, httpx.HTTPError):
        return "retryable", None
    return "retryable", None


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
    own per-item/per-board errors and keep yielding — except
    :class:`RateLimitedError` / :class:`AccessBlockedError`, which abort the
    stream so the pipeline can classify and (not) retry the run.
    """

    name: str = "base"
    display_name: str = "Base"
    requires_credentials: bool = False
    # Per-source minimum spacing between upstream requests, overriding
    # ACTION_INTERVAL_SECONDS when larger (e.g. SEEK's requests-per-minute).
    min_interval_seconds: float = 0.0

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Per-run state: board token -> completed successfully; the pipeline
        # uses it to age out missing jobs only for fully-collected boards.
        self.board_outcomes: dict[str, bool] = {}
        self.board_errors: dict[str, str] = {}
        # Boards whose listing was read to its natural end this run. A board
        # stopped early by ``results_wanted`` is removed via
        # :meth:`_note_board_incomplete` so its jobs are never aged out.
        self.complete_boards: set[str] = set()
        # The board the stream is currently reading; attached to yielded jobs.
        self.current_board: str | None = None
        # Set by the pipeline when visit budgets are configured.
        self.budget = None
        self._last_request_at = 0.0

    def is_enabled(self) -> bool:
        return True

    def validate(self) -> None:
        """Raise :class:`CollectorError` if required config is missing."""

    async def _record_response(self, response: httpx.Response) -> None:
        """Count upstream error responses and page visits (async: httpx async
        clients require async response hooks — a sync hook would raise on
        every response)."""
        try:
            if response.status_code >= 400:
                record_http_error(self.name, response.status_code)
            if self.budget is not None:
                await self.budget.record_page()
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

    # -- shared pacing / budgeting / error classification -------------------

    async def _throttle(self) -> None:
        """Space upstream requests by ACTION_INTERVAL_SECONDS (or the
        per-source minimum, whichever is larger). No configured value implies
        no artificial delay."""
        interval = max(float(self.settings.action_interval_seconds or 0.0), self.min_interval_seconds)
        if interval <= 0:
            return
        now = time.monotonic()
        wait = self._last_request_at + interval - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    async def _pre_request(self) -> bool:
        """Call before every upstream request. ``False`` means a stop
        condition was reached (visit budget exhausted) and the adapter should
        end its stream cleanly — not error, not retry."""
        if self.budget is not None and not self.budget.page_allowed():
            return False
        await self._throttle()
        return True

    async def _note_detail(self) -> bool:
        """Count one detail-page visit; ``False`` = detail budget exhausted."""
        if self.budget is None:
            return True
        return await self.budget.record_detail()

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Replace ``response.raise_for_status()`` with classified errors."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = response.status_code
            if status == 429 and self.settings.respect_retry_after:
                raise RateLimitedError(
                    str(exc), retry_after=parse_retry_after(response.headers.get("retry-after"))
                ) from exc
            if status in (401, 403):
                raise AccessBlockedError(str(exc)) from exc
            raise

    def _note_board_failure(self, board: str, exc: Exception) -> None:
        """Record a failed board so the pipeline can skip its missing-job sweep."""
        self.board_outcomes[board] = False
        self.board_errors[board] = f"{type(exc).__name__}: {exc}"
        self.complete_boards.discard(board)

    def _note_board_incomplete(self, board: str) -> None:
        """The board listing was cut short (results_wanted cap): its snapshot
        is not complete, so the pipeline must not sweep its missing jobs."""
        self.complete_boards.discard(board)

    async def _board_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        board: str,
        params: dict | None = None,
        **kwargs,
    ):
        """Fetch one board/page as JSON with attribution and classification.

        Success marks the board as fetched and (by default) fully read —
        paginating adapters call :meth:`_note_board_incomplete` when they stop
        early on ``results_wanted``. Rate limits and access blocks propagate
        so the run ends as ``retryable`` / ``blocked`` instead of continuing
        to hammer the platform.
        """
        self.current_board = board
        response = await client.get(url, params=params, **kwargs)
        self._raise_for_status(response)
        payload = response.json()
        self.board_outcomes[board] = True
        self.complete_boards.add(board)
        return payload

    @abstractmethod
    def stream(self, params: SearchParams) -> AsyncIterator[NormalizedJob]:
        """Yield normalised jobs for the given search."""
        raise NotImplementedError

    async def collect(self, params: SearchParams) -> list[NormalizedJob]:
        return [job async for job in self.stream(params)]
