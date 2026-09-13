# Job Aggregator (US + Australia)

A job aggregation platform focused on the **United States** and **Australia**.
It collects from public ATS boards and official APIs first, adds aggregator and
local-market sources behind opt-in switches, normalises everything into one
schema, deduplicates across sources, and exposes a search API.

The design deliberately avoids making the platform depend on any single
scraping target. Stable sources come first; risky sources are disabled by
default and can be turned off per adapter.

## Architecture

```text
                 ┌─ Public ATS: Greenhouse / Lever / Ashby / Workable /
                 │   SmartRecruiters / Recruitee / Breezy / Workday /
                 │   Personio / Teamtailor / BambooHR / JazzHR / Pinpoint /
                 │   Rippling / Jobvite (token ones need a key)         (on by default)
用户搜索条件 ────┼─ USAJOBS official API                                (opt-in)
                 ├─ JobSpy: Indeed / Glassdoor / Google Jobs           (opt-in)
                 ├─ Adzuna official API (US + AU)                      (opt-in)
                 ├─ RemoteOK public JSON feed                          (opt-in)
                 ├─ SEEK (AU)                                          (opt-in, low rate)
                 └─ Phase 2: ZipRecruiter / LinkedIn                   (not enabled)
                                  │
               采集任务队列 / scheduler (Celery + Redis；APScheduler 回退)
                                  │
                 标准化 → 三层去重 → 薪资与币种原样保存
                                  │
                             PostgreSQL
                                  │
                         FastAPI 搜索服务 ── 保存搜索 / 新岗位告警
                                  │
                    Next.js 前端（apps/web：搜索 / 详情 / 告警）
```

## Tech stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.11+ (developed on 3.13) |
| API | FastAPI + Pydantic v2 |
| Ingestion | HTTPX (async) + `python-jobspy` |
| Scheduling | Celery + Redis (APScheduler as a no-Redis fallback) |
| Database | PostgreSQL 16 |
| Search | PostgreSQL full-text (`tsvector` + GIN) by default; optional OpenSearch; `ILIKE` fallback |
| Migrations | Alembic |
| Packaging | Docker Compose |
| Tests | pytest (in-memory SQLite) |

## Data sources and phase priority

**United States:** Public ATS → USAJOBS → Adzuna → Indeed / Glassdoor / Google
Jobs / ZipRecruiter (the last four via JobSpy).
**Australia:** Public ATS → Adzuna → SEEK → Indeed Australia / Google Jobs.

One posting frequently appears on LinkedIn, Indeed and SEEK at the same time, so
cross-source deduplication is mandatory and runs on every insert (see below).

### Compliance boundary

- **LinkedIn is never enabled by default** and there is no cookie/login
  automation, captcha bypass or proxy rotation in this codebase.
- **SEEK is opt-in** (`ENABLE_SEEK=true`), rate-limited by
  `SEEK_REQUESTS_PER_MINUTE`, and only reads public search results.
- **RemoteOK is opt-in** and, per their request, the UI links back to the
  original posting; do not strip attribution when redistributing.
- Only job postings are stored. No candidate profiles or personal data.
- Review each source's terms with legal counsel before commercial use.

The stack is split into `compose.dev.yml` (hot reload, ports published) and
`compose.prod.yml` (built images, no bind mounts, internal data services).
`docker-compose.yml` just includes the dev file.

## Quick start (Docker, development)

```bash
cp .env.example .env          # adjust toggles / credentials
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up api worker beat web
```

`worker` runs the Celery worker and `beat` dispatches collections on an
interval. To use the APScheduler fallback instead (no Redis needed), run
`python -m apps.worker.main schedule` and drop the `worker`/`beat` services.

- Web UI: http://localhost:3000
- API docs: http://localhost:8000/docs · health: http://localhost:8000/health

## Quick start (Docker, production)

```bash
cp .env.prod.example .env.prod     # set POSTGRES_PASSWORD, API_KEY, CORS_ORIGINS...
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml run --rm api alembic upgrade head
```

Only `api` (8000) and `web` (3000) are published; Postgres/Redis/OpenSearch
stay on the internal network. Images run non-root and the frontend is a
multi-stage `next start` build.

## Quick start (local preview)

```bash
python -m venv .venv
.venv\Scripts\activate                    # Windows
pip install -e ".[dev]"

# SQLite preview with sample data (no collectors, no Postgres needed)
set DATABASE_URL=sqlite+pysqlite:///./.preview.db
set AUTO_CREATE_TABLES=true
python -m apps.worker.main seed-demo
uvicorn apps.api.main:app --port 8010

# frontend (separate terminal)
cd apps/web
npm install
set API_BASE_URL=http://127.0.0.1:8010
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010
npm run dev                       # http://localhost:3000
```

The browser never holds the API key: client writes go through the Next.js
proxy route (`app/api/proxy/[...path]`), which attaches the server-only
`API_KEY`. See [SECURITY.md](SECURITY.md).

Run tests (no database required):

```bash
pytest -q
ruff check .
```

## Worker CLI

```bash
# create tables without Alembic (dev convenience)
python -m apps.worker.main init-db

# insert sample jobs so the UI can be previewed without collecting
python -m apps.worker.main seed-demo

# public ATS boards are enabled by default (ENABLE_ATS=true)
python -m apps.worker.main collect --source greenhouse --source lever
python -m apps.worker.main collect --all

# opt-in sources (enable via env first)
set ENABLE_USAJOBS=true     &  python -m apps.worker.main collect --source usajobs --keywords "data engineer"
set ENABLE_JOBSPY=true      &  python -m apps.worker.main collect --source jobspy --keywords "analyst" --country US --sites "indeed,glassdoor,zip_recruiter"
set ENABLE_ADZUNA=true      &  python -m apps.worker.main collect --source adzuna --keywords "analyst" --country AU
set ENABLE_SEEK=true        &  python -m apps.worker.main collect --source seek --keywords "developer" --location "Melbourne VIC"

# run on a schedule (used by the docker worker service); also evaluates saved searches
python -m apps.worker.main schedule --all --interval-minutes 60

# evaluate saved searches once (records new matches for the /alerts page)
python -m apps.worker.main alerts --lookback-hours 24

# mark jobs inactive that have not been seen for STALE_JOB_DAYS (default 30)
python -m apps.worker.main sweep --days 30
python -m apps.worker.main enqueue-sweep

# (re)index jobs into OpenSearch (when SEARCH_BACKEND=opensearch)
python -m apps.worker.main reindex
python -m apps.worker.main enqueue-reindex

# dispatch to Celery/Redis instead of running inline (needs broker + worker)
python -m apps.worker.main enqueue --all
python -m apps.worker.main enqueue --source seek --keywords "developer" --location "Melbourne VIC"
python -m apps.worker.main enqueue-alerts --lookback-hours 24
```

### Celery + Redis

Consumers run with:

```bash
celery -A apps.worker.celery_app worker --loglevel=info --concurrency=2
celery -A apps.worker.celery_app beat   --loglevel=info
```

`jobagg.collect_all` fans out one `jobagg.collect_source` task per enabled
collector in parallel, then a chord body runs `jobagg.evaluate_alerts` once the
collection finishes (so alert emails go out after new jobs land). Individual
source tasks retry up to 3 times. The beat schedule runs every
`COLLECT_INTERVAL_MINUTES` using the default `COLLECT_KEYWORDS` /
`COLLECT_LOCATION` / `COLLECT_COUNTRY` / `COLLECT_RESULTS`, plus a `daily-digest`
entry at `DIGEST_HOUR_UTC` (via `jobagg.daily_digest`) for digest searches.

Which companies to poll for ATS sources lives in
[`config/ats_companies.json`](config/ats_companies.json). Entries are usually a
board token string, but some providers take objects:

```jsonc
{
  "workday":  [{ "tenant": "nvidia", "host": "wd5", "site": "NVIDIAExternalCareerSite" }],
  "personio": [{ "token": "acme", "domain": "jobs.personio.de" }],
  "teamtailor": [{ "token": "acme", "api_token": "...", "api_version": "20240404" }],
  "bamboohr": ["acme"],
  "jazzhr":   [{ "api_key": "...", "board": "acme.applytojob.com" }],
  "pinpoint": ["workwithus"],
  "rippling": ["spreeai"],
  "jobvite":  [{ "api": "...", "sc": "...", "site": "career-site-name" }]
}
```

Teamtailor, JazzHR and Jobvite require per-account credentials; entries without
them are skipped.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + database check |
| GET | `/api/v1/jobs` | Search: `q`, `source`, `country`, `state`, `city`, `company`, `remote_type`, `employment_type`, `min_salary`, `posted_after`, `currency`, `include_duplicates`, `sort` (`posted_at` \| `relevance` \| `salary_max` \| `first_seen_at`), `order`, `page`, `page_size` |
| GET | `/api/v1/jobs/{id}` | Single job |
| GET | `/api/v1/sources` | Known sources, which are enabled, per-source counts |
| GET | `/api/v1/stats` | Totals by source and country |
| GET | `/api/v1/fx` | FX base currency + rates used for salary display |
| GET | `/api/v1/runs` | Recent collector runs (`source`, `status`, `limit`) |
| GET | `/api/v1/runs/summary` | Per-source run health summary |
| GET | `/api/v1/jobs/export` | Export filtered jobs (`format=csv\|json\|xlsx`, `limit`) |
| POST | `/api/v1/match` | Score jobs against a résumé (`resume`, `limit`, `country`, `remote_type`) |
| GET | `/api/v1/saved-searches` | List saved searches |
| POST | `/api/v1/saved-searches` | Create a saved search |
| GET | `/api/v1/saved-searches/{id}` | Get one saved search |
| PATCH | `/api/v1/saved-searches/{id}` | Update name / email / frequency / active |
| DELETE | `/api/v1/saved-searches/{id}` | Delete a saved search and its matches |
| POST | `/api/v1/saved-searches/{id}/run` | Evaluate now and record new matches |
| GET | `/api/v1/saved-searches/{id}/matches` | Jobs matched by the search |
| GET | `/api/v1/saved-searches/unsubscribe?token=...` | Deactivate a saved search (email link) |

Example:

```bash
curl "http://localhost:8000/api/v1/jobs?q=python&country=AU&remote_type=remote&page_size=20"
curl -o jobs.csv "http://localhost:8000/api/v1/jobs/export?format=csv&q=python"
curl -o jobs.xlsx "http://localhost:8000/api/v1/jobs/export?format=xlsx&country=US"

curl -X POST "http://localhost:8000/api/v1/saved-searches" \
  -H "Content-Type: application/json" \
  -d '{"name":"AU data roles","keywords":"data","country":"AU"}'

curl -X POST "http://localhost:8000/api/v1/saved-searches/1/run"

# ranked full-text search (PostgreSQL)
curl "http://localhost:8000/api/v1/jobs?q=data%20engineer&sort=relevance"
```

### Full-text search

On PostgreSQL, `q` runs against a generated `search_vector` column over
title/company/description with a GIN index (migration `0003_full_text`;
`sort=relevance` ranks by `ts_rank`). On any other engine (e.g. SQLite in
tests) it transparently falls back to `ILIKE`, so the same query works
everywhere. `create_all()` / `init-db` create the column and index on
PostgreSQL too, so both the migration and dev bootstrap paths are covered.

### OpenSearch (optional, scale stage)

Set `SEARCH_BACKEND=opensearch` and `OPENSEARCH_URL` (the compose `opensearch`
service is already wired at `http://opensearch:9200`). The API then queries
OpenSearch and **falls back to PostgreSQL automatically on any error**, so
search keeps working if the cluster is unavailable. Documents come from the
`jobs` table; build/refresh the index with:

```bash
python -m apps.worker.main reindex          # one-off
python -m apps.worker.main enqueue-reindex  # via Celery
```

When OpenSearch is enabled, Celery beat also reindexes every 30 minutes. The
index mapping and query DSL live in `packages/search`.

### FX salary display

Salaries are always stored in their original currency. Pass `currency=USD` (or
`AUD`, …) to `/api/v1/jobs` and each item gains `salary_display_min/max`,
`salary_display_currency` and `salary_display_period`, converted with the
`FX_RATES` table (values of one unit in `FX_BASE_CURRENCY`). `GET /api/v1/fx`
exposes the current table. The web UI has a **Salary currency** selector.

### Enrichment and résumé matching

Every job is enriched on ingest with extracted **skills** and an extractive
**summary** (`packages/enrichment`, fully offline). Backfill or re-run with:

```bash
python -m apps.worker.main enrich --batch-size 500
python -m apps.worker.main enqueue-enrich
```

`POST /api/v1/match` scores recent jobs against a pasted résumé and is exposed
in the UI at `/match`. The same `enrich` run also computes a **semantic
embedding** per job (`jobs.embedding`), so matching blends the deterministic
skill/keyword score with cosine similarity (50/50) and reports both
(`engine` + `semantic_score`).

Embeddings come from a pluggable provider (`packages/semantic`):

- `LLM_PROVIDER=local` (default) — dependency-free deterministic hashing, fully
  offline.
- `LLM_PROVIDER=openai` (or `auto`) with `LLM_API_KEY` — any OpenAI-compatible
  `/embeddings` endpoint (model via `LLM_MODEL`, base URL via `LLM_BASE_URL`).

If no job has an embedding yet, `/match` transparently reports
`engine: keyword`; re-run `enrich` after enabling a provider to populate them.

The top `RERANK_TOP_K` candidates are then **reranked** by a cross-encoder and
blended 50/50 with the earlier score (`rerank_score`, `reranked: true`).
`RERANK_PROVIDER=local` is an offline lexical reranker;
`RERANK_PROVIDER=http` + `RERANK_API_KEY` uses a Cohere/Jina-style `/rerank`
endpoint. Set `ENABLE_RERANK=false` to skip this stage.

### LLM-generated summaries

Enrichment stores a deterministic extractive summary by default. With
`ENABLE_LLM_SUMMARIES=true`, `LLM_PROVIDER=openai` and an `LLM_API_KEY`, run:

```bash
python -m apps.worker.main summaries --batch-size 50
python -m apps.worker.main enqueue-summaries
```

Each job's `summary` is replaced by a 2-3 sentence LLM summary and
`summary_source` becomes `llm` (re-running is idempotent).

### Saved-search email alerts

The `/alerts` page lists every saved search with its frequency, last-run and
last-notified times, and lets you **Run now**, **Pause/Resume** or **Delete** it.
A `/status` page shows collector run history and per-source health
(`GET /api/v1/runs`, `GET /api/v1/runs/summary`).

### Webhook delivery

Set a `webhook_url` on a saved search (UI or API) to receive a `POST` with
`{"event": "saved_search.matches", "saved_search": {...}, "new_matches": N,
"jobs": [...]}` whenever new matches appear. Delivery is gated by
`ENABLE_WEBHOOKS`, times out after `WEBHOOK_TIMEOUT_SECONDS` and includes at
most `WEBHOOK_MAX_JOBS` jobs. Only absolute `http(s)` URLs are accepted.

`webhook_kind` controls the body shape:

- `generic` (default) — the JSON payload above.
- `slack` — Slack incoming-webhook `{"text": ...}` with links.
- `teams` — Microsoft Teams `MessageCard` payload.

The same value is set per saved search in the UI or via the API.

Matches are always stored (shown on `/alerts`). To also email them, set the
`ENABLE_EMAIL_ALERTS`, `SMTP_*`, `ALERT_FROM_EMAIL` and `WEB_BASE_URL` variables.
Each saved search has a `frequency` of `immediate` (send per run) or `digest`
(one combined email of everything matched since the last send), plus an
unsubscribe link that deactivates the search via `/unsubscribe`. The worker
sends one email per saved search that has a `notify_email` and new matches:

```bash
python -m apps.worker.main alerts --lookback-hours 24   # evaluate + email
python -m apps.worker.main schedule --all               # does this after each collection
```

Sending uses the Python standard library (`smtplib`) — no extra package. For
local testing point `SMTP_HOST`/`SMTP_PORT` at a catcher such as Mailpit or
MailHog. If SMTP is not configured the worker logs and skips sending.

## Unified data model

The `jobs` table stores one row per source posting with the canonical fields:
`source`, `source_job_id`, `canonical_url`, `apply_url`, `title`, `company`,
`description`, `country`, `state`, `city`, `remote_type`, `employment_type`,
`salary_min`, `salary_max`, `salary_currency`, `salary_period`, `posted_at`,
`first_seen_at`, `last_seen_at`, `expires_at`, `content_hash`, `dedup_key`,
`raw_payload`.

USD and AUD are **never mixed**: the original amount and currency are stored,
and a single display currency can be derived at query/render time via an FX
rate.

### Job lifecycle

`is_active`, `last_seen_at`, `closed_at` and `inactive_reason` track liveness.
Two complementary mechanisms:

- **Per-board (accurate):** full-board ATS sources record `last_seen_run_id`.
  After a *complete* successful board run (fewer results than the requested
  cap, so the board was fully enumerated), jobs that did not appear get
  `missing_runs += 1`; after `MISSING_RUN_THRESHOLD` consecutive misses they are
  closed with `inactive_reason="missing"`. Keyword-search sources are excluded.
- **Time-based (backstop):** jobs not seen for `STALE_JOB_DAYS` are deactivated
  by the `sweep` task (`jobagg.sweep_stale`, also on the daily beat).

Re-seeing a job clears `closed_at`/`inactive_reason` and reactivates it.
Inactive jobs are excluded from search.

### Three-layer deduplication

1. **Exact** — unique constraint on `(source, source_job_id)`; re-seen jobs are
   updated in place and their `last_seen_at` is refreshed.
2. **Link** — canonicalised apply URL (tracking params, `www`, fragments and
   trailing slashes removed) via `canonical_url_hash`.
3. **Cross-platform** — `company + title + city + description_hash` via
   `dedup_key`; duplicates get `duplicate_of` pointing at the canonical row and
   are hidden from search by default.

Implementation: [`packages/deduplication`](packages/deduplication) and
[`apps/worker/pipeline.py`](apps/worker/pipeline.py).

## Project layout

```text
.
├── apps/
│   ├── api/                 # FastAPI service, SQLAlchemy models, settings
│   ├── worker/              # pipeline, Celery app/tasks, CLI + fallback scheduler
│   └── web/                 # Next.js + TypeScript search UI
├── collectors/
│   ├── ats_adapters/        # Greenhouse, Lever, Ashby, Workable,
│   │                        # SmartRecruiters, Recruitee, Breezy HR,
│   │                        # Workday, Personio, Teamtailor,
│   │                        # BambooHR, JazzHR, Pinpoint,
│   │                        # Rippling, Jobvite
│   ├── jobspy_adapter/      # Indeed / Glassdoor / Google
│   ├── adzuna_adapter/      # Adzuna official API (US + AU, opt-in)
│   ├── remoteok_adapter/    # RemoteOK public feed (opt-in)
│   ├── seek_adapter/        # SEEK (AU, opt-in)
│   └── usajobs_adapter/     # USAJOBS official API
├── packages/
│   ├── job_schema/          # unified NormalizedJob model + enums
│   ├── deduplication/       # normalisation + dedup keys
│   ├── ranking/             # keyword / recency scoring
│   ├── fx/                  # currency conversion for salary display
│   ├── enrichment/          # skills, summaries, résumé match score
│   ├── semantic/            # embeddings, cosine, cross-encoder rerankers
│   ├── llm/                 # OpenAI-compatible chat client (summaries)
│   └── search/              # optional OpenSearch index + query DSL
├── migrations/              # Alembic
├── config/                  # ATS board tokens
├── tests/
├── docker-compose.yml
└── requirements.txt
```

## Security

See [SECURITY.md](SECURITY.md). Highlights:

- **Set `API_KEY` before exposing the API.** Write endpoints then require the
  `X-API-Key` header; the web app forwards `API_KEY`/`NEXT_PUBLIC_API_KEY`.
- Write and export endpoints are rate-limited; `CORS_ORIGINS=*` is rejected when
  `ENVIRONMENT=production`.
- Webhooks are **off by default**, block loopback/private/link-local/metadata
  targets (validated at save *and* send time), do not follow redirects, support
  a host allowlist and an optional `X-JobAgg-Signature` HMAC.
- LinkedIn/SEEK scrapers stay disabled unless explicitly enabled.

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)):
authentication/abuse (`API_KEY`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_PER_MINUTE`,
`MATCH_RATE_LIMIT_PER_MINUTE`), database/Redis URLs, collector toggles
(`ENABLE_ATS`, `ENABLE_USAJOBS`,
`ENABLE_JOBSPY`, `ENABLE_ADZUNA`, `ENABLE_REMOTEOK`, `ENABLE_SEEK`,
`ENABLE_LINKEDIN`), USAJOBS/Adzuna credentials, the ATS board file, SMTP settings
for email alerts, `WEB_BASE_URL` (links inside emails), Celery/Redis
(`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `COLLECT_*`), FX
(`FX_BASE_CURRENCY`, `FX_RATES`), `ENRICHMENT_ENABLED`, semantic matching
(`ENABLE_SEMANTIC_MATCH`, `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`,
`LLM_BASE_URL`), reranking (`ENABLE_RERANK`, `RERANK_PROVIDER`,
`RERANK_API_KEY`, `RERANK_TOP_K`), LLM summaries (`ENABLE_LLM_SUMMARIES`,
`LLM_SUMMARY_MODEL`), webhooks (`ENABLE_WEBHOOKS`, `WEBHOOK_TIMEOUT_SECONDS`, `WEBHOOK_MAX_JOBS`,
`WEBHOOK_ALLOWED_HOSTS`, `WEBHOOK_ALLOW_PRIVATE`, `WEBHOOK_SIGNING_SECRET`),
job lifecycle (`STALE_JOB_DAYS`), `DIGEST_HOUR_UTC`, the search backend (`SEARCH_BACKEND`, `OPENSEARCH_URL`,
`OPENSEARCH_INDEX`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`), user agent,
HTTP timeout and the SEEK rate limit.

## Roadmap

- Per-source reliability: exponential backoff/jitter, `Retry-After`, per-host
  concurrency caps, circuit breaker and source health scores.
- Contract tests with recorded fixtures per adapter; detect schema drift and
  distinguish "no jobs" from "parser broke".
- Fuzzy/deterministic-ATS dedup tiers with `duplicate_reason`/`duplicate_score`
  and source aliases; manual merge/split.
- Rename the default hashing embedder to `lexical-hash`, add a TF-IDF/BM25
  baseline and store `embedding_provider/model/version/content_hash`.
- Job-seeker workflow: saved/applied/hidden states, application Kanban, notes,
  reminders, skill-gap analysis.
- Dependency/tooling: adopt a lock file (`uv.lock` or hashed pip-tools output),
  add `pip-audit`/`npm audit` and image scanning to CI, pin image digests.
- FX rates with source/timestamp, scheduled refresh and staleness handling.
- LinkedIn as an optional, carefully-reviewed source (kept disabled by default).

## Version control & CI

Git is initialized with an initial commit, and GitHub Actions
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs:

- `ruff check .` and `pytest -q` (Python 3.13)
- `npm ci && npm run typecheck && npm run build` (Node 22)
- an Alembic `upgrade → downgrade base → upgrade` migration test against PostgreSQL

Dependabot is configured for pip, npm, GitHub Actions and Docker.
