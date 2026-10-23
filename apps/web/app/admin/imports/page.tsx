import Link from "next/link";

import { CollectorDashboard } from "@/components/CollectorDashboard";
import { getImportAdmin } from "@/lib/api";
import { formatDate, formatLocation } from "@/lib/format";

export const dynamic = "force-dynamic";

function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function percent(value: number, total: number): number {
  return total > 0 ? Math.min(100, Math.max(0, Math.round(value / total * 100))) : 0;
}

function distribution(items: Record<string, number>): string {
  return Object.entries(items).map(([name, count]) => (name === "unknown" ? "未标注" : name) + " " + count).join(" · ") || "暂无数据";
}

function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    running: "运行中", waiting: "等待中", retrying: "重试中",
    paused: "已暂停", completed: "已完成", partial: "部分完成",
    failed: "失败", processing: "处理中",
  };
  return labels[value] ?? value;
}

export default async function ImportAdminPage({ searchParams }: { searchParams: Promise<{ page?: string; q?: string; country?: string; job_status?: string }> }) {
  const query = await searchParams;
  const page = Math.max(1, Number(query.page) || 1);
  const keyword = query.q ?? "";
  const country = query.country ?? "";
  const jobStatus = query.job_status ?? "active";
  let data;
  try { data = await getImportAdmin(page, keyword, country, jobStatus); }
  catch (cause) { return <div className="notice">无法读取采集数据库（{cause instanceof Error ? cause.message : "API 错误"}）。</div>; }

  const pages = Math.max(1, Math.ceil(data.jobs.total / data.jobs.page_size));
  const seek = data.summary.seek;
  const batches = data.batches;
  const pageHref = (number: number) => {
    const params = new URLSearchParams({ page: String(number) });
    if (keyword) params.set("q", keyword);
    if (country) params.set("country", country);
    params.set("job_status", jobStatus);
    return `/admin/imports?${params}`;
  };

  return <div className="admin-page">
    <div className="admin-page-head">
      <div>
        <div className="admin-eyebrow">职位数据管理</div>
        <h1>采集数据库</h1>
        <p>查看扩展写入的职位、采集进度和导入记录。</p>
      </div>
      <div className="admin-head-side"><span className="admin-live-dot"/>最近入库 <strong>{dateTime(data.summary.latest_import_at)}</strong></div>
    </div>

    <CollectorDashboard seekDailyTarget={seek.today_target} />

    <div className="admin-overview" aria-label="数据库概览">
      <div><span>数据库职位</span><strong>{data.summary.total_jobs.toLocaleString("zh-CN")}</strong></div>
      <div><span>导入批次</span><strong>{data.summary.total_batches.toLocaleString("zh-CN")}</strong></div>
      <div><span>采集设备</span><strong>{data.summary.devices}</strong></div>
      <div><span>国家分布</span><p>{distribution(data.summary.by_country)}</p></div>
    </div>

    <section className="admin-panel admin-seek" aria-labelledby="seek-title">
      <div className="admin-panel-head">
        <div><span className="admin-section-kicker">SEEK / 澳洲护士职位</span><h2 id="seek-title">今日入库统计</h2></div>
        <span className="admin-status">{seek.status === "done" ? "今日目标已达到" : seek.status === "waiting" ? "本小时入库额度已满" : "入库额度可用"}</span>
      </div>
      <div className="admin-seek-grid">
        <div className="admin-progress-block">
          <div className="admin-progress-top"><span>今日有效职位</span><strong>{seek.today_valid}<small> / {seek.today_target}</small></strong></div>
          <div className="admin-progress-track"><span style={{ width: percent(seek.today_valid, seek.today_target) + "%" }}/></div>
          <p>下次采集 {dateTime(seek.next_run_at)} · 最近成功入库 {dateTime(seek.last_success_at)}</p>
        </div>
        <div className="admin-seek-metrics">
          <div><strong>{seek.hour_valid}<small> / {seek.hour_limit}</small></strong><span>本小时有效</span></div>
          <div><strong>{seek.recent_7d_valid}</strong><span>近 7 天有效</span></div>
          <div><strong>{Math.round(seek.salary_rate * 100)}%</strong><span>含薪资信息</span></div>
          <div><strong>{seek.visa_sponsorship_count}</strong><span>签证担保</span></div>
        </div>
      </div>
      <div className="admin-seek-foot">
        <span>重复 {seek.duplicate_count} · 不合格 {seek.rejected_count}</span>
        <span>州：{distribution(seek.by_state)}</span>
        <span>专业：{distribution(seek.by_specialty)}</span>
      </div>
    </section>

    <section className="admin-panel" aria-labelledby="latest-jobs-title">
      <div className="admin-panel-head">
        <div><span className="admin-section-kicker">职位记录</span><h2 id="latest-jobs-title">搜索采集职位</h2></div>
        <span className="admin-panel-count">共 {data.jobs.total.toLocaleString("zh-CN")} 条</span>
      </div>
      <form action="/admin/imports" method="get" className="admin-import-search">
        <input name="q" type="search" aria-label="职位关键词" placeholder="职位、公司或描述" defaultValue={keyword} />
        <select name="country" aria-label="国家或地区" defaultValue={country}>
          <option value="">全部国家</option><option value="AU">澳大利亚</option><option value="US">美国</option>
        </select>
        <button type="submit" className="btn-primary">搜索</button>
        <select name="job_status" aria-label="招聘状态" defaultValue={jobStatus}>
          <option value="active">在招职位</option><option value="closed">已下架</option>
          <option value="pending">待复查</option><option value="all">全部状态</option>
        </select>
        <Link href="/admin/imports">清除</Link>
      </form>
      {data.jobs.items.length ? <div className="admin-table-scroll"><table className="admin-table admin-jobs-table">
        <thead><tr><th>职位 / 公司</th><th>地点</th><th>发布时间</th><th>采集时间</th><th>招聘状态</th><th>结果</th><th>设备</th></tr></thead>
        <tbody>{data.jobs.items.map((item) => <tr key={item.batch_id + "-" + item.job.id}>
          <td className="admin-job-cell">{item.job.canonical_url ? <a href={item.job.canonical_url} target="_blank" rel="noreferrer">{item.job.title}</a> : <strong>{item.job.title}</strong>}<span>{item.job.company ?? "公司未提供"}</span></td>
          <td>{formatLocation(item.job)}</td>
          <td>{formatDate(item.job.posted_at) ?? "—"}</td>
          <td>{dateTime(item.collected_at)}<span className="admin-table-sub">入库 {dateTime(item.imported_at)}</span></td>
          <td>{item.job.is_active === false ? "已下架" : item.job.review_status === "unknown" ? "待复查" : item.job.review_status === "active" ? "已确认在招" : "在招 · 未复查"}<span className="admin-table-sub">检查 {dateTime(item.job.last_checked_at)}</span></td>
          <td><span className={"admin-table-tag " + (item.action === "inserted" ? "is-new" : "")}>{item.action === "inserted" ? "新增" : item.action === "updated" ? "更新" : "重复"}</span><span className="admin-table-sub">批次 #{item.batch_id}</span></td>
          <td>{item.device.name}</td>
        </tr>)}</tbody>
      </table></div> : <p className="admin-empty">{keyword || country ? "没有符合条件的采集职位。" : "暂时没有采集职位。扩展上传后会出现在这里。"}</p>}
      <div className="admin-pagination">
        <span>第 {page} / {pages} 页</span>
        <div>{page > 1 ? <Link href={pageHref(page - 1)}>上一页</Link> : <span className="disabled">上一页</span>}{page < pages ? <Link href={pageHref(page + 1)}>下一页</Link> : <span className="disabled">下一页</span>}</div>
      </div>
    </section>

    <section className="admin-panel" aria-labelledby="batches-title">
      <div className="admin-panel-head"><div><span className="admin-section-kicker">入库记录</span><h2 id="batches-title">最近导入批次</h2></div><span className="admin-panel-count">最近 {batches.length} 批</span></div>
      <div className="admin-table-scroll"><table className="admin-table">
        <thead><tr><th>批次</th><th>设备</th><th>状态</th><th>收到</th><th>新增</th><th>重复</th><th>拒绝</th><th>完成时间</th><th>错误</th></tr></thead>
        <tbody>{batches.map((batch) => <tr key={batch.id}><td><strong>#{batch.id}</strong></td><td>{batch.device.name}</td><td><span className={"admin-table-tag " + (batch.status === "completed" ? "is-new" : "")}>{statusLabel(batch.status)}</span></td><td>{batch.received_count}</td><td>{batch.accepted_count}</td><td>{batch.duplicate_count}</td><td>{batch.rejected_count}</td><td>{dateTime(batch.completed_at)}</td><td className="admin-error-cell">{batch.error || "—"}</td></tr>)}</tbody>
      </table></div>
    </section>
  </div>;
}
