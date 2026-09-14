import { NextResponse } from "next/server";

/**
 * Server-side proxy for browser-initiated write requests.
 *
 * The API key never reaches the browser: client components call this route and
 * it attaches `API_KEY` (server env) before forwarding to FastAPI. Only the
 * exact method + path combinations the UI needs are allowed.
 */

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

const RULES: { method: string; test: (path: string) => boolean }[] = [
  { method: "POST", test: (p) => p === "saved-searches" },
  { method: "PATCH", test: (p) => /^saved-searches\/\d+$/.test(p) },
  { method: "DELETE", test: (p) => /^saved-searches\/\d+$/.test(p) },
  { method: "POST", test: (p) => /^saved-searches\/\d+\/run$/.test(p) },
  { method: "POST", test: (p) => p === "match" },
  { method: "POST", test: (p) => p === "boards" },
  { method: "POST", test: (p) => p === "boards/discover" },
  { method: "POST", test: (p) => /^boards\/\d+\/verify$/.test(p) },
  { method: "PATCH", test: (p) => /^boards\/\d+$/.test(p) },
];

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

  const body = method === "GET" || method === "DELETE" ? undefined : await request.text();
  const headers: Record<string, string> = {};
  if (body) headers["Content-Type"] = "application/json";
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  const response = await fetch(`${API_BASE}/api/v1/${joined}`, {
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
export const PATCH = handle;
export const DELETE = handle;
