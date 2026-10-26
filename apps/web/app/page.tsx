import { JobCard } from "@/components/JobCard";
import Link from "next/link";
import { SaveSearchForm } from "@/components/SaveSearchForm";
import { SearchForm } from "@/components/SearchForm";
import {
  exportUrl,
  getStats,
  searchJobs,
  type JobSearchResponse,
  type SearchQuery,
  type Stats,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

function single(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value ?? undefined;
}

function toValues(params: SearchParams): Record<string, string> {
  const values: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    const v = single(value);
    if (v !== undefined) values[key] = v;
  }
  return values;
}

function pageHref(params: SearchParams, page: number): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (key === "page") continue;
    const v = single(value);
    if (v) search.set(key, v);
  }
  search.set("page", String(page));
  return `/?${search.toString()}`;
}

export default async function Home({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const resolved = await searchParams;
  const values = toValues(resolved);
  const query: SearchQuery = {
    q: values.q,
    source: values.source,
    country: values.country,
    city: values.city,
    remote_type: values.remote_type,
    employment_type: values.employment_type,
    min_salary: values.min_salary,
    currency: values.currency,
    sort: values.sort ?? "posted_at",
    order: values.order ?? "desc",
    page: values.page ?? "1",
    page_size: values.page_size ?? "20",
  };

  let data: JobSearchResponse = { items: [], total: 0, page: 1, page_size: 20 };
  let stats: Stats | null = null;
  let error: string | null = null;
  try {
    const [jobsResult, statsResult] = await Promise.all([searchJobs(query), getStats()]);
    data = jobsResult;
    stats = statsResult;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  const countrySummary =
    stats?.by_country
      .filter((row) => row.country)
      .map((row) => `${row.country}: ${row.count.toLocaleString()}`)
      .join(" · ") ?? "";

  return (
    <>
      <section className="hero">
        <h1>职位搜索</h1>
        <p>搜索美国和澳大利亚的职位。可按来源、城市、工作方式和薪资筛选。</p>
        {stats ? (
          <p className="hero-stats">
            可公开展示 {stats.total_jobs.toLocaleString()} 个职位
            {countrySummary ? ` · ${countrySummary}` : ""}
          </p>
        ) : null}
      </section>

      <SearchForm values={values} />
      <SaveSearchForm values={values} />

      {error ? (
        <div className="notice">
          数据服务暂时不可用，请稍后刷新。<Link href="/status">查看运行状态</Link>
        </div>
      ) : null}

      <div className="results-head" data-testid="results-head">
        <h2>{data.total.toLocaleString()} 个结果</h2>
        <div className="results-tools">
          <a className="btn-ghost small" href={exportUrl(query, "csv")}>
            导出 CSV
          </a>
          <a className="btn-ghost small" href={exportUrl(query, "xlsx")}>
            导出 Excel
          </a>
          <span>
            第 {data.page} / {totalPages} 页
          </span>
        </div>
      </div>

      {data.items.length === 0 ? (
        <div className="empty" data-testid="results-empty">
          {stats?.total_jobs === 0 ? (
            <>
              <p>目前没有获准公开展示的职位。</p>
              <p>扩展采集的数据保存在私有采集库，公开搜索不会显示这些记录。</p>
              <Link href="/collection">查看真实采集统计</Link>{" · "}<Link href="/demo/match">体验匿名匹配示例</Link>{" · "}<Link href="/methodology">查看方法与实验</Link>
            </>
          ) : (
            <p>没有符合当前搜索条件的公开职位。</p>
          )}
        </div>
      ) : (
        <div className="job-grid" data-testid="job-grid">
          {data.items.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}

      {totalPages > 1 ? (
        <nav className="pagination">
          {data.page > 1 ? (
            <a className="btn-ghost" href={pageHref(resolved, data.page - 1)}>
              上一页
            </a>
          ) : (
            <span className="btn-ghost disabled">上一页</span>
          )}
          <span className="pagination-status">
            {data.page} / {totalPages}
          </span>
          {data.page < totalPages ? (
            <a className="btn-ghost" href={pageHref(resolved, data.page + 1)}>
              下一页
            </a>
          ) : (
            <span className="btn-ghost disabled">下一页</span>
          )}
        </nav>
      ) : null}
    </>
  );
}
