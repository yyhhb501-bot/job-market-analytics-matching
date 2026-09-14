"""Detect CAPTCHA / checkpoint / auth-wall pages and pause for the user.

The collector never attempts to solve or bypass a challenge. When one appears
it stops issuing requests and waits for the user to resolve it in the opened
browser, then continues (or aborts if the user gives up).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from selenium.webdriver.chrome.webdriver import WebDriver

logger = logging.getLogger("linkedin_agent.browser")

_CHALLENGE_URL_MARKERS = (
    "/checkpoint/",
    "/challenge/",
    "/authwall",
    "/login",
    "/uas/login",
)
_CHALLENGE_TEXT_MARKERS = (
    "let's do a quick security check",
    "quick security check",
    "verify you're a human",
    "unusual activity",
    "enter the characters you see",
    "we've emailed you a",
)


class ChallengeDetected(RuntimeError):
    """Raised when LinkedIn presents a CAPTCHA, checkpoint or login wall."""


def looks_like_challenge(url: str, page_source: str) -> bool:
    lowered_url = (url or "").lower()
    if any(marker in lowered_url for marker in _CHALLENGE_URL_MARKERS):
        return True
    lowered = (page_source or "").lower()
    return any(marker in lowered for marker in _CHALLENGE_TEXT_MARKERS)


def wait_for_user(driver: WebDriver, timeout: int, poll_seconds: float = 5.0) -> None:
    """Block until the challenge is cleared or ``timeout`` elapses."""
    deadline = time.monotonic() + max(int(timeout), 1)
    logger.warning(
        "LinkedIn presented a security check. Solve it in the browser window; "
        "waiting up to %s seconds...",
        timeout,
    )
    while time.monotonic() < deadline:
        time.sleep(poll_seconds)
        if not looks_like_challenge(driver.current_url, driver.page_source):
            logger.info("challenge cleared, resuming")
            return
    raise ChallengeDetected("security check was not resolved in time")


def guard(driver: WebDriver, timeout: int) -> None:
    if looks_like_challenge(driver.current_url, driver.page_source):
        wait_for_user(driver, timeout)


__all__ = ["ChallengeDetected", "guard", "looks_like_challenge", "wait_for_user"]
