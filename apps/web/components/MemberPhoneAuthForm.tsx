"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

export default function MemberPhoneAuthForm({ intent }: { intent: "login" | "register" }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function sendCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch("/api/member-auth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim(), intent }),
      });
      const body = (await response.json().catch(() => ({}))) as { detail?: string; message?: string };
      if (!response.ok) {
        setError(body.detail ?? "验证码发送失败");
        return;
      }
      setSent(true);
      setMessage(body.message ?? "验证码已发送");
    } catch {
      setError("暂时无法连接，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/member-auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim(), code: code.trim(), intent }),
      });
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      if (!response.ok) {
        setError(body.detail ?? "验证码错误或已过期");
        return;
      }
      const next = searchParams.get("next");
      router.replace(next && next.startsWith("/") ? next : "/");
      router.refresh();
    } catch {
      setError("暂时无法连接，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="login-layout" aria-label={intent === "register" ? "会员注册" : "会员登录"}>
      <Link className="login-brand" href="/">职位聚合平台</Link>
      <form onSubmit={sent ? verifyCode : sendCode} className="login-form">
        <div className="login-form-heading">
          <h1>{intent === "register" ? "手机号注册" : "手机号登录"}</h1>
          <p className="muted">使用短信验证码验证手机号并进入账户。</p>
        </div>
        <div className="login-field">
          <label htmlFor="member-phone">手机号</label>
          <input
            id="member-phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="国际格式，例如 +61412345678"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoFocus
            required
            disabled={sent}
          />
        </div>
        {sent ? (
          <div className="login-field">
            <label htmlFor="member-code">短信验证码</label>
            <input id="member-code" type="text" inputMode="numeric" autoComplete="one-time-code"
              value={code} onChange={(event) => setCode(event.target.value)} required />
          </div>
        ) : null}
        {message ? <p className="login-success" role="status">{message}</p> : null}
        {error ? <p className="error-text" role="alert">{error}</p> : null}
        <button type="submit" disabled={busy}>
          {busy ? "请稍候…" : sent ? "验证并进入" : "发送验证码"}
        </button>
        {sent ? <button type="button" className="login-secondary" onClick={() => { setSent(false); setCode(""); setMessage(null); }} disabled={busy}>更换手机号</button> : null}
      </form>
      <p className="login-note">
        {intent === "register" ? <>已有账户？ <Link href="/login">手机号登录</Link></> : <>还没有账户？ <Link href="/register">手机号注册</Link></>}
      </p>
      <Link className="login-admin-link" href="/admin/login">管理员入口</Link>
    </section>
  );
}
