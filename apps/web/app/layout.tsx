import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "职位聚合平台 — 美国 & 澳大利亚",
  description:
    "聚合公开 ATS 职位板、USAJOBS、SEEK、Indeed、Glassdoor 与 Adzuna 的美国与澳大利亚职位。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <header className="site-header">
          <div className="container header-inner">
            <Link href="/" className="brand">
              职位聚合平台
            </Link>
            <span className="brand-sub">美国 &amp; 澳大利亚</span>
            <nav className="site-nav">
              <Link href="/">搜索</Link>
              <Link href="/compare">地区对比</Link>
              <Link href="/match">简历匹配</Link>
              <Link href="/alerts">告警</Link>
              <Link href="/boards">公司看板</Link>
              <Link href="/status">运行状态</Link>
              <Link href="/admin/imports">采集数据库</Link>
              <Link href="/login">会员登录</Link>
              <Link href="/register">手机号注册</Link>
            </nav>
          </div>
        </header>
        <main className="container">{children}</main>
        <footer className="site-footer">
          <div className="container">
            数据来自公开 ATS 职位板、USAJOBS、SEEK、Indeed、Glassdoor 与 Adzuna。
          </div>
        </footer>
      </body>
    </html>
  );
}
