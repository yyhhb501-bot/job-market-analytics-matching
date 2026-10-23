import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  readSessionToken,
  sameOrigin,
} from "@/lib/session";

/**
 * Server-side proxy for browser-initiated write requests.
 *
 * The API key never reaches the browser: client components call this route and
 * it attaches `API_KEY` (server env) before forwarding to FastAPI. Only the
 * exact method + path combinations the UI needs are allowed.
 *
 * Operator-only paths require an operator session. Member saved searches are
 * scoped by the verified member id from the signed, HttpOnly session cookie.
 */

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

const RULES: { method: string; test: (path: string) => boolean }[] = [
  { method: "GET", test: (p) => p === "import/admin" },
  { method: "GET", test: (p) => p === "saved-searches" },
  { method: "GET", test: (p) => /^saved-searches\/\d+(\/matches)?$/.test(p) },
  { method: "POST", test: (p) => p === "saved-searches" },
  { method: "PATCH", test: (p) => /^saved-searches\/\d+$/.test(p) },
  { method: "DELETE", test: (p) => /^saved-searches\/\d+$/.test(p) },
  { method: "POST", test: (p) => /^saved-searches\/\d+\/run$/.test(p) },
  { method: "POST", test: (p) => p === "match" },
  { method: "POST", test: (p) => p === "boards" },
  { method: "POST", test: (p) => p === "boards/discover" },
  { method: "POST", test: (p) => /^boards\/\d+\/verify$/.test(p) },
  { method: "PATCH", test: (p) => /^boards\/\d+$/.test(p) },
  { method: "POST", test: (p) => /^collector\/[^/]+\/(pause|resume)$/.test(p) },
];

const WRITES = new Set(["POST", "PATCH", "DELETE"]);

function sessionCookie(request: Request): string | undefined {
  // Prefer Next's parsed cookies (already percent-decoded). The raw-header
  // fallback must decode: a token payload contains ':' and a base64url
  // signature, both stored percent-encoded, and verifying the encoded string
  // fails the HMAC check.
  const parsed = (request as { cookies?: { get(name: string): { value: string } | undefined } })
    .cookies?.get(SESSION_COOKIE)?.value;
  if (parsed) return parsed;
  const header = request.headers.get("cookie");
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === SESSION_COOKIE) {
      const raw = rest.join("=");
      try {
        return decodeURIComponent(raw);
      } catch {
        return raw;
      }
    }
  }
  return undefined;
}

async function identity(request: Request) {
  if (WRITES.has(request.method.toUpperCase()) && !sameOrigin(request)) {
    return null;
  }
  return readSessionToken(sessionCookie(request));
}

async function handle(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await context.params;
  const joined = path.join("/");
  const method = request.method.toUpperCase();

  if (!RULES.some((rule) => rule.method === method && rule.test(joined))) {
    return NextResponse.json({ detail: "proxy route not allowed" }, { status: 403 });
  }

  const session = await identity(request);
  if (!session) {
    return NextResponse.json({ detail: "未登录或会话已过期" }, { status: 401 });
  }

  const memberAllowed =
    (joined === "saved-searches" && (method === "GET" || method === "POST")) ||
    (/^saved-searches\/\d+(?:\/matches|\/run)?$/.test(joined) &&
      ["GET", "PATCH", "DELETE", "POST"].includes(method)) ||
    (joined === "match" && method === "POST");
  if (session.kind !== "operator" && !memberAllowed) {
    return NextResponse.json({ detail: "此操作需要管理员权限" }, { status: 403 });
  }

  const body = method === "GET" || method === "DELETE" ? undefined : await request.text();
  const headers: Record<string, string> = {};
  if (body) headers["Content-Type"] = "application/json";
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  if (session.kind === "member") headers["X-Member-ID"] = String(session.id);

  const search = new URL(request.url).search;
  const response = await fetch(`${API_BASE}/api/v1/${joined}${search}`, {
    method,
    headers,
    body,
    cache: "no-store",
  });
  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

export const POST = handle;
export const GET = handle;
export const PATCH = handle;
export const DELETE = handle;
