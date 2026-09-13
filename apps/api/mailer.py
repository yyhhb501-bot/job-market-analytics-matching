"""Saved-search alert emails.

Uses the standard library (``smtplib`` + ``email.message``) so no extra
dependency is required. Sending is a no-op unless ``ENABLE_EMAIL_ALERTS`` is
true and SMTP + sender are configured.
"""

from __future__ import annotations

import html as html_lib
import logging
import smtplib
from collections.abc import Iterable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from apps.api.config import Settings

logger = logging.getLogger("jobagg.mailer")

_FOOTER_NOTE = "You are receiving this because you saved a search on Job Aggregator."


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


def is_email_configured(settings: Settings) -> bool:
    return bool(
        settings.enable_email_alerts
        and settings.smtp_host
        and settings.alert_from_email
    )


def _format_salary(job: Any) -> str | None:
    minimum = getattr(job, "salary_min", None)
    maximum = getattr(job, "salary_max", None)
    if minimum is None and maximum is None:
        return None
    currency = getattr(job, "salary_currency", None) or ""
    if minimum is not None and maximum is not None and minimum != maximum:
        amount = f"{minimum:,.0f} - {maximum:,.0f}"
    else:
        amount = f"{(minimum if minimum is not None else maximum):,.0f}"
    period = getattr(job, "salary_period", None)
    return f"{currency} {amount} / {period}".strip() if period else f"{currency} {amount}".strip()


def _format_location(job: Any) -> str:
    parts = [
        getattr(job, "city", None),
        getattr(job, "state", None),
        getattr(job, "country", None),
    ]
    return ", ".join(str(part) for part in parts if part) or "Location not specified"


def _detail_url(settings: Settings, job: Any) -> str | None:
    job_id = getattr(job, "id", None)
    if job_id is None:
        return None
    return f"{settings.web_base_url.rstrip('/')}/jobs/{job_id}"


def render_alert(
    settings: Settings,
    search_name: str,
    to_email: str,
    jobs: Iterable[Any],
    unsubscribe_url: str | None = None,
    digest: bool = False,
) -> OutgoingEmail:
    jobs = list(jobs)
    label = "Daily digest" if digest else "New jobs"
    subject = f"{label}: {len(jobs)} job(s) for \u201c{search_name}\u201d"

    text_lines = [f'{label} matching "{search_name}":', ""]
    html_items: list[str] = []
    for index, job in enumerate(jobs, start=1):
        title = getattr(job, "title", "Untitled")
        company = getattr(job, "company", None) or "Unknown company"
        location = _format_location(job)
        salary = _format_salary(job)
        source = getattr(job, "source", "")
        detail = _detail_url(settings, job)
        apply_url = getattr(job, "apply_url", None) or getattr(job, "canonical_url", None)

        text_lines.append(f"{index}. {title} — {company} ({source})")
        text_lines.append(f"   {location}")
        if salary:
            text_lines.append(f"   {salary}")
        if detail:
            text_lines.append(f"   Details: {detail}")
        if apply_url:
            text_lines.append(f"   Apply: {apply_url}")
        text_lines.append("")

        details_html = (
            f'<a href="{html_lib.escape(detail)}" style="color:#2563eb">Details</a>'
            if detail
            else ""
        )
        apply_html = (
            f'<a href="{html_lib.escape(str(apply_url))}" style="color:#2563eb">Apply</a>'
            if apply_url
            else ""
        )
        links = " &middot; ".join(part for part in (details_html, apply_html) if part)
        salary_html = (
            f'<div style="color:#047857;font-weight:600">{html_lib.escape(salary)}</div>'
            if salary
            else ""
        )
        html_items.append(
            '<li style="margin-bottom:14px">'
            f'<div style="font-weight:600">{html_lib.escape(str(title))}</div>'
            f'<div style="color:#334155">{html_lib.escape(str(company))} &middot; '
            f"{html_lib.escape(source)}</div>"
            f'<div style="color:#64748b">{html_lib.escape(location)}</div>'
            f"{salary_html}"
            f'<div style="margin-top:4px">{links}</div>'
            "</li>"
        )

    footer_parts = [_FOOTER_NOTE]
    if unsubscribe_url:
        footer_parts.append(
            f'<a href="{html_lib.escape(unsubscribe_url)}" style="color:#64748b">Unsubscribe</a>'
        )
    footer_html = "<br/>".join(footer_parts)

    html = (
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px">'
        f'<h2 style="margin:0 0 12px">{html_lib.escape(label)} for '
        f"&ldquo;{html_lib.escape(search_name)}&rdquo;</h2>"
        f'<ul style="padding-left:18px;margin:0">{"".join(html_items)}</ul>'
        f'<p style="color:#64748b;font-size:12px;margin-top:18px">{footer_html}</p>'
        "</div>"
    )

    text_lines.append(_FOOTER_NOTE)
    if unsubscribe_url:
        text_lines.append(f"Unsubscribe: {unsubscribe_url}")

    return OutgoingEmail(to=to_email, subject=subject, text="\n".join(text_lines), html=html)


def send_email(
    settings: Settings,
    message: OutgoingEmail,
    smtp_factory: type[smtplib.SMTP] = smtplib.SMTP,
) -> bool:
    if not is_email_configured(settings):
        logger.info("email alerts disabled or SMTP not configured; skipping %s", message.to)
        return False

    email_message = EmailMessage()
    email_message["Subject"] = message.subject
    email_message["From"] = formataddr((settings.alert_from_name, settings.alert_from_email))
    email_message["To"] = message.to
    email_message.set_content(message.text)
    email_message.add_alternative(message.html, subtype="html")

    with smtp_factory(
        settings.smtp_host, settings.smtp_port, timeout=settings.http_timeout_seconds
    ) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(email_message)

    logger.info("sent job alert to %s (%s)", message.to, message.subject)
    return True


def send_saved_search_alert(
    settings: Settings,
    search_name: str,
    to_email: str,
    jobs: Iterable[Any],
    unsubscribe_url: str | None = None,
    digest: bool = False,
    smtp_factory: type[smtplib.SMTP] = smtplib.SMTP,
) -> bool:
    if not to_email:
        return False
    message = render_alert(
        settings, search_name, to_email, jobs, unsubscribe_url=unsubscribe_url, digest=digest
    )
    return send_email(settings, message, smtp_factory=smtp_factory)


__all__ = [
    "OutgoingEmail",
    "is_email_configured",
    "render_alert",
    "send_email",
    "send_saved_search_alert",
]
