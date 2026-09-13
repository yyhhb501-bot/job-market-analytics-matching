"use client";

import { useState, type FormEvent } from "react";

import { createSavedSearch, runSavedSearch, type SavedSearchInput } from "@/lib/api";

function defaultName(values: Record<string, string>): string {
  const parts = [values.q, values.city, values.country].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "All jobs";
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
      setMessage(`Saved “${created.name}” — ${run.new_matches} new match(es). See Alerts.`);
      setName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to save search");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="save-search" onSubmit={onSubmit}>
      <div className="field field-grow">
        <label htmlFor="saved-name">Save this search</label>
        <input
          id="saved-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={`Name (default: ${defaultName(values)})`}
        />
      </div>
      <div className="field field-grow">
        <label htmlFor="saved-email">Alert email (optional)</label>
        <input
          id="saved-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />
      </div>
      <div className="field field-grow">
        <label htmlFor="saved-webhook">Webhook URL (optional)</label>
        <input
          id="saved-webhook"
          type="url"
          value={webhook}
          onChange={(event) => setWebhook(event.target.value)}
          placeholder="https://hooks.example.com/jobs"
        />
      </div>
      <div className="field">
        <label htmlFor="saved-webhook-kind">Webhook type</label>
        <select
          id="saved-webhook-kind"
          value={webhookKind}
          onChange={(event) =>
            setWebhookKind(event.target.value as "generic" | "slack" | "teams")
          }
        >
          <option value="generic">Generic JSON</option>
          <option value="slack">Slack</option>
          <option value="teams">Microsoft Teams</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="saved-frequency">Alerts</label>
        <select
          id="saved-frequency"
          value={frequency}
          onChange={(event) => setFrequency(event.target.value as "immediate" | "digest")}
        >
          <option value="immediate">Immediate</option>
          <option value="digest">Daily digest</option>
        </select>
      </div>
      <div className="field field-actions">
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save search"}
        </button>
      </div>
      {message ? <p className="form-message ok">{message}</p> : null}
      {error ? <p className="form-message error">{error}</p> : null}
    </form>
  );
}
