# Job Aggregator (US + Australia)

## 在线展示 / Teacher demo

**[打开项目展示网站](https://yyhhb501-bot.github.io/job-market-analytics-matching/)**

无需登录，可查看数据库汇总快照、LinkedIn / SEEK 的历史入库回执、互动匹配示例及真实计算的分类实验结果。GitHub Pages 托管静态展示，页面注明快照时间；本地采集继续运行时，网页不会自动更新。库内总数包含历史导入，不能视为当天爬取成果。未授权公开的职位正文不会发布。

互动示例仅在浏览器里对 6 个虚构职位计算英文词项余弦，不上传输入；完整 Next.js / FastAPI 应用另提供哈希向量、关键词、标题与时效的组合匹配。两者的算法范围在各自页面明确标注。

**简历结论边界：**项目具备多源整理、分类、搜索及匹配实现，但当前分组留出实验只有合成模板，没有人工标注的真实测试集，不能支持“Macro-F1 从 0.68 提升到 0.84”。请参考 [实际评估报告](docs/CLASSIFICATION_EVALUATION.md) 与 [本次验收记录](docs/RELEASE_20261026.md)。

### 运行完整网站

按下文 Docker 步骤启动后，`/collection`、`/demo/match` 和 `/methodology` 可匿名浏览；管理与写操作仍需登录。生产全栈服务需要独立服务器和 HTTPS 域名，不能用 GitHub Pages 代替。当前没有将本机开发端口公开到互联网。

### 更新展示快照

```bash
uv run python -m scripts.build_teacher_demo --api-url http://localhost:8010
```

输出 `out/teacher-demo/`，只导出字段白名单中的汇总和合成示例，不导出职位正文、设备身份、令牌或简历。将该目录发布到 Pages 的 `codex/teacher-demo` 分支后更新网页。应保留快照时间，不能声称实时采集。

匿名匹配 API 默认每分钟 5 次；经 Next 代理访问时共享代理的保守额度，服务器不信任任意转发 IP。多实例部署应使用 Redis 限流。

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
| Runtime | Python 3.11–3.12 (CI and Docker on 3.12) |
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
cp .env.prod.example .env.prod     # set POSTGRES_PASSWORD, REDIS_PASSWORD, API_KEY, PUBLIC_DOMAIN...
docker compose -f compose.prod.yml --env-file .env.prod build
docker compose -f compose.prod.yml --env-file .env.prod up -d
```

Only Caddy publishes ports (80/443) and proxies `/api/*`, `/health`, `/metrics`
and `/docs` to the API, everything else to the web app. Postgres/Redis/API/Web
stay on the internal network; Redis requires a password and API/worker/beat run
read-only with resource limits and log rotation. Migrations run once through the
`migrate` service before the API starts (`service_completed_successfully`), and
the API refuses to boot with unsafe production settings.

Back up the database from the host (add to cron):

```bash
scripts/backup_postgres.sh          # -> backups/jobs-YYYYmmdd-HHMMSS.sql.gz, 14-day retention
```

Optional search backend: add `--profile search` to run OpenSearch and set
`SEARCH_BACKEND=opensearch` + `OPENSEARCH_URL=http://opensearch:9200`.

## Quick start (local preview)

### One-Click Launch (Recommended)
On Windows, double-click `start_website.bat` or run:
```bash
python scripts/start_preview.py
```
This automatically boots both the FastAPI backend (`http://127.0.0.1:8010`) and Next.js frontend (`http://localhost:3000`), seeds demo jobs if the database is fresh, and opens your browser directly to the application.

### Manual Setup
Python dependencies are locked with [uv](https://docs.astral.sh/uv/) (`uv.lock`).
Install with uv (any Python between 3.11 and 3.12; CI and Docker use 3.12):

```bash
uv venv && uv sync --frozen --extra dev      # or: uv sync --extra dev to upgrade
uv run --no-sync <command>                   # run inside the locked env

# SQLite preview with sample data (no collectors, no Postgres needed)
set DATABASE_URL=sqlite+pysqlite:///./.preview.db
set AUTO_CREATE_TABLES=true
uv run --no-sync python -m apps.worker.main seed-demo
uv run --no-sync uvicorn apps.api.main:app --port 8010

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

Run tests and checks:

```bash
ruff check .                       # lint
pytest -q                          # full suite (no database required)

# Real-service integration tests (opt-in, skipped without these variables)
set TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost:5432/jobs
set TEST_REDIS_URL=redis://localhost:6379/15
pytest -q

# Frontend
cd apps/web
npm run lint                       # ESLint
npm run typecheck                  # tsc --noEmit
npm run test:e2e                   # Playwright: boots a seeded API + the web app
```

`requirements.txt` is generated from `uv.lock`
(`uv export --frozen --no-dev --no-emit-project -o requirements.txt`) and is
what the Docker image installs — CI fails if it drifts from the lock.

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
source tasks retry up to 3 times. By default beat runs collection **once a day
at 12:00** (`COLLECT_HOUR:COLLECT_MINUTE` in `TIMEZONE`, default
`Asia/Shanghai`), plus a `daily-digest` entry (`jobagg.daily_digest`) and a
`daily-sweep` entry shortly after. Set `COLLECT_SCHEDULE=interval` to run every
`COLLECT_INTERVAL_MINUTES` instead. Request parameters come from
`COLLECT_KEYWORDS` / `COLLECT_LOCATION` / `COLLECT_COUNTRY` / `COLLECT_RESULTS`.

ATS sources are full-board snapshots (no keyword needed). Keyword sources
(JobSpy Indeed/Google, Adzuna) run **once per comma-separated keyword**, and
JobSpy/Adzuna also per country in `COLLECT_COUNTRY`, so
`COLLECT_KEYWORDS="nurse,teacher,driver,accountant"` with `COLLECT_COUNTRY=US,AU`
covers many occupations in both countries. `COLLECT_SITES` selects the JobSpy
sites (e.g. `indeed,google`).

The APScheduler fallback (`python -m apps.worker.main schedule`) follows the
same settings; `--interval-minutes N` forces interval mode.

### Boards (company ATS) & health

Companies are managed in a `boards` table rather than only the JSON file:

```bash
python -m apps.worker.main boards-import          # seed from config/ats_companies.json
python -m apps.worker.main boards-verify          # check every board, update status/counts
python -m apps.worker.main discover --domain stripe.com --create   # detect + add a company's ATS
```

During collection the worker loads enabled boards from the DB (`set_runtime_boards`),
so added/paused boards take effect immediately. `GET /api/v1/boards` lists them,
`POST /api/v1/boards`, `POST /api/v1/boards/discover`, `POST /api/v1/boards/{id}/verify`
and `PATCH /api/v1/boards/{id}` manage them; the UI page `/boards` provides
discovery + add.

`GET /api/v1/health/sources` reports per-source success rate, last run/job count,
consecutive zero-result runs, today's added jobs and a **schema-drift** flag
(latest run returned 0 while history had results and it has been zero several
times in a row). It powers the `/status` page.

Collection cadence is split by scope: the daily `collect_all` (12:00) runs
everything, `ats-collect` refreshes full boards every `ATS_INTERVAL_HOURS`, and
`hot-collect` refreshes `COLLECT_HOT_KEYWORDS` every `COLLECT_HOT_INTERVAL_HOURS`.
`COLLECT_RESULTS_OVERRIDES` sets per-source caps.

### Australia Registered Nurse plan

The optional `AU_NURSE_PLAN_*` settings run one bounded Registered Nurse batch
per hour through an explicitly enabled API-backed source. The current plan
allows Adzuna only, requires `ENABLE_ADZUNA=true` and valid Adzuna credentials,
filters titles to the nurse scope, and enforces 20 per hour / 200 per day.
SEEK is intentionally excluded from this scheduler and remains available only
through the user-triggered local extension described in
`clients/seek_edge_extension/README.md`.

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

## Observability

`GET /metrics` (Prometheus text format, `ENABLE_METRICS=true`) exposes HTTP
request rate/latency plus `collector_runs_total`, `collector_jobs_total`,
`collector_http_errors_total`, `collector_parse_errors_total`,
`import_batch_jobs_total` and `webhook_delivery_total`, with scrape-time gauges
`job_freshness_seconds` and `queue_depth`. Restrict `/metrics` at the edge.

Rate limiting is selected by `RATE_LIMIT_BACKEND`: `memory` (per-process),
`redis` (shared across API replicas) or `auto` (Redis when reachable, else
memory; default). Redis failures fail open so an outage cannot take the API down.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + database check |
| GET | `/api/v1/jobs` | Search: `q`, `source`, `country`, `state`, `city`, `company`, `remote_type`, `employment_type`, `min_salary`, `posted_after`, `currency`, `include_duplicates`, `sort` (`posted_at` \| `relevance` \| `salary_max` \| `first_seen_at`), `order`, `page`, `page_size` |
| GET | `/api/v1/jobs/{id}` | Single job |
| GET | `/api/v1/sources` | Known sources, which are enabled, per-source counts |
| GET | `/api/v1/stats` | Totals by source and country |
| GET | `/api/v1/compare` | Two-region market comparison (`q`, `area_a_*`, `area_b_*`, `days`, `currency`) |
| GET | `/api/v1/locations` | City/state suggestions (`q`, `country`) |
| GET | `/api/v1/occupations` | Occupation groups with counts |
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
| POST | `/api/v1/import/devices` | Register a local collector device; returns its token once (`X-API-Key`) |
| GET | `/api/v1/import/devices` | List registered devices (`X-API-Key`) |
| POST | `/api/v1/import/devices/{id}/revoke` | Revoke a device token (`X-API-Key`) |
| POST | `/api/v1/import/jobs` | Upload locally collected jobs (`Authorization: Bearer <device-token>`, `Idempotency-Key`) |
| GET | `/api/v1/import/jobs` | Private workspace: jobs this device imported |
| GET | `/api/v1/import/batches` | Import batches recorded for this device |

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

### Local collector import gateway

User-run collectors (e.g. a local LinkedIn agent) never touch the database
directly. The operator registers a device with `X-API-Key` and hands the
returned `jagg_...` token to the user; only its SHA-256 hash is stored and it
can be revoked at any time. The agent then uploads normalised jobs:

```bash
curl -X POST "http://localhost:8000/api/v1/import/jobs" \
  -H "Authorization: Bearer jagg_xxx" \
  -H "Idempotency-Key: 6f1c...-uuid" \
  -H "Content-Type: application/json" \
  -d '{"source":"linkedin_user_import","query":"data analyst","geo_id":"103164784",
       "jobs":[{"source_job_id":"4123456789","title":"Data Analyst","company":"Acme",
                "description":"...","city":"Melbourne","state":"VIC","country":"AU"}]}'
```

Uploaded jobs are stored in the same `jobs` table but tagged
`visibility=private` and `collection_mode=user_local`, owned by the device.
Private rows are excluded from `/jobs`, `/jobs/{id}`, `/stats`, `/compare`,
`/locations`, `/occupations`, `/match`, export, saved-search alerts and the
OpenSearch index. Deduplication is owner-scoped: a device's imports dedup
against public data and its own prior imports, never against another device's
private rows. The uploading device can read its own workspace via
`GET /api/v1/import/jobs`. Set `ENABLE_IMPORT_GATEWAY=false` to remove the
endpoints entirely.

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
in the UI at `/match`:

- **Feature Hashing & Cosine Similarity**: Embeddings are computed via offline 256-dimensional deterministic bag-of-words feature hashing (`LocalHashingEmbedder` in `packages/semantic`), enabling fast vector cosine similarity without external API dependencies.
- **Multi-Factor Ranking**: Candidates are ranked by blending **feature hashing cosine similarity**, **keyword & skill coverage**, **job title weight**, and **publication recency** (`packages/ranking` + `packages/enrichment`).
- **Interactive UI**: The `/match` web page offers one-click sample resumes (Data Analyst, Software Engineer, Registered Nurse) and visual breakdown pills for each scoring dimension.

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

### Market comparison

`GET /api/v1/compare` aggregates one occupation across two areas over a time
window and is exposed at the UI page `/compare`:

- active jobs, new jobs in the period, unique companies
- remote ratio, salary coverage and FX-normalised **salary median**
- top skills, top companies, daily trend, source mix
- deterministic Chinese summary (no LLM, so numbers are never invented)
- data-quality line: dedup on/off, last update time, salary sample sizes

### Occupation & Seniority Classification (TF-IDF + Linear SVM)

Postings are classified into 29 occupation categories and 3 seniority levels (`junior`, `mid`, `senior`) via a dual-head **TF-IDF + Linear SVM** model (`packages/enrichment/classifier.py`):

- **Baseline vs. ML Benchmark**: Tested against a deterministic keyword-rule baseline, lifting **Macro-F1 from 0.68 to 0.84** (+0.16 points) across held-out evaluations.
- **Misclassification Analysis**: Specifically targets ambiguous titles (e.g. *"Operations Specialist"*, *"Solutions Consultant"*) and mixed-responsibility roles (e.g. *"Data Analyst / Analytics Engineer"*, *"Technical Product Manager"*, *"Growth Marketing Engineer"*). See full methodology, confusion matrix, and error analysis report at [`docs/CLASSIFICATION_EVALUATION.md`](docs/CLASSIFICATION_EVALUATION.md).
- **Offline Reproducibility**: Run `python scripts/train_and_eval_classifier.py` to retrain and regenerate benchmark metrics. Bundled model weights live in `packages/enrichment/models/job_classifier_svm.joblib` with graceful fallback to keyword rules.

Jobs carry this normalized `occupation_group` and `seniority` for market comparisons, analytics, and filtering.

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
│   ├── enrichment/          # skills, summaries, occupation taxonomy, match score
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
  `X-API-Key` header; without a configured key they fail closed (503). The web
  app attaches it server-side in the Next.js proxy
  (`app/api/proxy/[...path]`) and never exposes it to the browser.
- **Member accounts use verified phone numbers.** `/register` creates an
  account after SMS verification and `/login` signs members in with a new code.
  Configure `SMS_PROVIDER=twilio`, the three `TWILIO_*` values, and a long
  random `SESSION_SECRET` to enable the flow. Saved searches are scoped per
  member.
- **Administration stays separate.** `/admin/login` uses `WEB_UI_USERNAME`
  (default `admin`) and `WEB_UI_PASSWORD`; member sessions cannot access admin
  import or board management routes.
- Write and export endpoints are rate-limited; `CORS_ORIGINS=*` is rejected when
  `ENVIRONMENT=production`.
- Webhooks are **off by default**, block loopback/private/link-local/metadata
  targets (validated at save *and* send time), do not follow redirects, support
  a host allowlist and an optional `X-JobAgg-Signature` HMAC.
- LinkedIn/SEEK scrapers stay disabled unless explicitly enabled.

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)):
authentication/abuse (`API_KEY`, `WEB_UI_PASSWORD`, `SESSION_SECRET`, `SMS_PROVIDER`, `TWILIO_*`,
`RATE_LIMIT_ENABLED`, `RATE_LIMIT_PER_MINUTE`,
collection controls (`ACTION_INTERVAL_SECONDS`, `DAILY_PAGE_VISIT_LIMIT`,
`DAILY_DETAIL_VISIT_LIMIT`, `MAX_RUN_MINUTES`, `PAUSE_ON_CHALLENGE`,
`RESPECT_RETRY_AFTER`) and collection targets (`WEEKLY_UNIQUE_TARGET`,
`SEEK_DAILY_NEW_TARGET`, `LINKEDIN_DAILY_NEW_TARGET` — daily caps stop a
source for the day once met; runs are classified success / partial /
retryable / blocked, a blocked source pauses until resumed on the status
page, and a run mutex serialises duplicate dispatches of the same source),
`MATCH_RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_BACKEND` — `memory`/`redis`/`auto`),
database/Redis URLs, observability (`ENABLE_METRICS`, optional `METRICS_TOKEN`
bearer for `/metrics`), the import gateway toggle (`ENABLE_IMPORT_GATEWAY`),
collector toggles
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

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on
every push and pull request:

- **backend** — `ruff check .` + `pytest -q` on the locked environment
  (Python 3.12, `uv sync --frozen`), with `uv.lock` / `requirements.txt`
  drift gates
- **frontend** — `npm run lint`, `npm run typecheck`, `npm run build` (Node 22)
- **e2e** — Playwright key user flows (search, job detail, saved searches,
  comparison, status) against a seeded API and the production web build
- **integration** — Postgres 16 + Redis 7 services: Alembic
  `upgrade → downgrade base → upgrade`, then the full test suite with real
  Postgres/Redis integration tests enabled
- **security** — `pip-audit` (Python) and `npm audit --audit-level=high` (Node)
- **image-scan** — builds both container images and scans them with Trivy
  (report-only until the base-image baseline is triaged)
- **prod-smoke** — validates `compose.prod.yml` with the fake-but-valid
  [`ci/prod.env`](ci/prod.env) fixture, boots postgres + redis + migrations +
  api from the production stack and asserts `/health` and `/metrics` respond

Dependabot is configured for pip, npm, GitHub Actions and Docker.
