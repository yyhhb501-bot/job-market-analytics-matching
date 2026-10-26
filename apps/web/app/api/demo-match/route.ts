import { NextResponse } from "next/server";

import { sameOrigin } from "@/lib/session";

/**
 * Anonymous proxy for the public match demonstration.
 *
 * No session is required: teachers can try the matcher without registering.
 * The request is forwarded to the keyless, rate-limited FastAPI demo endpoint
 * (stricter caps than the member endpoint). Cross-origin POSTs are rejected so
 * third-party pages cannot burn the deployment's rate budget. Forwarded client
 * IP headers are deliberately not trusted; visitors through this proxy share
 * the API's conservative per-proxy limit.
 */

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

const MAX_BODY_BYTES = 32 * 1024;

export async function POST(request: Request): Promise<NextResponse> {
  if (!sameOrigin(request)) {
    return NextResponse.json({ detail: "cross-origin request rejected" }, { status: 403 });
  }
  const length=request.headers.get("content-length");
  if(length && Number(length)>MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "请求体过大" }, { status: 413 });
  }
  const reader=request.body?.getReader();
  const chunks:Uint8Array[]=[];let size=0;
  if(reader) {
    try {while(true) {
      const {done,value}=await reader.read();if(done) break;
      size+=value.byteLength;
      if(size>MAX_BODY_BYTES) {await reader.cancel();return NextResponse.json({detail:"请求体过大"},{status:413});}
      chunks.push(value);
    }} catch {return NextResponse.json({detail:"请求体读取失败"},{status:400});}
    finally {reader.releaseLock();}
  }
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.byteLength;}
  const body=new TextDecoder().decode(bytes);
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return NextResponse.json({ detail: "invalid JSON" }, { status: 400 });
  }
  if(!parsed || typeof parsed!=="object" || Array.isArray(parsed)) {
    return NextResponse.json({detail:"请求必须为 JSON 对象"},{status:400});
  }
  const payload = parsed as { resume?: unknown; country?: unknown; remote_type?: unknown; limit?: unknown; illustrative?: unknown };
  if (typeof payload.resume !== "string" || payload.resume.trim().length === 0) {
    return NextResponse.json({ detail: "简历文本不能为空" }, { status: 400 });
  }

  try {
  const endpoint=payload.illustrative===true?"demo/examples/match":"demo/match";
  const response = await fetch(`${API_BASE}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resume: payload.resume,
      country: typeof payload.country === "string" && payload.country ? payload.country : null,
      remote_type:
        typeof payload.remote_type === "string" && payload.remote_type ? payload.remote_type : null,
      limit: typeof payload.limit === "number" ? payload.limit : 10,
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
    },
  });
  } catch {
    return NextResponse.json({detail:"匹配服务暂不可用，请稍后重试。"},{status:503});
  }
}
