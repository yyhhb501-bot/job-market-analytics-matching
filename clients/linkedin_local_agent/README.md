# LinkedIn Local Collector (client)

A **user-run** supplement collector for LinkedIn. It runs on the user's own
machine against their own logged-in Chrome session and uploads normalised jobs
to the platform's private import API.

It is deliberately **not** part of the server: no LinkedIn credentials are
stored, no CAPTCHA is bypassed, and coverage is not guaranteed. LinkedIn
personalises search, caps results and loads pages asynchronously, so this tool
supplements — never replaces — the platform's public/licensed sources.
Automated collection must respect LinkedIn's terms; use at your own risk.

## What it borrows from the reference collector

- `geoId`-pinned searches instead of unreliable text locations
- two channels per keyword: **city** (onsite/hybrid) and **country remote** (`f_WT=2`)
- several keywords per occupation group (config-driven, not hardcoded)
- full JD fetched only for unseen, accepted jobs (avoids opening ~500 pages)
- dedup by LinkedIn job id **and** `title + company`
- `seen` state separated so `filtered_location` never permanently hides a job
- incremental checkpointing: a crash loses at most the page in flight
- CAPTCHA/email verification pauses the run and hands control to the user

## Install

```bash
pip install -r clients/linkedin_local_agent/requirements.txt
# Selenium 4.20+ manages the Chrome driver automatically (Selenium Manager).
```

## 1. Get a device token (on the platform)

```bash
curl -X POST "http://localhost:8010/api/v1/import/devices" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"my-laptop","owner":"me@example.com"}'
# -> {"id":1, "token":"jagg_...", ...}   # token is shown ONCE
```

Store it in the environment; it is never written to the config file:

```bash
# PowerShell
setx JOBAGG_DEVICE_TOKEN "jagg_..."
# bash
export JOBAGG_DEVICE_TOKEN="jagg_..."
```

Revoke any time with `POST /api/v1/import/devices/{id}/revoke`.

## 2. Configure

```bash
mkdir -p ~/.jobagg/linkedin-collector
cp clients/linkedin_local_agent/config.example.json ~/.jobagg/linkedin-collector/config.json
```

Find each `geo_id` by selecting the location on LinkedIn and copying the number
from the URL (`...?geoId=103644278`). `REPLACE_WITH_...` placeholders are
rejected at startup so a run never silently searches the wrong region.

Preview the query matrix without opening a browser:

```bash
python -m clients.linkedin_local_agent.main --config ~/.jobagg/linkedin-collector/config.json --list-queries
```

## 3. Run

```bash
# first run only: a Chrome window opens; log in (and clear any email/2FA check)
python -m clients.linkedin_local_agent.main --config ~/.jobagg/linkedin-collector/config.json

# collect but do not upload (writes collected-*.json)
python -m clients.linkedin_local_agent.main --dry-run --config ~/.jobagg/linkedin-collector/config.json
```

Local state lives in `~/.jobagg/linkedin-collector/`:

- `seen.json` — job id + title/company states
- `checkpoint.json` — completed pages and uploaded ids
- `collected-*.json` — dry-run output

Use `--reset-checkpoint` to force a full re-scan, `--verbose` for debug logs.

## Flow

```
login (manual) -> query matrix (city + remote)
      -> search cards -> title/location pre-filter -> seen/checkpoint
      -> detail pages (JSON-LD JobPosting) -> batch upload -> private workspace
```

Uploaded jobs are stored `visibility=private` and are visible to this device
only (`GET /api/v1/import/jobs`); they never enter public search or market
statistics.

## Limitations

- LinkedIn DOM/JSON-LD changes can break parsing; the JSON-LD path is used first.
- Search is capped by LinkedIn (typically a few hundred results per query).
- If a security check appears, the run pauses; if unresolved it aborts safely.
- No proxies, no parallel workers, no automatic retry loops by design.
