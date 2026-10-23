import { NextResponse, type NextRequest } from "next/server";

import { readSessionToken, SESSION_COOKIE } from "@/lib/session";

/**
 * Member pages require a verified-phone member session. Management pages
 * remain restricted to the separate operator session.
 */

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const identity = await readSessionToken(
    request.cookies.get(SESSION_COOKIE)?.value
  );

  if (pathname.startsWith("/api/proxy")) {
    if (!identity) {
      return NextResponse.json({ detail: "未登录或会话已过期" }, { status: 401 });
    }
    return NextResponse.next();
  }

  if (pathname === "/login" || pathname === "/register" || pathname === "/admin/login") {
    if (identity) {
      return NextResponse.redirect(new URL(identity.kind === "operator" ? "/admin/imports" : "/", request.url));
    }
    return NextResponse.next();
  }

  const operatorOnly = pathname.startsWith("/admin");
  if (operatorOnly && identity?.kind !== "operator") {
    const url = new URL("/admin/login", request.url);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  const memberPages = ["/alerts", "/match"];
  if (memberPages.some((path) => pathname === path || pathname.startsWith(`${path}/`)) && !identity) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (pathname.startsWith("/boards") && identity?.kind !== "operator") {
    const url = new URL("/admin/login", request.url);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/admin/:path*",
    "/boards/:path*",
    "/alerts/:path*",
    "/match/:path*",
    "/login",
    "/register",
    "/admin/login",
    "/api/proxy/:path*",
  ],
};
