"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { pauseCollector, resumeCollector, type CollectorControlStatus } from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  partial: "部分成功",
  retryable: "可重试失败",
  error: "失败",
  blocked: "访问受限",
  paused: "已暂停",
  skipped: "跳过（重复调度）",
  running: "运行中",
};

function statusLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  return STATUS_LABELS[status] ?? status;
}

const PAUSE_REASON_LABELS: Record<string, string> = {
  challenge: "访问受限（需人工处理）",
  manual: "手动暂停",
};

export default function CollectorControls({ sources }: { sources: CollectorControlStatus[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busySource, setBusySource] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(source: string, action: "pause" | "resume") {
    const confirmed = window.confirm(
      action === "pause"
        ? `确认暂停 ${source} 的采集？暂停后该来源不再访问上游。`
        : `确认恢复 ${source} 的采集？恢复后会重新受到访问预算与运行互斥的约束。`
    );
    if (!confirmed) return;
    setBusySource(source);
    setError(null);
    try {
      if (action === "pause") {
        await pauseCollector(source, "manual");
      } else {
        await resumeCollector(source);
      }
      startTransition(() => router.refresh());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusySource(null);
    }
  }

  if (sources.length === 0) {
    return (
      <p className="empty" data-testid="collector-controls-empty">
        暂无采集源状态。
      </p>
    );
  }

  return (
    <div className="table-wrap" data-testid="collector-controls">
      {error ? <p className="error-text">{error}</p> : null}
      <table className="runs-table">
        <thead>
          <tr>
            <th>来源</th>
            <th>状态</th>
            <th>上次运行</th>
            <th>今日访问（页面/详情）</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((row) => (
            <tr key={row.source}>
              <td>{row.source}</td>
              <td>
                {row.paused ? (
                  <span className="badge badge-error">
                    已暂停 · {PAUSE_REASON_LABELS[row.pause_reason ?? "manual"] ?? row.pause_reason}
                  </span>
                ) : (
                  <span className="badge">正常</span>
                )}
              </td>
              <td>
                {row.last_run ? (
                  <>
                    {statusLabel(row.last_run.status)}
                    {row.last_run.stopped_reason ? `（${row.last_run.stopped_reason}）` : ""}
                    {row.last_run.error ? ` · ${row.last_run.error}` : ""}
                  </>
                ) : (
                  "从未"
                )}
              </td>
              <td>
                {row.today_page_visits}
                {row.daily_page_visit_limit > 0 ? `/${row.daily_page_visit_limit}` : ""} /{" "}
                {row.today_detail_visits}
                {row.daily_detail_visit_limit > 0 ? `/${row.daily_detail_visit_limit}` : ""}
              </td>
              <td>
                {row.paused ? (
                  <button
                    type="button"
                    disabled={busySource === row.source || pending}
                    onClick={() => act(row.source, "resume")}
                  >
                    恢复
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={busySource === row.source || pending}
                    onClick={() => act(row.source, "pause")}
                  >
                    暂停
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
