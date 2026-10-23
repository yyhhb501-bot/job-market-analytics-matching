import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { readSessionToken, sameOrigin, SESSION_COOKIE } from "@/lib/session";

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  // Next's internal URL can use 0.0.0.0/container hostname. Validate the actual
  // browser Origin AND Host, never a forwarded host supplied in isolation.
  if (!origin || !["http://localhost:3000", "http://127.0.0.1:3000"].includes(origin)
      || new URL(origin).host !== host || !sameOrigin(request)) {
    return NextResponse.json({ detail: "仅允许本机控制台连接" }, { status: 403 });
  }
  const url = new URL(origin);
  const identity = await readSessionToken((await cookies()).get(SESSION_COOKIE)?.value);
  if (identity?.kind !== "operator") {
    return NextResponse.json({ detail: "请先登录管理员账号" }, { status: 401 });
  }
  let platform: unknown;
  try { platform = (await request.json()).platform; } catch { /* invalid input */ }
  if (platform !== "linkedin" && platform !== "seek") {
    return NextResponse.json({ detail: "不支持的采集来源" }, { status: 400 });
  }
  if (!process.env.API_KEY) return NextResponse.json({ detail: "入库服务尚未配置" }, { status: 503 });
  try {
    const apiBase = process.env.API_BASE_URL ?? "http://localhost:8010";
    const localToken = platform === "linkedin" ? process.env.JOBAGG_DEVICE_TOKEN : undefined;
    if (localToken) {
      const existing = await fetch(`${apiBase}/api/v1/import/jobs?page_size=1`, {
        headers: { Authorization: `Bearer ${localToken}` }, signal: AbortSignal.timeout(10000), cache: "no-store",
      });
      if (existing.ok) return NextResponse.json({ apiUrl: `${url.protocol}//${url.hostname}:8010`, deviceToken: localToken },
        { headers: { "Cache-Control": "no-store" } });
      if (![401, 403].includes(existing.status)) throw new Error("existing connection unavailable");
    }
    const response = await fetch(`${apiBase}/api/v1/import/devices`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": process.env.API_KEY },
      body: JSON.stringify({ name: `Edge ${platform === "seek" ? "SEEK" : "领英"} 一键采集`, owner: "local-operator", platform }),
      signal: AbortSignal.timeout(10000), cache: "no-store",
    });
    if (!response.ok) throw new Error("setup failed");
    const device = await response.json();
    if (typeof device.token !== "string") throw new Error("invalid device");
    return NextResponse.json({ apiUrl: `${url.protocol}//${url.hostname}:8010`, deviceToken: device.token },
      { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "入库服务暂时不可用，请先运行启动采集服务" }, { status: 503 });
  }
}
