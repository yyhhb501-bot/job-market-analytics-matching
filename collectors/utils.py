"""Parsing helpers shared by the collectors."""

from __future__ import annotations

import datetime as dt
import html as html_lib
import re

AU_STATES = {"NSW", "VIC", "QLD", "ACT", "TAS", "NT"}
AU_AMBIGUOUS = {"SA", "WA"}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SALARY_RE = re.compile(r"(\d[\d,\.]*)\s*(k)?", re.IGNORECASE)


def strip_html(value: str | None) -> str | None:
    """Turn an HTML / entity-encoded description into plain text."""
    if not value:
        return None
    text = html_lib.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def trim(value: str | None, limit: int = 20000) -> str | None:
    if not value:
        return None
    return value if len(value) <= limit else value[:limit]


def split_location(location: str | None) -> tuple[str | None, str | None]:
    """Best-effort ``(city, state)`` extraction from a location string."""
    if not location:
        return None, None
    text = location.strip().rstrip(".")
    parts = [part.strip() for part in text.split(",") if part.strip()]
    known = US_STATES | AU_STATES | AU_AMBIGUOUS
    if len(parts) >= 2:
        tail = parts[-1]
        if len(tail) <= 3 and tail.upper() in known:
            return parts[0] or None, tail.upper()
        if parts[0].lower() in {"remote", "anywhere"} and len(parts) > 1:
            return parts[0] or None, None
        return parts[0] or None, parts[-1] or None
    tokens = text.split()
    if tokens and tokens[-1].upper() in known:
        city = " ".join(tokens[:-1]).strip() or None
        return city, tokens[-1].upper()
    return text or None, None


def infer_country(location: str | None) -> str | None:
    """Infer ``US`` / ``AU`` from a free-form location string."""
    if not location:
        return None
    upper = location.upper()
    if "AUSTRALIA" in upper or "AOTEAROA" in upper:
        return "AU"
    if "UNITED STATES" in upper or "USA" in upper or "U.S." in upper:
        return "US"
    tokens = {token.strip(".,()") for token in re.split(r"[,\s/]+", upper) if token}
    if tokens & AU_STATES:
        return "AU"
    if tokens & US_STATES:
        return "US"
    return None


_EMPLOYMENT_ALIASES = {
    "fulltime": "full_time",
    "parttime": "part_time",
    "contractor": "contract",
    "intern": "internship",
    "regular": "other",
    "permanent": "other",
}


def normalize_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    text = _EMPLOYMENT_ALIASES.get(text, text)
    return text or None


def country_from_name(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.strip().upper()
    if upper in {"AU", "AUS", "AUSTRALIA"}:
        return "AU"
    if upper in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    return None


def parse_datetime(value) -> dt.datetime | None:
    """Parse epoch seconds/millis or an ISO string into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_datetime(int(text))
    text = text.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d %b %Y"):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


_MONEY_RE = re.compile(r"(?:A\$|AU\$|US\$|\$|€|£)?\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?")


def parse_salary_range(
    text: str | None, default_currency: str | None = None
) -> tuple[float | None, float | None, str | None, str | None]:
    """Parse a free-form compensation string into ``(min, max, currency, period)``."""
    if not text:
        return None, None, None, None
    upper = text.upper()
    if "AUD" in upper or "A$" in upper or "AU$" in upper:
        currency = "AUD"
    elif "USD" in upper or "US$" in upper:
        currency = "USD"
    elif "$" in text:
        currency = default_currency or "USD"
    else:
        currency = default_currency

    if "HOUR" in upper:
        period = "hour"
    elif "DAY" in upper:
        period = "day"
    elif "WEEK" in upper:
        period = "week"
    elif "MONTH" in upper:
        period = "month"
    elif "YEAR" in upper or "ANNUM" in upper or "ANN" in upper:
        period = "year"
    else:
        period = None

    values: list[float] = []
    for raw, suffix in _MONEY_RE.findall(text):
        try:
            number = float(raw.replace(",", ""))
        except ValueError:
            continue
        if suffix:
            number *= 1000
        if number >= 1000:
            values.append(number)
    if not values:
        return None, None, currency, period
    if len(values) == 1:
        return values[0], values[0], currency, period
    return min(values[0], values[1]), max(values[0], values[1]), currency, period


def parse_salary_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    match = _SALARY_RE.search(text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    if match.group(2):  # trailing "k" e.g. "120k"
        number *= 1000
    return number


__all__ = [
    "AU_AMBIGUOUS",
    "AU_STATES",
    "US_STATES",
    "country_from_name",
    "infer_country",
    "normalize_employment_type",
    "parse_datetime",
    "parse_salary_number",
    "parse_salary_range",
    "split_location",
    "strip_html",
    "trim",
]
