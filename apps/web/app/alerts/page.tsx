import Link from "next/link";

import { JobCard } from "@/components/JobCard";
import { SavedSearchActions } from "@/components/SavedSearchActions";
import {
  getSavedSearchMatches,
  listSavedSearches,
  type Job,
  type SavedSearch,
} from "@/lib/api";
import { formatDate, labelEmployment, labelRemote } from "@/lib/format";

export const dynamic = "force-dynamic";

function describe(search: SavedSearch): string {
  const parts = [
    search.keywords ? `“${search.keywords}”` : null,
    search.country,
    search.source,
    search.city,
    labelRemote(search.remote_type) || null,
    labelEmployment(search.employment_type) || null,
    search.min_salary ? `≥ ${search.min_salary}` : null,
  ].filter(Boolean) as string[];
  return parts.length > 0 ? parts.join(" · ") : "全部职位";
}

export default async function AlertsPage() {
  let searches: SavedSearch[] = [];
  let matchesBySearch: Record<number, Job[]> = {};
  let error: string | null = null;

  try {
    searches = await listSavedSearches();
    const map: Record<number, Job[]> = {};
    await Promise.all(
      searches.map(async (search) => {
        map[search.id] = await getSavedSearchMatches(search.id, 6);
      })
    );
    matchesBySearch = map;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  return (
    <>
      <section className="hero">
        <h1>保存搜索与告警</h1>
        <p>与你的保存搜索匹配的新职位。每次采集任务都会自动刷新。</p>
      </section>

      {error ? (
        <div className="notice">无法连接 API（{error}）。</div>
      ) : null}

      {searches.length === 0 ? (
        <p className="empty">
          还没有保存搜索。请在<Link href="/">首页</Link>搜索后使用“保存此搜索”。
        </p>
      ) : (
        <div className="alert-list">
          {searches.map((search) => {
            const matches = matchesBySearch[search.id] ?? [];
            return (
              <section key={search.id} className="alert-block">
                <div className="alert-head">
                  <div>
                    <h2>
                      {search.name}{" "}
                      {!search.is_active ? <span className="tag muted">已暂停</span> : null}
                    </h2>
                    <p className="meta">{describe(search)}</p>
                    <p className="meta">
                      {search.frequency === "digest" ? "每日摘要" : "即时提醒"}
                      {search.notify_email ? ` · ${search.notify_email}` : ""}
                      {search.webhook_url
                        ? ` · ${search.webhook_kind} webhook ${search.webhook_url}`
                        : ""}
                      {!search.notify_email && !search.webhook_url ? " · 未设置推送方式" : ""}
                    </p>
                  </div>
                  <div className="alert-stats">
                    <span>上次运行命中 {search.last_match_count} 个</span>
                    <span>上次运行：{formatDate(search.last_run_at) ?? "从未"}</span>
                    <span>上次通知：{formatDate(search.last_notified_at) ?? "从未"}</span>
                    <SavedSearchActions search={search} />
                  </div>
                </div>
                {matches.length === 0 ? (
                  <p className="empty small">暂无匹配记录。</p>
                ) : (
                  <div className="job-grid">
                    {matches.map((job) => (
                      <JobCard key={job.id} job={job} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
