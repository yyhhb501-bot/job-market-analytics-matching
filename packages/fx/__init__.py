"""Currency conversion for salary display.

Amounts are always stored in their original currency; a display currency is
derived on read. ``rates`` express the value of **one unit** of a currency in
the base currency (USD by default), so ``AUD: 0.66`` means 1 AUD = 0.66 USD.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_BASE = "USD"
DEFAULT_RATES: dict[str, float] = {
    "USD": 1.0,
    "AUD": 0.66,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.74,
    "NZD": 0.60,
}


def parse_rates(raw: str | dict | None) -> dict[str, float]:
    """Parse ``FX_RATES`` (JSON string or mapping) into an upper-cased rate map."""
    if raw is None or raw == "":
        return dict(DEFAULT_RATES)
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return dict(DEFAULT_RATES)
    rates: dict[str, float] = {}
    for key, value in data.items():
        try:
            rate = float(value)
        except (TypeError, ValueError):
            continue
        if rate > 0:
            rates[str(key).upper()] = rate
    rates.setdefault(DEFAULT_BASE, 1.0)
    return rates


def convert(
    amount: float | None,
    source: str | None,
    target: str | None,
    rates: dict[str, float] | None = None,
) -> float | None:
    """Convert ``amount`` from ``source`` to ``target`` currency."""
    if amount is None or not source or not target:
        return None
    rates = rates or DEFAULT_RATES
    source = source.upper()
    target = target.upper()
    if source == target:
        return float(amount)
    if source not in rates or target not in rates:
        return None
    return float(amount) * rates[source] / rates[target]


def convert_job_salary(
    job: Any, target: str | None, rates: dict[str, float] | None = None
) -> dict[str, float | str | None]:
    """Return display-salary fields for a job in ``target`` currency.

    Returns ``{}`` when the job has no salary or conversion is not possible.
    """
    if not target:
        return {}
    source = getattr(job, "salary_currency", None)
    minimum = getattr(job, "salary_min", None)
    maximum = getattr(job, "salary_max", None)
    if minimum is None and maximum is None:
        return {}
    converted_min = convert(minimum, source, target, rates)
    converted_max = convert(maximum, source, target, rates)
    if converted_min is None and converted_max is None:
        return {}
    return {
        "salary_display_min": converted_min,
        "salary_display_max": converted_max,
        "salary_display_currency": target.upper(),
        "salary_display_period": getattr(job, "salary_period", None),
    }


__all__ = [
    "DEFAULT_BASE",
    "DEFAULT_RATES",
    "convert",
    "convert_job_salary",
    "parse_rates",
]
