import { JobCard } from "@/components/JobCard";
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
    error = cause instanceof Error ? cause.message : "Failed to reach the API";
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
        <h1>Find jobs in the US and Australia</h1>
        <p>
          One search across public ATS boards, USAJOBS, SEEK, Indeed, Glassdoor and Adzuna.
        </p>
        {stats ? (
          <p className="hero-stats">
            {stats.total_jobs.toLocaleString()} jobs indexed
            {countrySummary ? ` · ${countrySummary}` : ""}
          </p>
        ) : null}
      </section>

      <SearchForm values={values} />
      <SaveSearchForm values={values} />

      {error ? (
        <div className="notice">
          Could not reach the API ({error}). Make sure the FastAPI service is running and
          <code> API_BASE_URL </code>
          points at it.
        </div>
      ) : null}

      <div className="results-head">
        <h2>{data.total.toLocaleString()} results</h2>
        <div className="results-tools">
          <a className="btn-ghost small" href={exportUrl(query, "csv")}>
            Export CSV
          </a>
          <a className="btn-ghost small" href={exportUrl(query, "xlsx")}>
            Export Excel
          </a>
          <span>
            Page {data.page} of {totalPages}
          </span>
        </div>
      </div>

      {data.items.length === 0 ? (
        <p className="empty">No jobs matched your search.</p>
      ) : (
        <div className="job-grid">
          {data.items.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}

      {totalPages > 1 ? (
        <nav className="pagination">
          {data.page > 1 ? (
            <a className="btn-ghost" href={pageHref(resolved, data.page - 1)}>
              Previous
            </a>
          ) : (
            <span className="btn-ghost disabled">Previous</span>
          )}
          <span className="pagination-status">
            {data.page} / {totalPages}
          </span>
          {data.page < totalPages ? (
            <a className="btn-ghost" href={pageHref(resolved, data.page + 1)}>
              Next
            </a>
          ) : (
            <span className="btn-ghost disabled">Next</span>
          )}
        </nav>
      ) : null}
    </>
  );
}
