# Security

This project is a self-hostable job aggregation platform. It ships with safe
defaults but a few decisions are deployment responsibilities.

## Authentication

- **Set `API_KEY` before exposing the API beyond localhost.** When set, all
  write endpoints (create/update/delete/run saved searches, `POST /match`)
  require the `X-API-Key` header. When unset they are open, which is intended
  for local development only.
- The web app forwards a key via `API_KEY` (server) and `NEXT_PUBLIC_API_KEY`
  (browser). `NEXT_PUBLIC_*` is visible to anyone who can load the page — only
  acceptable for a single-user, self-hosted deployment. For multi-user use,
  put the API behind an authenticating reverse proxy or add real user accounts.
- Never run with `CORS_ORIGINS=*` in production; the API refuses to start in
  `ENVIRONMENT=production` if it is still a wildcard.

## Abuse prevention

- In-process sliding-window rate limits apply to `POST /match`, saved-search
  `run`, and export (`RATE_LIMIT_PER_MINUTE`, `MATCH_RATE_LIMIT_PER_MINUTE`).
  Empty `API_KEY` plus a public port is the main risk. For multiple replicas,
  back the limiter with Redis.

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
