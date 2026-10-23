import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  createSessionToken,
  loginEnabled,
  sameOrigin,
  sessionCookieOptions,
  timingSafeEqual,
} from "@/lib/session";

/**
 * Single-operator login. Issues an HMAC-signed session cookie consumed by the
 * middleware and the API-key proxy. Replaced by the real identity system once
 * users/tenants exist.
 */

const MAX_ATTEMPTS = 5;
const WINDOW_MS = 5 * 60 * 1000;

const attempts = new Map<string, { count: number; resetAt: number }>();

function clientKey(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  return forwarded?.split(",")[0].trim() || "local";
}

function rateLimited(key: string): boolean {
  const now = Date.now();
  const entry = attempts.get(key);
  if (!entry || entry.resetAt <= now) {
    attempts.set(key, { count: 1, resetAt: now + WINDOW_MS });
    return false;
  }
  entry.count += 1;
  return entry.count > MAX_ATTEMPTS;
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ detail: "cross-origin request rejected" }, { status: 403 });
  }
  if (!loginEnabled()) {
    return NextResponse.json(
      { detail: "登录未启用：请在服务端配置 WEB_UI_PASSWORD" },
      { status: 403 }
    );
  }
  if (rateLimited(clientKey(request))) {
    return NextResponse.json({ detail: "尝试次数过多，请稍后再试" }, { status: 429 });
  }

  let username = "";
  let password = "";
  try {
    const body = (await request.json()) as { username?: unknown; password?: unknown };
    if (typeof body.username === "string") username = body.username.trim();
    if (typeof body.password === "string") password = body.password;
  } catch {
    return NextResponse.json({ detail: "请求格式错误" }, { status: 400 });
  }

  const expectedUsername = process.env.WEB_UI_USERNAME ?? "admin";
  const expectedPassword = process.env.WEB_UI_PASSWORD ?? "";
  if (!timingSafeEqual(username, expectedUsername) || !timingSafeEqual(password, expectedPassword)) {
    return NextResponse.json({ detail: "账号或密码错误" }, { status: 401 });
  }

  attempts.delete(clientKey(request));
  const response = NextResponse.json({ status: "ok" });
  response.cookies.set(
    SESSION_COOKIE,
    await createSessionToken(),
    sessionCookieOptions(request)
  );
  return response;
}
