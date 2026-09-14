"""LinkedIn ``geoId`` helpers.

LinkedIn's text location matching is unreliable (it silently widens the area),
so searches should be pinned with a numeric ``geoId`` taken from the URL after
picking the location in the UI, e.g.::

    https://www.linkedin.com/jobs/search/?geoId=103644278&keywords=data%20analyst

The values below are commonly used country ids, but LinkedIn changes them
rarely and they are *not* verified by this tool. Treat the JSON config as the
source of truth and confirm every id once in the browser; ``validate_geo_id``
just guards against obvious mistakes.
"""

from __future__ import annotations

# Country-level ids (verify before relying on them).
KNOWN_COUNTRY_GEO_IDS: dict[str, str] = {
    "US": "103644278",
    "AU": "101452733",
}


def geo_id_for_country(country: str) -> str | None:
    return KNOWN_COUNTRY_GEO_IDS.get(country.strip().upper())


def validate_geo_id(geo_id: str | None) -> bool:
    """A LinkedIn geo id is a non-empty run of digits."""
    return bool(geo_id) and str(geo_id).strip().isdigit()


__all__ = ["KNOWN_COUNTRY_GEO_IDS", "geo_id_for_country", "validate_geo_id"]
