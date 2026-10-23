import { NextResponse } from "next/server";

import {
  createMemberSessionToken,
  memberSessionEnabled,
  sameOrigin,
  SESSION_COOKIE,
  sessionCookieOptions,
} from "@/lib/session";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

export async function POST(
  request: Request,
  context: { params: Promise<{ action: string }> },
) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ detail: "cross-origin request rejected" }, { status: 403 });
  }
  const { action } = await context.params;
  if (action !== "start" && action !== "verify") {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }
  if (!memberSessionEnabled()) {
    return NextResponse.json({ detail: "手机号登录未配置：请设置 SESSION_SECRET" }, { status: 503 });
  }

  let body: { phone?: unknown; code?: unknown; intent?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "请求格式错误" }, { status: 400 });
  }
  const response = await fetch(`${API_BASE}/api/v1/auth/member/otp/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const result = await response.json().catch(() => ({ detail: "短信验证请求失败" }));
  if (!response.ok) {
    return NextResponse.json(result, { status: response.status });
  }

  const next = NextResponse.json(result);
  if (action === "verify" && result.member) {
    next.cookies.set(
      SESSION_COOKIE,
      await createMemberSessionToken(result.member),
      sessionCookieOptions(request),
    );
  }
  return next;
}
