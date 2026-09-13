"""Saved-search webhook delivery (POST JSON when new matches appear).

SSRF-safe: URLs are validated (scheme + host allowlist + resolved IP ranges)
both when saved and again immediately before sending. Redirects are not
followed so a public host cannot bounce the request into the internal network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from apps.api.config import Settings
from apps.api.url_safety import (
    UnsafeUrlError,
    normalize_webhook_url,
    parse_allowed_hosts,
    validate_webhook_url,
)

logger = logging.getLogger("jobagg.webhooks")


def build_payload(settings: Settings, search: Any, jobs: list) -> dict:
    base = settings.web_base_url.rstrip("/")
    max_jobs = max(int(settings.webhook_max_jobs), 0)
    items = [
        {
            "id": job.id,
            "source": job.source,
            "title": job.title,
            "company": job.company,
            "city": job.city,
            "state": job.state,
            "country": job.country,
            "remote_type": job.remote_type,
            "employment_type": job.employment_type,
            "url": f"{base}/jobs/{job.id}",
        }
        for job in jobs[:max_jobs]
    ]
    return {
        "event": "saved_search.matches",
        "saved_search": {"id": search.id, "name": search.name},
        "new_matches": len(jobs),
        "jobs": items,
    }


def _location(job: Any) -> str:
    parts = [job.city, job.state, job.country]
    return ", ".join(str(part) for part in parts if part)


def build_slack_payload(settings: Settings, search: Any, jobs: list) -> dict:
    base = settings.web_base_url.rstrip("/")
    lines = [f"*{len(jobs)} new job(s) for {search.name}*"]
    for job in jobs[: max(int(settings.webhook_max_jobs), 0)]:
        location = _location(job)
        suffix = f" ({location})" if location else ""
        lines.append(
            f"• <{base}/jobs/{job.id}|{job.title}> — {job.company or 'Unknown company'}{suffix}"
        )
    return {"text": "\n".join(lines)}


def build_teams_payload(settings: Settings, search: Any, jobs: list) -> dict:
    base = settings.web_base_url.rstrip("/")
    lines = []
    for job in jobs[: max(int(settings.webhook_max_jobs), 0)]:
        location = _location(job)
        suffix = f" ({location})" if location else ""
        lines.append(
            f"- [{job.title}]({base}/jobs/{job.id}) — {job.company or 'Unknown company'}{suffix}"
        )
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"{len(jobs)} new job(s) for {search.name}",
        "title": f"{len(jobs)} new job(s) for {search.name}",
        "text": "\n\n".join(lines),
    }


def build_webhook_payload(settings: Settings, search: Any, jobs: list) -> dict:
    """Dispatch to the payload shape for the search's ``webhook_kind``."""
    kind = str(getattr(search, "webhook_kind", "generic") or "generic").lower()
    if kind == "slack":
        return build_slack_payload(settings, search, jobs)
    if kind == "teams":
        return build_teams_payload(settings, search, jobs)
    return build_payload(settings, search, jobs)


def sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send_webhook(
    url: str,
    payload: dict,
    settings: Settings | None = None,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
    validate: bool = True,
    resolver=None,
) -> bool:
    if not url:
        return False

    if validate:
        allowed = parse_allowed_hosts(getattr(settings, "webhook_allowed_hosts", "")) if settings else []
        allow_private = bool(getattr(settings, "webhook_allow_private", False)) if settings else False
        kwargs: dict[str, Any] = {"allowed_hosts": allowed, "allow_private": allow_private}
        if resolver is not None:
            kwargs["resolver"] = resolver
        try:
            validate_webhook_url(url, **kwargs)
        except UnsafeUrlError as exc:
            logger.warning("webhook blocked: %s", exc)
            return False

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    secret = getattr(settings, "webhook_signing_secret", None) if settings else None
    if secret:
        headers["X-JobAgg-Signature"] = sign_payload(secret, body)

    try:
        if client is not None:
            response = client.post(url, content=body, headers=headers)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=False) as http:
                response = http.post(url, content=body, headers=headers)
        if 300 <= response.status_code < 400:
            logger.warning("webhook redirect rejected for %s", url)
            return False
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - never break the alert run
        logger.warning("webhook to %s failed: %s", url, exc)
        return False


__all__ = [
    "build_payload",
    "build_slack_payload",
    "build_teams_payload",
    "build_webhook_payload",
    "normalize_webhook_url",
    "send_webhook",
    "sign_payload",
]
