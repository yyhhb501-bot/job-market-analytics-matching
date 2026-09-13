"""URL / SSRF safety helpers for outbound webhooks."""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger("jobagg.url_safety")


class UnsafeUrlError(ValueError):
    pass


def normalize_webhook_url(url: str | None) -> str | None:
    """Validate the URL shape only (scheme + host); no DNS resolution."""
    if not url:
        return None
    text = url.strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("webhook_url must be an absolute http(s) URL")
    return text


def resolve_ips(host: str) -> set[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return {info[4][0] for info in infos}


def _is_blocked(ip: str, allow_private: bool) -> bool:
    if allow_private:
        return False
    address = ipaddress.ip_address(ip)
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def parse_allowed_hosts(value: str | None) -> list[str]:
    if not value:
        return []
    return [host.strip().lower() for host in value.split(",") if host.strip()]


def validate_webhook_url(
    url: str | None,
    *,
    allowed_hosts: list[str] | None = None,
    allow_private: bool = False,
    resolver=resolve_ips,
) -> str | None:
    """Validate scheme, optional host allowlist, and resolved IP ranges.

    Raises :class:`UnsafeUrlError` for anything that could reach internal
    services (loopback, private, link-local, metadata/reserved addresses).
    """
    text = normalize_webhook_url(url)
    if text is None:
        return None

    host = (urlparse(text).hostname or "").lower()
    allowlist = {item.lower() for item in (allowed_hosts or []) if item}
    if allowlist and host not in allowlist:
        raise UnsafeUrlError(f"webhook host {host!r} is not in WEBHOOK_ALLOWED_HOSTS")

    try:
        addresses = resolver(host)
    except Exception as exc:  # noqa: BLE001 - DNS failures are unsafe by default
        raise UnsafeUrlError(f"webhook host {host!r} could not be resolved") from exc

    for address in addresses:
        try:
            blocked = _is_blocked(address, allow_private)
        except ValueError as exc:
            raise UnsafeUrlError(f"invalid resolved address {address!r}") from exc
        if blocked:
            raise UnsafeUrlError(
                f"webhook target {host!r} resolves to a blocked address ({address})"
            )
    return text


__all__ = [
    "UnsafeUrlError",
    "normalize_webhook_url",
    "parse_allowed_hosts",
    "resolve_ips",
    "validate_webhook_url",
]
