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
      setMessage(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  const run = () =>
    withBusy(async () => {
      const result = await runSavedSearch(search.id);
      return `新增 ${result.new_matches} 个匹配`;
    });

  const toggle = () =>
    withBusy(async () => {
      await updateSavedSearch(search.id, { is_active: !search.is_active });
      return search.is_active ? "已暂停" : "已恢复";
    });

  const remove = () => {
    if (!window.confirm(`确定删除保存搜索“${search.name}”？`)) return undefined;
    return withBusy(async () => {
      await deleteSavedSearch(search.id);
      return "已删除";
    });
  };

  return (
    <div className="search-actions">
      <button type="button" className="btn-ghost small" onClick={run} disabled={busy}>
        立即运行
      </button>
      <button type="button" className="btn-ghost small" onClick={toggle} disabled={busy}>
        {search.is_active ? "暂停" : "恢复"}
      </button>
      <button type="button" className="btn-danger small" onClick={remove} disabled={busy}>
        删除
      </button>
      {message ? <span className="action-message">{message}</span> : null}
    </div>
  );
}
