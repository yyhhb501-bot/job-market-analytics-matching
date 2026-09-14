import {
  getRuns,
  getRunsSummary,
  getSourceHealth,
  type CollectorRun,
  type RunsSummary,
  type SourceHealth,
} from "@/lib/api";
import { formatDate, labelSource } from "@/lib/format";

export const dynamic = "force-dynamic";

const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  error: "失败",
  running: "运行中",
};

function statusLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  return STATUS_LABELS[status] ?? status;
}

export default async function StatusPage() {
  let runs: CollectorRun[] = [];
  let summary: RunsSummary | null = null;
  let health: SourceHealth[] = [];
  let error: string | null = null;

  try {
    [runs, summary, health] = await Promise.all([
      getRuns(50),
      getRunsSummary(),
      getSourceHealth(),
    ]);
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  return (
    <>
      <section className="hero">
        <h1>采集运行状态</h1>
        <p>每个已启用采集源的运行历史与健康情况。</p>
      </section>

      {error ? <div className="notice">无法连接 API（{error}）。</div> : null}

      {summary && summary.sources.length > 0 ? (
        <div className="job-grid" data-testid="source-cards">
          {summary.sources.map((row) => (
            <div key={row.source} className="job-card">
              <div className="job-card-head">
                <h2>{row.source}</h2>
                <span className={`badge ${row.last_status === "error" ? "badge-error" : ""}`}>
                  {statusLabel(row.last_status)}
                </span>
              </div>
              <p className="meta">
                共 {row.runs} 次 · 成功 {row.successes} · 失败 {row.errors}
              </p>
              <p className="meta">
                发现 {row.jobs_seen} · 新增 {row.jobs_inserted}
              </p>
              <p className="meta">上次运行：{formatDate(row.last_run_at) ?? "从未"}</p>
            </div>
          ))}
        </div>
      ) : (
        !error && (
          <p className="empty" data-testid="status-empty">
            暂无采集运行记录。
          </p>
        )
      )}

      {health.length > 0 ? (
        <>
          <h2 className="section-title">来源健康</h2>
          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th>成功率</th>
                  <th>上次状态</th>
                  <th>上次岗位数</th>
                  <th>连续空结果</th>
                  <th>今日新增</th>
                  <th>活跃/总数</th>
                  <th>异常</th>
                </tr>
              </thead>
              <tbody>
                {health.map((row) => (
                  <tr key={row.source}>
                    <td>{labelSource(row.source)}</td>
                    <td>{Math.round(row.success_rate * 100)}%</td>
                    <td>{statusLabel(row.last_status)}</td>
                    <td>{row.last_job_count}</td>
                    <td>{row.consecutive_zero_runs}</td>
                    <td>{row.jobs_added_today}</td>
                    <td>
                      {row.jobs_active}/{row.jobs_total}
                    </td>
                    <td className="error-cell">{row.schema_drift ? "疑似解析失效" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {runs.length > 0 ? (
        <>
          <h2 className="section-title">最近运行</h2>
          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th>状态</th>
                  <th>发现</th>
                  <th>新增</th>
                  <th>更新</th>
                  <th>重复</th>
                  <th>开始时间</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{run.source}</td>
                    <td>{statusLabel(run.status)}</td>
                    <td>{run.jobs_seen}</td>
                    <td>{run.jobs_inserted}</td>
                    <td>{run.jobs_updated}</td>
                    <td>{run.jobs_duplicate}</td>
                    <td>{formatDate(run.started_at) ?? "—"}</td>
                    <td className="error-cell">{run.error ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </>
  );
}
