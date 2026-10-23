# Security

This project is a self-hostable job aggregation platform. It ships with safe
defaults but a few decisions are deployment responsibilities.

## Authentication

- **Set `API_KEY` before exposing the API beyond localhost.** When set, all
  write endpoints (create/update/delete/run saved searches, `POST /match`)
  require the `X-API-Key` header. When unset, those endpoints **fail closed**
  (HTTP 503) — they are not silently open.
- The browser never holds the key. Client-initiated writes go to the same-origin
  Next.js route handler (`app/api/proxy/[...path]`), which attaches the
  server-only `API_KEY` before calling FastAPI. Do **not** reintroduce a
  `NEXT_PUBLIC_API_KEY`: every `NEXT_PUBLIC_*` value is shipped to the browser.
- **Members register and log in with a verified phone number.** `/register` and
  `/login` use SMS one-time codes; the API stores E.164 phone identity and saved
  searches are scoped to the signed-in member. Configure `SMS_PROVIDER=twilio`,
  `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID`, and a
  long random `SESSION_SECRET` before enabling registration.
- **The operator account remains separate.** `/admin/login` uses
  `WEB_UI_USERNAME` and `WEB_UI_PASSWORD`. Administrative proxy routes require
  an operator session; member sessions can access only member saved-search and
  résumé-match routes. Cross-site state-changing requests are rejected by an
  Origin check and `SameSite=Lax` cookies.
- In `ENVIRONMENT=production` the API **refuses to start** if any of these are
  unsafe: `API_KEY` unset, `CORS_ORIGINS=*`, a default/weak database password,
  `WEBHOOK_ALLOW_PRIVATE=true`, or `AUTO_CREATE_TABLES=true`. See
  `check_production_settings` in `apps/api/config.py`.
- Never run with `CORS_ORIGINS=*` in production; the API refuses to start in
  `ENVIRONMENT=production` if it is still a wildcard.

## Abuse prevention

- In-process sliding-window rate limits apply to `POST /match`, saved-search
  `run`, and export (`RATE_LIMIT_PER_MINUTE`, `MATCH_RATE_LIMIT_PER_MINUTE`).
  A missing `API_KEY` plus a public port is the main risk (writes fail closed
  without it). For multiple replicas, back the limiter with Redis.

## Outbound webhooks (SSRF)

- Webhooks are **disabled by default** (`ENABLE_WEBHOOKS=false`).
- Target URLs are validated at save time (scheme) and again immediately before
  sending: resolved IPs must not be loopback, private, link-local, multicast,
  reserved or unspecified. Redirects are not followed.
- Restrict destinations with `WEBHOOK_ALLOWED_HOSTS` (comma-separated).
  `WEBHOOK_ALLOW_PRIVATE=true` is an explicit escape hatch for trusted internal
  receivers and should be avoided on public deployments.
- Set `WEBHOOK_SIGNING_SECRET` to attach an `X-JobAgg-Signature` HMAC-SHA256
  header so receivers can verify authenticity.

## Data sources / compliance

- LinkedIn and SEEK scrapers are disabled by default and must be enabled
  deliberately. Review each source's terms before commercial use.

## Reporting

Report vulnerabilities privately to the maintainer rather than opening a public
issue. Include reproduction steps and impact.
