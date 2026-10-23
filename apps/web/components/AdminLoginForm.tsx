"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

export default function AdminLoginForm() {
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (response.ok) {
        const next = searchParams.get("next");
        // A full navigation lets Edge inject the collector bridge on this route.
        window.location.assign(next && next.startsWith("/admin/") ? next : "/admin/imports");
        return;
      }
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? "登录失败");
    } catch {
      setError("登录请求失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="login-layout" aria-label="管理员登录">
      <Link className="login-brand" href="/">职位聚合平台</Link>
      <form onSubmit={handleSubmit} className="login-form">
        <div className="login-form-heading">
          <h1>管理员登录</h1>
          <p className="muted">管理职位数据和采集任务。</p>
        </div>
        <div className="login-field">
          <label htmlFor="admin-username">管理员账号</label>
          <input id="admin-username" type="text" value={username}
            onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
        </div>
        <div className="login-field">
          <label htmlFor="admin-password">密码</label>
          <input id="admin-password" type="password" value={password}
            onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
        </div>
        {error ? <p className="error-text" role="alert">{error}</p> : null}
        <button type="submit" disabled={submitting}>{submitting ? "登录中…" : "登录"}</button>
      </form>
    </section>
  );
}
