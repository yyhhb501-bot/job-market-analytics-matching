"""Normalisation and the platform's three-layer deduplication keys.

Layer 1: ``(source, source_job_id)``  -> exact identity, handled by a DB unique key.
Layer 2: canonicalised apply URL        -> same posting reached through a different link.
Layer 3: company + title + city + description hash -> same role cross-posted
         on LinkedIn / Indeed / SEEK / a company ATS.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from packages.job_schema import NormalizedJob

_LEGAL_SUFFIXES = (
    "incorporated",
    "inc",
    "llc",
    "l l c",
    "ltd",
    "limited",
    "plc",
    "corp",
    "corporation",
    "co",
    "gmbh",
    "pty",
    "pty ltd",
    "pvt",
    "private",
    "group",
    "holdings",
    "company",
)

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "gclid",
        "fbclid",
        "msclkid",
        "igshid",
        "ref",
        "referrer",
        "source",
        "gh_src",
        "gh_jid",
        "lever-source",
        "lever-origin",
        "trk",
        "trackingid",
        "sessionid",
    }
)

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]")
_MULTI_DASH = re.compile(r"-{2,}")


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def normalize_text(value: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    if not value:
        return ""
    text = _ascii(value).lower()
    text = _NON_WORD.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_company(value: str | None) -> str:
    """Normalise a company name and drop common legal suffixes."""
    text = normalize_text(value)
    if not text:
        return ""
    tokens = text.split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_location(value: str | None) -> str:
    return normalize_text(value)


def normalize_url(value: str | None) -> str:
    """Canonicalise a URL for dedup: drop tracking params, fragment and www."""
    if not value:
        return ""
    value = value.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.lower()

    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(sorted(query)), ""))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def description_hash(description: str | None) -> str:
    return hash_text(normalize_text(description))


def content_hash(job: NormalizedJob) -> str:
    """Stable identity of the exact payload from a source."""
    payload = "|".join(
        (
            job.source,
            job.source_job_id or "",
            normalize_text(job.title),
            normalize_company(job.company),
            normalize_location(job.city),
            description_hash(job.description),
        )
    )
    return hash_text(payload)


def dedup_key(job: NormalizedJob) -> str:
    """Cross-platform key: company + title + city + description."""
    payload = "|".join(
        (
            normalize_company(job.company),
            normalize_text(job.title),
            normalize_location(job.city),
            description_hash(job.description),
        )
    )
    return hash_text(payload)


def canonical_url_hash(job: NormalizedJob) -> str | None:
    url = normalize_url(job.best_url())
    return hash_text(url) if url else None


def compute_hashes(job: NormalizedJob) -> dict[str, str | None]:
    """All dedup-related hashes plus the normalised fields stored on the row."""
    return {
        "content_hash": content_hash(job),
        "dedup_key": dedup_key(job),
        "canonical_url_hash": canonical_url_hash(job),
        "description_hash": description_hash(job.description),
        "title_normalized": normalize_text(job.title),
        "company_normalized": normalize_company(job.company),
    }


__all__ = [
    "canonical_url_hash",
    "compute_hashes",
    "content_hash",
    "dedup_key",
    "description_hash",
    "hash_text",
    "normalize_company",
    "normalize_location",
    "normalize_text",
    "normalize_url",
]
