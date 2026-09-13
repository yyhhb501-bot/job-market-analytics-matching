"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { deleteSavedSearch, runSavedSearch, updateSavedSearch, type SavedSearch } from "@/lib/api";

export function SavedSearchActions({ search }: { search: SavedSearch }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function withBusy(action: () => Promise<string | null>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage(await action());
      router.refresh();
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const run = () =>
    withBusy(async () => {
      const result = await runSavedSearch(search.id);
      return `${result.new_matches} new match(es)`;
    });

  const toggle = () =>
    withBusy(async () => {
      await updateSavedSearch(search.id, { is_active: !search.is_active });
      return search.is_active ? "Paused" : "Resumed";
    });

  const remove = () => {
    if (!window.confirm(`Delete saved search “${search.name}”?`)) return undefined;
    return withBusy(async () => {
      await deleteSavedSearch(search.id);
      return "Deleted";
    });
  };

  return (
    <div className="search-actions">
      <button type="button" className="btn-ghost small" onClick={run} disabled={busy}>
        Run now
      </button>
      <button type="button" className="btn-ghost small" onClick={toggle} disabled={busy}>
        {search.is_active ? "Pause" : "Resume"}
      </button>
      <button type="button" className="btn-danger small" onClick={remove} disabled={busy}>
        Delete
      </button>
      {message ? <span className="action-message">{message}</span> : null}
    </div>
  );
}
