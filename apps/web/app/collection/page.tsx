import {
  getCollectionOverview,
  type CollectionOverview,
} from "@/lib/api";
import { formatDate, labelSource } from "@/lib/format";
import { RefreshCollection } from "@/components/RefreshCollection";

export const dynamic = "force-dynamic";

/**
 * Public read-only collection dashboard. Aggregate, whitelisted figures only:
 * no tokens, device configuration, owner identifiers or control actions.
 * Internal collection counts and publicly displayable counts are shown as
 * two separate columns; the daily target is labelled as a target, not an
 * achievement.
 */

const RUN_STATUS_LABELS: Record<string, string> = {
  success: "成功",
  partial: "部分成功",
  retryable: "可重试失败",
  error: "失败",
  blocked: "访问受限",
  paused: "已暂停",
  skipped: "跳过（重复调度）",
  running: "运行中",
};

const COLLECTOR_STATE_LABELS: Record<string, string> = {
  online: "采集端在线",
  stale: "状态过期（超5分钟无心跳）",
  offline: "采集端离线",
  none: "无本地采集端记录",
};

function runStatusLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  return RUN_STATUS_LABELS[status] ?? status;
}

export default async function CollectionPage() {
  let overview: CollectionOverview | null = null;
  let error: string | null = null;
  try {
    overview = await getCollectionOverview();
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  const bjGenerated = overview
    ? new Date(overview.generated_at).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : null;

  const trendMax = overview
    ? Math.max(1, ...overview.seven_day_trend.map((p) => p.new_jobs))
    : 1;

  return (
    <>
      <section className="hero">
        <h1>采集看板（公开只读）</h1>
        <p>
          各来源真实采集与入库统计。统计基于服务端数据库实际记录；
          “今日/近7日”按北京时间窗口计算；每日目标 600 是<strong>目标</strong>而非已完成量或承诺。
          展示记录（可公开展示）与内部采集记录（含未授权展示的来源）分列，不混用口径。
        </p>
      </section>

      {error ? <div className="notice">无法连接 API（{error}）。</div> : null}

      {overview ? (
        <>
          <p className="meta" style={{ opacity: 0.8 }}>
            统计生成时间：{bjGenerated}（北京时间）
          </p>

          <h2 className="section-title">各来源统计</h2>
          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th>内部采集总量</th>
                  <th>可公开展示</th>
                  <th>今日新增（北京窗口）</th>
                  <th>近7日新增</th>
                  <th>最近入库时间</th>
                  <th>最近任务状态</th>
                </tr>
              </thead>
              <tbody>
                {overview.sources.map((row) => (
                  <tr key={row.source}>
                    <td>{labelSource(row.source) ?? row.source}</td>
                    <td>{row.internal_total}</td>
                    <td>{row.public_total}</td>
                    <td>{row.today_new_bj}</td>
                    <td>{row.seven_day_new_bj}</td>
                    <td>{formatDate(row.last_ingest_at) ?? "—"}</td>
                    <td>{runStatusLabel(row.last_run_status)}</td>
                  </tr>
                ))}
                {overview.sources.length === 0 ? (
                  <tr>
                    <td colSpan={7}>暂无采集记录。</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <h2 className="section-title">近7日新增趋势（内部采集口径）</h2>
          {overview.seven_day_trend.length === 0 ? (
            <p className="empty">暂无历史数据。</p>
          ) : (
            <div style={{ display: "flex", alignItems: "flex-end", gap: "0.5rem", minHeight: "120px" }}>
              {overview.seven_day_trend.map((point) => (
                <div key={point.date} style={{ textAlign: "center", minWidth: "48px" }}>
                  <div
                    style={{
                      height: `${Math.max(4, Math.round((point.new_jobs / trendMax) * 100))}px`,
                      background: "#2563eb",
                      margin: "0 auto",
                      width: "28px",
                    }}
                    title={`${point.date}: ${point.new_jobs} 条`}
                  />
                  <div style={{ fontSize: "0.7rem", opacity: 0.75 }}>{point.date.slice(5)}</div>
                  <div style={{ fontSize: "0.7rem" }}>{point.new_jobs}</div>
                </div>
              ))}
            </div>
          )}

          <RefreshCollection />
          <h2 className="section-title">本地采集端（今日统计与最近一次历史回执）</h2>
          {overview.local_uploads.length === 0 ? (
            <p className="empty">今日暂无本地采集端上传记录。</p>
          ) : (
            <div className="table-wrap">
              <table className="runs-table">
                <thead>
                  <tr>
                    <th>上传通道</th>
                    <th>accepted</th>
                    <th>duplicate</th>
                    <th>rejected</th>
                    <th>最近批次状态</th>
                    <th>最近批次完成</th>
                    <th>采集端状态</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.local_uploads.map((row) => (
                    <tr key={row.source}>
                      <td>{row.source}</td>
                      <td>{row.today_accepted_bj}</td>
                      <td>{row.today_duplicate_bj}</td>
                      <td>{row.today_rejected_bj}</td>
                      <td>
                        {row.last_batch_status ?? "—"}
                        {row.last_batch_id != null ? (
                          <span style={{ opacity: 0.7 }}> #{row.last_batch_id}</span>
                        ) : null}
                      </td>
                      <td>{formatDate(row.last_batch_completed_at) ?? "—"}</td>
                      <td>
                        {COLLECTOR_STATE_LABELS[row.collector_state] ?? row.collector_state}
                        {row.collector_last_seen_at
                          ? `（最近通信 ${formatDate(row.collector_last_seen_at)}）`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="small" style={{ opacity: 0.75, marginTop: "1rem" }}>
            说明：accepted / duplicate / rejected 为本地采集端上传回执的分列统计，重复与拒绝不计入有效新增；
            超过 5 分钟无心跳的采集端显示“状态过期”，不会永远显示运行中。
          </p>
        </>
      ) : null}
    </>
  );
}
