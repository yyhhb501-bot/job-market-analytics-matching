import { getRuns, getRunsSummary, type CollectorRun, type RunsSummary } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function StatusPage() {
  let runs: CollectorRun[] = [];
  let summary: RunsSummary | null = null;
  let error: string | null = null;

  try {
    [runs, summary] = await Promise.all([getRuns(50), getRunsSummary()]);
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "Failed to reach the API";
  }

  return (
    <>
      <section className="hero">
        <h1>Collector status</h1>
        <p>Run history and per-source health for every enabled collector.</p>
      </section>

      {error ? <div className="notice">Could not reach the API ({error}).</div> : null}

      {summary && summary.sources.length > 0 ? (
        <div className="job-grid">
          {summary.sources.map((row) => (
            <div key={row.source} className="job-card">
              <div className="job-card-head">
                <h2>{row.source}</h2>
                <span className={`badge ${row.last_status === "error" ? "badge-error" : ""}`}>
                  {row.last_status ?? "unknown"}
                </span>
              </div>
              <p className="meta">
                {row.runs} runs · {row.successes} ok · {row.errors} errors
              </p>
              <p className="meta">
                seen {row.jobs_seen} · inserted {row.jobs_inserted}
              </p>
              <p className="meta">last run {formatDate(row.last_run_at) ?? "never"}</p>
            </div>
          ))}
        </div>
      ) : (
        !error && <p className="empty">No collector runs recorded yet.</p>
      )}

      {runs.length > 0 ? (
        <>
          <h2 className="section-title">Recent runs</h2>
          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Seen</th>
                  <th>Inserted</th>
                  <th>Updated</th>
                  <th>Dup</th>
                  <th>Started</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>{run.source}</td>
                    <td>{run.status}</td>
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
