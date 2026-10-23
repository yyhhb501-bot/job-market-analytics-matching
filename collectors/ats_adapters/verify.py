"""Lightweight, read-only verification of a single ATS board.

Used when adding/discovering boards: a board is only enabled once a provider
endpoint confirms it returns at least one posting.
"""

from __future__ import annotations

from typing import Any

import httpx


def board_entry(board: Any) -> dict:
    """Build a collector-style entry dict from a Board row / dict."""
    get = board.get if isinstance(board, dict) else lambda key, default=None: getattr(board, key, default)
    config = dict(get("config") or {})
    token = get("board_token")
    entry: dict = {"token": token, "board_id": get("id")}
    entry.update(config)
    if get("company_name"):
        entry.setdefault("company_name", get("company_name"))
    return entry


async def _greenhouse(client, e):
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{e['token']}/jobs")
    r.raise_for_status()
    return len(r.json().get("jobs") or [])


async def _lever(client, e):
    r = await client.get(f"https://api.lever.co/v0/postings/{e['token']}", params={"mode": "json"})
    r.raise_for_status()
    data = r.json()
    return len(data) if isinstance(data, list) else 0


async def _ashby(client, e):
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{e['token']}")
    r.raise_for_status()
    return len(r.json().get("jobs") or [])


async def _workable(client, e):
    r = await client.get(f"https://apply.workable.com/api/v1/widget/accounts/{e['token']}")
    r.raise_for_status()
    return len(r.json().get("jobs") or [])


async def _smartrecruiters(client, e):
    r = await client.get(
        f"https://api.smartrecruiters.com/v1/companies/{e['token']}/postings",
        params={"limit": 1},
    )
    r.raise_for_status()
    return int(r.json().get("totalFound") or 0)


async def _recruitee(client, e):
    r = await client.get(f"https://{e['token']}.recruitee.com/api/offers/")
    r.raise_for_status()
    return len(r.json().get("offers") or [])


async def _breezy(client, e):
    r = await client.get(f"https://{e['token']}.breezy.hr/json")
    r.raise_for_status()
    data = r.json()
    return len(data) if isinstance(data, list) else 0


async def _workday(client, e):
    tenant = e.get("tenant") or e["token"]
    host = e.get("host") or "wd1"
    site = e.get("site")
    base = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    r = await client.post(
        f"{base}/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    )
    r.raise_for_status()
    return int(r.json().get("total") or 0)


async def _personio(client, e):
    domain = e.get("domain") or "jobs.personio.de"
    r = await client.get(f"https://{e['token']}.{domain}/xml")
    r.raise_for_status()
    return r.text.count("<position")


async def _bamboohr(client, e):
    domain = e.get("domain") or "bamboohr.com"
    r = await client.get(f"https://{e['token']}.{domain}/careers/list")
    r.raise_for_status()
    return len(r.json().get("result") or [])


async def _pinpoint(client, e):
    r = await client.get(f"https://{e['token']}.pinpointhq.com/postings.json")
    r.raise_for_status()
    return len(r.json().get("data") or [])


async def _rippling(client, e):
    r = await client.get(f"https://ats.rippling.com/api/v2/board/{e['token']}/jobs")
    r.raise_for_status()
    return int(r.json().get("totalItems") or 0)


async def _jazzhr(client, e):
    api_key = e.get("api_key") or e["token"]
    r = await client.get("https://api.resumatorapi.com/v1/jobs", params={"apikey": api_key})
    r.raise_for_status()
    data = r.json()
    return len(data) if isinstance(data, list) else 0


async def _teamtailor(client, e):
    r = await client.get(
        "https://api.teamtailor.com/v1/jobs",
        headers={
            "Authorization": f"Token token={e.get('api_token')}",
            "X-Api-Version": str(e.get("api_version") or "20240404"),
        },
        params={"page[size]": 1},
    )
    r.raise_for_status()
    return len(r.json().get("data") or [])


async def _jobvite(client, e):
    r = await client.get(
        "https://api.jobvite.com/api/v2/job",
        params={"api": e.get("api"), "sc": e.get("sc")},
    )
    r.raise_for_status()
    data = r.json()
    jobs = data.get("jobs") if isinstance(data, dict) else data
    return len(jobs or [])


_VERIFIERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
    "recruitee": _recruitee,
    "breezy": _breezy,
    "workday": _workday,
    "personio": _personio,
    "bamboohr": _bamboohr,
    "pinpoint": _pinpoint,
    "rippling": _rippling,
    "jazzhr": _jazzhr,
    "teamtailor": _teamtailor,
    "jobvite": _jobvite,
}


async def verify_board(
    provider: str, entry: dict, *, user_agent: str, timeout: float, client: httpx.AsyncClient | None = None
) -> int | None:
    """Return the number of postings for a board, or None if it can't be checked."""
    verifier = _VERIFIERS.get(provider)
    if verifier is None:
        return None
    owns_client = client is None
    client = client or httpx.AsyncClient(
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        timeout=timeout,
        follow_redirects=True,
    )
    try:
        return int(await verifier(client, entry))
    except Exception:  # noqa: BLE001 - verification failure means "not usable"
        return None
    finally:
        if owns_client:
            await client.aclose()


__all__ = ["board_entry", "verify_board"]
