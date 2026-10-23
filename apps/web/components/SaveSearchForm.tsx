"use client";

import { useState, type FormEvent } from "react";

import { createSavedSearch, runSavedSearch, type SavedSearchInput } from "@/lib/api";

function defaultName(values: Record<string, string>): string {
  const parts = [values.q, values.city, values.country].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "全部职位";
}

function buildPayload(
  values: Record<string, string>,
  name: string,
  email: string,
  webhook: string,
  webhookKind: "generic" | "slack" | "teams",
  frequency: "immediate" | "digest"
): SavedSearchInput {
  return {
    name,
    keywords: values.q || null,
    country: values.country || null,
    source: values.source || null,
    city: values.city || null,
    remote_type: values.remote_type || null,
    employment_type: values.employment_type || null,
    min_salary: values.min_salary ? Number(values.min_salary) : null,
    notify_email: email || null,
    webhook_url: webhook || null,
    webhook_kind: webhookKind,
    frequency,
  };
}

export function SaveSearchForm({ values }: { values: Record<string, string> }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [webhook, setWebhook] = useState("");
  const [webhookKind, setWebhookKind] = useState<"generic" | "slack" | "teams">("generic");
  const [frequency, setFrequency] = useState<"immediate" | "digest">("immediate");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const payload = buildPayload(
        values,
        name.trim() || defaultName(values),
        email.trim(),
        webhook.trim(),
        webhookKind,
        frequency
      );
      const created = await createSavedSearch(payload);
      const run = await runSavedSearch(created.id);
      setMessage(`已保存“${created.name}” — ${run.new_matches} 个新匹配。可在“告警”页查看。`);
      setName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="save-search-shell">
      <summary><span>保存搜索并接收新职位提醒</span><span>可选 · 邮箱或 Webhook</span></summary>
    <form className="save-search" onSubmit={onSubmit} data-testid="save-search-form">
      <div className="field field-grow">
        <label htmlFor="saved-name">保存此搜索</label>
        <input
          id="saved-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={`名称（默认：${defaultName(values)}）`}
        />
      </div>
      <div className="field field-grow">
        <label htmlFor="saved-email">告警邮箱（可选）</label>
        <input
          id="saved-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />
      </div>
      <div className="field field-grow">
        <label htmlFor="saved-webhook">Webhook 地址（可选）</label>
        <input
          id="saved-webhook"
          type="url"
          value={webhook}
          onChange={(event) => setWebhook(event.target.value)}
          placeholder="https://hooks.example.com/jobs"
        />
      </div>
      <div className="field">
        <label htmlFor="saved-webhook-kind">Webhook 类型</label>
        <select
          id="saved-webhook-kind"
          value={webhookKind}
          onChange={(event) =>
            setWebhookKind(event.target.value as "generic" | "slack" | "teams")
          }
        >
          <option value="generic">通用 JSON</option>
          <option value="slack">Slack</option>
          <option value="teams">Microsoft Teams</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="saved-frequency">告警频率</label>
        <select
          id="saved-frequency"
          value={frequency}
          onChange={(event) => setFrequency(event.target.value as "immediate" | "digest")}
        >
          <option value="immediate">即时</option>
          <option value="digest">每日摘要</option>
        </select>
      </div>
      <div className="field field-actions">
        <button type="submit" className="btn-primary" disabled={busy} data-testid="save-search-submit">
          {busy ? "保存中…" : "保存搜索"}
        </button>
      </div>
      {message ? (
        <p className="form-message ok" data-testid="save-search-message">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="form-message error" data-testid="save-search-error">
          {error}
        </p>
      ) : null}
    </form></details>
  );
}
