"""Create a Chrome session backed by a persistent, user-owned profile.

The collector never asks for LinkedIn credentials. On first run the user logs
in by hand in the opened window; the session is kept in a dedicated Chrome
profile directory so later runs reuse it.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from clients.linkedin_local_agent.config import BrowserConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from selenium.webdriver.chrome.webdriver import WebDriver

logger = logging.getLogger("linkedin_agent.browser")

_STEALTH_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def create_driver(config: BrowserConfig) -> WebDriver:
    """Return a Chrome driver using the configured persistent profile."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument(f"--user-data-dir={config.resolved_profile_dir}")
    options.add_argument(f"--window-size={config.window_size}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if config.headless:
        options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(config.page_load_timeout)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_SCRIPT}
        )
    except Exception as exc:  # noqa: BLE001 - cosmetic hardening only
        logger.debug("could not apply stealth script: %s", exc)
    return driver


def open_url(driver: WebDriver, url: str, pause: float = 1.5) -> str:
    """Navigate to ``url`` and return the page source."""
    driver.get(url)
    if pause:
        time.sleep(pause)
    return driver.page_source


__all__ = ["create_driver", "open_url"]
