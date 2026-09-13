import Link from "next/link";

import { JobCard } from "@/components/JobCard";
import { SavedSearchActions } from "@/components/SavedSearchActions";
import {
  getSavedSearchMatches,
  listSavedSearches,
  type Job,
  type SavedSearch,
} from "@/lib/api";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

function describe(search: SavedSearch): string {
  const parts = [
    search.keywords ? `“${search.keywords}”` : null,
    search.country,
    search.source,
    search.city,
    search.remote_type,
    search.employment_type,
    search.min_salary ? `≥ ${search.min_salary}` : null,
  ].filter(Boolean) as string[];
  return parts.length > 0 ? parts.join(" · ") : "All jobs";
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
    error = cause instanceof Error ? cause.message : "Failed to reach the API";
  }

  return (
    <>
      <section className="hero">
        <h1>Saved searches &amp; alerts</h1>
        <p>
          Newly seen jobs that matched your saved searches. The worker refreshes these on every
          collection run.
        </p>
      </section>

      {error ? (
        <div className="notice">Could not reach the API ({error}).</div>
      ) : null}

      {searches.length === 0 ? (
        <p className="empty">
          No saved searches yet. Run a search on the <Link href="/">home page</Link> and use
          &ldquo;Save search&rdquo;.
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
                      {!search.is_active ? <span className="tag muted">paused</span> : null}
                    </h2>
                    <p className="meta">{describe(search)}</p>
                    <p className="meta">
                      {search.frequency === "digest" ? "Daily digest" : "Immediate alerts"}
                      {search.notify_email ? ` · ${search.notify_email}` : ""}
                      {search.webhook_url
                        ? ` · ${search.webhook_kind} webhook ${search.webhook_url}`
                        : ""}
                      {!search.notify_email && !search.webhook_url ? " · no delivery set" : ""}
                    </p>
                  </div>
                  <div className="alert-stats">
                    <span>{search.last_match_count} on last run</span>
                    <span>last run {formatDate(search.last_run_at) ?? "never"}</span>
                    <span>
                      last notified {formatDate(search.last_notified_at) ?? "never"}
                    </span>
                    <SavedSearchActions search={search} />
                  </div>
                </div>
                {matches.length === 0 ? (
                  <p className="empty small">No matches recorded yet.</p>
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
