"""Board management: runtime loading, JSON import, verification and discovery."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.config import Settings
from apps.api.models import Board, utcnow
from collectors.ats_adapters.verify import board_entry, verify_board

logger = logging.getLogger("jobagg.boards")

# provider -> regex capturing the board token from careers HTML/URLs
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_\-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_\-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.\-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_\-]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/([A-Za-z0-9_\-]+)")),
    ("recruitee", re.compile(r"([A-Za-z0-9\-]+)\.recruitee\.com")),
    ("bamboohr", re.compile(r"([A-Za-z0-9\-]+)\.bamboohr\.com")),
    ("breezy", re.compile(r"([A-Za-z0-9\-]+)\.breezy\.hr")),
    ("pinpoint", re.compile(r"([A-Za-z0-9\-]+)\.pinpointhq\.com")),
    ("personio", re.compile(r"([A-Za-z0-9\-]+)\.jobs\.personio\.(?:de|com)")),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/([A-Za-z0-9_\-]+)")),
    ("jazzhr", re.compile(r"([A-Za-z0-9\-]+)\.applytojob\.com")),
    ("rippling", re.compile(r"ats\.rippling\.com/([A-Za-z0-9_\-]+)")),
]
_WORKDAY_PATTERN = re.compile(
    r"([A-Za-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-zA-Z\-]+/)?([A-Za-z0-9_\-]+)"
)


def load_runtime_boards(session: Session) -> dict[str, list[dict]]:
    """Provider -> entries for all enabled boards, for the collectors."""
    boards = session.scalars(select(Board).where(Board.enabled.is_(True))).all()
    grouped: dict[str, list[dict]] = {}
    for board in boards:
        grouped.setdefault(board.provider, []).append(board_entry(board))
    return grouped


def import_boards_from_json(session: Session, settings: Settings) -> int:
    """Seed the boards table from ``config/ats_companies.json`` (idempotent)."""
    path = Path(settings.ats_companies_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    created = 0
    for provider, entries in data.items():
        if provider.startswith("_"):
            continue
        for raw in entries or []:
            if isinstance(raw, str):
                token, config = raw, {}
            elif isinstance(raw, dict):
                config = dict(raw)
                token = (
                    raw.get("token")
                    or raw.get("tenant")
                    or raw.get("api")
                    or raw.get("api_key")
                    or raw.get("board")
                )
            else:
                continue
            if not token:
                continue
            token = str(token)
            exists = session.scalar(
                select(Board).where(Board.provider == provider, Board.board_token == token)
            )
            if exists:
                continue
            session.add(
                Board(
                    provider=provider,
                    board_token=token,
                    company_name=config.get("company_name"),
                    config=config,
                    enabled=True,
                    discovery_source="json",
                )
            )
            created += 1
    session.commit()
    return created


async def verify_and_record(session: Session, board: Board, settings: Settings) -> int | None:
    count = await verify_board(
        board.provider,
        board_entry(board),
        user_agent=settings.user_agent,
        timeout=settings.http_timeout_seconds,
    )
    now = utcnow()
    board.last_checked_at = now
    if count is None:
        board.consecutive_failures = (board.consecutive_failures or 0) + 1
    else:
        board.verified_at = now
        board.last_job_count = count
        board.consecutive_failures = 0
        if count > 0:
            board.last_success_at = now
            board.enabled = True
    session.commit()
    return count


async def verify_all_boards(session: Session, settings: Settings) -> dict:
    boards = session.scalars(select(Board)).all()
    ok = failed = 0
    for board in boards:
        count = await verify_and_record(session, board, settings)
        if count is None:
            failed += 1
        else:
            ok += 1
    return {"checked": len(boards), "ok": ok, "failed": failed}


def _extract(html: str, url: str) -> list[dict]:
    candidates: list[dict] = []
    for provider, pattern in _PATTERNS:
        for match in pattern.findall(html):
            token = match if isinstance(match, str) else match[0]
            candidates.append(
                {"provider": provider, "board_token": token, "careers_url": url, "config": {}}
            )
    for tenant, host, site in _WORKDAY_PATTERN.findall(html):
        candidates.append(
            {
                "provider": "workday",
                "board_token": tenant,
                "careers_url": url,
                "config": {"tenant": tenant, "host": host, "site": site},
            }
        )
    return candidates


async def discover_from_domain(domain: str, settings: Settings) -> list[dict]:
    """Fetch a company's site/careers pages and detect its ATS board(s)."""
    host = domain.strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0]
    urls = [
        f"https://{host}",
        f"https://{host}/careers",
        f"https://{host}/jobs",
        f"https://www.{host}/careers",
    ]
    found: dict[tuple[str, str], dict] = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
    ) as client:
        for url in urls:
            try:
                response = await client.get(url)
            except Exception:  # noqa: BLE001
                continue
            for candidate in _extract(response.text, str(response.url)):
                found[(candidate["provider"], candidate["board_token"])] = candidate
    return list(found.values())


async def discover_and_verify(domain: str, settings: Settings) -> list[dict]:
    results = []
    for candidate in await discover_from_domain(domain, settings):
        count = await verify_board(
            candidate["provider"],
            {**candidate["config"], "token": candidate["board_token"]},
            user_agent=settings.user_agent,
            timeout=settings.http_timeout_seconds,
        )
        candidate["job_count"] = count
        candidate["verified"] = count is not None and count > 0
        results.append(candidate)
    return results


__all__ = [
    "discover_and_verify",
    "discover_from_domain",
    "import_boards_from_json",
    "load_runtime_boards",
    "verify_all_boards",
    "verify_and_record",
]
