"""Manual, session-based login. No credentials are ever read or stored."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from clients.linkedin_local_agent.browser.challenge import wait_for_user

if TYPE_CHECKING:  # pragma: no cover - typing only
    from selenium.webdriver.chrome.webdriver import WebDriver

logger = logging.getLogger("linkedin_agent.browser")

LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
_LOGGED_OUT_MARKERS = ("/login", "/authwall", "/checkpoint", "/uas/login")


def is_logged_in(driver: WebDriver) -> bool:
    url = (driver.current_url or "").lower()
    if any(marker in url for marker in _LOGGED_OUT_MARKERS):
        return False
    if "linkedin.com" not in url:
        return False
    try:
        source = driver.page_source
    except Exception:  # noqa: BLE001 - transient during navigation
        return False
    return "global-nav" in source or "/feed" in url


def ensure_logged_in(driver: WebDriver, timeout: int = 600) -> None:
    """Open LinkedIn and wait for the user to be signed in."""
    driver.get(FEED_URL)
    time.sleep(2)
    if is_logged_in(driver):
        logger.info("reusing existing LinkedIn session")
        return

    logger.warning(
        "Not signed in. Log into LinkedIn in the browser window (including any "
        "email/2FA verification); the collector stores only the browser profile."
    )
    if "/login" not in (driver.current_url or ""):
        driver.get(LOGIN_URL)
    wait_for_user(driver, timeout)
    if not is_logged_in(driver):
        driver.get(FEED_URL)
        time.sleep(2)
    if not is_logged_in(driver):
        raise RuntimeError("still not logged in after waiting")


__all__ = ["FEED_URL", "LOGIN_URL", "ensure_logged_in", "is_logged_in"]
