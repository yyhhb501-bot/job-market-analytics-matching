/**
 * Operator session helpers for the web UI.
 *
 * Until a real identity system exists (users/tenants/RBAC), the write proxy
 * is gated behind a single shared operator password: `WEB_UI_PASSWORD`.
 * A successful login sets an HMAC-signed, HttpOnly session cookie that the
 * proxy (and the middleware guarding management pages) verifies.
 *
 * Keep this file Edge-runtime compatible: the middleware runs on the Edge
 * runtime, so only Web Crypto APIs are used here.
 */

export const SESSION_COOKIE = "jagg_session";

const SESSION_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours
const SESSION_TTL_SECONDS = SESSION_TTL_MS / 1000;

function webUiPassword(): string {
  return process.env.WEB_UI_PASSWORD ?? "";
}

export function loginEnabled(): boolean {
  return webUiPassword().length > 0;
}

export function memberSessionEnabled(): boolean {
  return Boolean(process.env.SESSION_SECRET);
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(message),
  );
  return Array.from(new Uint8Array(signature))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function sessionSecret(): Promise<string> {
  const explicit = process.env.SESSION_SECRET;
  if (explicit) return explicit;
  // Fall back to a secret derived from the password so deployments work with
  // a single env var; rotating the password then also invalidates sessions.
  return hmac("jagg-session-secret", webUiPassword());
}

async function signedToken(payload: string): Promise<string> {
  const signature = await hmac(await sessionSecret(), payload);
  return `${payload}.${signature}`;
}

export async function createSessionToken(): Promise<string> {
  const expires = Date.now() + SESSION_TTL_MS;
  // Keep the existing operator token format valid for already active sessions.
  return signedToken(`jagg-session:${expires}`);
}

export async function createMemberSessionToken(member: { id: number; phone: string }): Promise<string> {
  if (!memberSessionEnabled()) throw new Error("SESSION_SECRET must be set for member sessions");
  const expires = Date.now() + SESSION_TTL_MS;
  return signedToken(`member|${member.id}|${encodeURIComponent(member.phone)}|${expires}`);
}

export type SessionIdentity =
  | { kind: "operator" }
  | { kind: "member"; id: number; phone: string };

export async function readSessionToken(
  token: string | undefined | null
): Promise<SessionIdentity | null> {
  if (!token) return null;
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  const payload = token.slice(0, dot);
  const given = token.slice(dot + 1);
  const member = /^member\|(\d+)\|([^|]+)\|(\d+)$/.exec(payload);
  const legacy = /^jagg-session:(\d+)$/.exec(payload);
  if (!member && !legacy) return null;
  const expires = Number(member?.[3] ?? legacy?.[1]);
  if (!Number.isFinite(expires) || expires <= Date.now()) return null;
  const expected = await hmac(await sessionSecret(), payload);
  if (given.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) {
    diff |= expected.charCodeAt(i) ^ given.charCodeAt(i);
  }
  if (diff !== 0) return null;
  if (!member) return { kind: "operator" };
  try {
    return {
      kind: "member",
      id: Number(member[1]),
      phone: decodeURIComponent(member[2]),
    };
  } catch {
    return null;
  }
}

export async function verifySessionToken(
  token: string | undefined | null
): Promise<boolean> {
  return (await readSessionToken(token)) !== null;
}

/** Reject cross-site state-changing requests even with a stolen cookie. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true; // non-browser client; cookie SameSite still applies
  const host =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * Whether the session cookie may carry the `Secure` attribute.
 *
 * Deriving it from NODE_ENV breaks any deployment served over plain HTTP
 * (local preview, E2E, an internal host): the browser silently drops a
 * `Secure` cookie there and login appears to succeed but never authenticates.
 * Decide from the actual request protocol instead — Caddy/any reverse proxy
 * sets `X-Forwarded-Proto` — and allow an explicit override for operators who
 * terminate TLS somewhere this app cannot see.
 */
export function shouldUseSecureCookie(request?: Request): boolean {
  const override = process.env.COOKIE_SECURE?.toLowerCase();
  if (override === "true") return true;
  if (override === "false") return false;
  const forwarded = request?.headers.get("x-forwarded-proto");
  if (forwarded) return forwarded.split(",")[0]?.trim() === "https";
  const url = request?.url;
  return url ? url.startsWith("https://") : false;
}

export function sessionCookieOptions(request?: Request): {
  httpOnly: true;
  sameSite: "lax";
  secure: boolean;
  path: "/";
  maxAge: number;
} {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: shouldUseSecureCookie(request),
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  };
}

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}
