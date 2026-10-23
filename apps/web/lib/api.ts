export type Job = {
  id: number;
  source: string;
  source_job_id: string;
  title: string;
  is_active?: boolean;
  review_status?: string | null;
  last_checked_at?: string | null;
  company: string | null;
  description: string | null;
  canonical_url: string | null;
  apply_url: string | null;
  country: string | null;
  state: string | null;
  city: string | null;
  remote_type: string | null;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
  posted_at: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  duplicate_of: number | null;
  skills: string[] | null;
  summary: string | null;
  salary_display_min: number | null;
  salary_display_max: number | null;
  salary_display_currency: string | null;
  salary_display_period: string | null;
};

export type JobSearchResponse = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
};

export type ImportAdminData = {
  summary: { total_jobs: number; total_batches: number; devices: number; latest_import_at: string | null; by_country: Record<string, number>; seek: {
    today_valid: number; today_target: number; hour_valid: number; hour_limit: number; recent_7d_valid: number;
    by_state: Record<string, number>; by_specialty: Record<string, number>; salary_rate: number;
    visa_sponsorship_count: number; duplicate_count: number; rejected_count: number;
    last_success_at: string | null; status: string; next_run_at: string | null;
  } };
  jobs: { total: number; page: number; page_size: number; items: Array<{
    job: Job; batch_id: number; action: string; collected_at: string | null; imported_at: string;
    device: { id: number; name: string; owner: string };
  }> };
  batches: Array<{
    id: number; device: { id: number; name: string }; status: string; received_count: number;
    accepted_count: number; duplicate_count: number; rejected_count: number;
    started_at: string; completed_at: string | null; error: string | null;
  }>;
};

export type SourceInfo = {
  known: string[];
  ats: string[];
  enabled: Record<string, boolean>;
  counts: Record<string, number>;
};

export type Stats = {
  total_jobs: number;
  active_jobs: number;
  by_source: { source: string; count: number }[];
  by_country: { country: string | null; count: number }[];
};

export type SearchQuery = {
  q?: string;
  source?: string;
  country?: string;
  city?: string;
  state?: string;
  remote_type?: string;
  employment_type?: string;
  min_salary?: string;
  currency?: string;
  sort?: string;
  order?: string;
  page?: string;
  page_size?: string;
};

function baseUrl(): string {
  return (
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000"
  );
}

function authHeaders(): Record<string, string> {
  // Server-only: the API key must never be bundled into browser JS.
  const key = process.env.API_KEY;
  return key ? { "X-API-Key": key } : {};
}

function toQuery(params: SearchQuery): string {
  const search = new URLSearchParams();
  const entries = Object.entries(params) as [string, unknown][];
  for (const [key, value] of entries) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text !== "") search.set(key, text);
  }
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl()}${path}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API request failed (${response.status}) for ${path}`);
  }
  return (await response.json()) as T;
}

export function searchJobs(query: SearchQuery): Promise<JobSearchResponse> {
  return getJson<JobSearchResponse>(`/api/v1/jobs${toQuery(query)}`);
}

export async function getJob(id: number | string): Promise<Job | null> {
  const response = await fetch(`${baseUrl()}/api/v1/jobs/${id}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`API request failed (${response.status}) for /api/v1/jobs/${id}`);
  }
  return (await response.json()) as Job;
}

export function getSources(): Promise<SourceInfo> {
  return getJson<SourceInfo>("/api/v1/sources");
}

export function getStats(): Promise<Stats> {
  return getJson<Stats>("/api/v1/stats");
}

export type Board = {
  id: number;
  provider: string;
  board_token: string;
  company_name: string | null;
  company_domain: string | null;
  country: string | null;
  careers_url: string | null;
  enabled: boolean;
  discovery_source: string | null;
  verified_at: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_job_count: number;
  consecutive_failures: number;
  discovered_at: string | null;
};

export type BoardCandidate = {
  provider: string;
  board_token: string;
  careers_url: string | null;
  config: Record<string, unknown> | null;
  job_count: number | null;
  verified: boolean;
};

export type SourceHealth = {
  source: string;
  runs: number;
  successes: number;
  errors: number;
  success_rate: number;
  last_status: string | null;
  last_run_at: string | null;
  last_job_count: number;
  consecutive_zero_runs: number;
  jobs_total: number;
  jobs_active: number;
  jobs_added_today: number;
  schema_drift: boolean;
};

export function getBoards(params: { provider?: string; enabled?: boolean; q?: string } = {}): Promise<Board[]> {
  const search = new URLSearchParams();
  if (params.provider) search.set("provider", params.provider);
  if (params.enabled !== undefined) search.set("enabled", String(params.enabled));
  if (params.q) search.set("q", params.q);
  const suffix = search.toString();
  return getJson<Board[]>(`/api/v1/boards${suffix ? `?${suffix}` : ""}`);
}

export function getSourceHealth(): Promise<SourceHealth[]> {
  return getJson<SourceHealth[]>("/api/v1/health/sources");
}

export function discoverBoards(domain: string, create: boolean): Promise<BoardCandidate[]> {
  return clientJson<BoardCandidate[]>("/api/proxy/boards/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, create }),
  });
}

export function createBoard(payload: {
  provider: string;
  board_token: string;
  company_name?: string | null;
  verify?: boolean;
}): Promise<Board> {
  return clientJson<Board>("/api/proxy/boards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function verifyBoard(id: number): Promise<Board> {
  return clientJson<Board>(`/api/proxy/boards/${id}/verify`, { method: "POST" });
}

export function setBoardEnabled(id: number, enabled: boolean): Promise<Board> {
  return clientJson<Board>(`/api/proxy/boards/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export type CompareAreaMetrics = {
  label: string;
  active_jobs: number;
  new_jobs: number;
  unique_companies: number;
  remote_ratio: number;
  salary_coverage: number;
  salary_median: number | null;
  salary_currency: string | null;
  salary_sample: number;
  top_skills: { skill: string; count: number }[];
  top_companies: { company: string; count: number }[];
  daily_counts: { date: string; count: number }[];
  source_counts: { source: string; count: number }[];
};

export type CompareResponse = {
  occupation: string | null;
  period_days: number;
  area_a: CompareAreaMetrics;
  area_b: CompareAreaMetrics;
  comparison: {
    job_count_ratio: number | null;
    salary_difference_percent: number | null;
    remote_ratio_difference: number | null;
  };
  data_quality: { deduplicated: boolean; last_updated_at: string | null };
  summary: string;
};

export function compareMarkets(
  query: Record<string, string | undefined>
): Promise<CompareResponse> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && String(value).trim() !== "") params.set(key, value);
  }
  return getJson<CompareResponse>(`/api/v1/compare?${params.toString()}`);
}

export function getLocations(
  q: string,
  country?: string,
  limit = 10
): Promise<{ country: string | null; state: string | null; city: string | null; count: number }[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (country) params.set("country", country);
  return getJson(`/api/v1/locations?${params.toString()}`);
}

export function getOccupations(q = "", limit = 50): Promise<{ occupation_group: string; count: number }[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set("q", q);
  return getJson(`/api/v1/occupations?${params.toString()}`);
}

export type SavedSearch = {
  id: number;
  name: string;
  keywords: string | null;
  country: string | null;
  source: string | null;
  city: string | null;
  state: string | null;
  remote_type: string | null;
  employment_type: string | null;
  min_salary: number | null;
  notify_email: string | null;
  webhook_url: string | null;
  webhook_kind: string;
  frequency: string;
  is_active: boolean;
  last_run_at: string | null;
  last_notified_at: string | null;
  last_match_count: number;
  created_at: string | null;
};

export type SavedSearchInput = {
  name: string;
  keywords?: string | null;
  country?: string | null;
  source?: string | null;
  city?: string | null;
  state?: string | null;
  remote_type?: string | null;
  employment_type?: string | null;
  min_salary?: number | null;
  notify_email?: string | null;
  webhook_url?: string | null;
  webhook_kind?: "generic" | "slack" | "teams";
  frequency?: "immediate" | "digest";
};

export type CollectorRun = {
  id: number;
  source: string;
  status: string;
  params: Record<string, unknown> | null;
  jobs_seen: number;
  jobs_inserted: number;
  jobs_updated: number;
  jobs_duplicate: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type SourceRunSummary = {
  source: string;
  runs: number;
  successes: number;
  errors: number;
  last_status: string | null;
  last_run_at: string | null;
  jobs_seen: number;
  jobs_inserted: number;
};

export type RunsSummary = {
  total_runs: number;
  sources: SourceRunSummary[];
};

export type MatchResult = {
  job: Job;
  score: number;
  matched_skills: string[];
  missing_skills: string[];
  shared_keywords: string[];
  semantic_score: number | null;
  rerank_score: number | null;
  keyword_coverage_score?: number | null;
  title_weight_score?: number | null;
  recency_score?: number | null;
};

export type MatchResponse = {
  engine: string;
  reranked: boolean;
  results: MatchResult[];
};

export type SavedSearchRunResult = {
  saved_search_id: number;
  new_matches: number;
  total_matches: number;
  items: Job[];
};

async function clientJson<T>(path: string, init?: RequestInit): Promise<T> {
  // Browser requests hit the same-origin proxy route, which adds the API key
  // server-side. `path` is always a `/api/proxy/...` URL.
  const response = await fetch(path, {
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    throw new Error(`API request failed (${response.status}) for ${path}`);
  }
  return (await response.json()) as T;
}

export function getImportAdmin(page = 1, q = "", country = "", jobStatus = "active"): Promise<ImportAdminData> {
  const params = new URLSearchParams({ page: String(page) });
  if (q.trim()) params.set("q", q.trim());
  if (country.trim()) params.set("country", country.trim());
  params.set("job_status", jobStatus);
  return getJson<ImportAdminData>(`/api/v1/import/admin?${params}`);
}

export function createSavedSearch(payload: SavedSearchInput): Promise<SavedSearch> {
  return clientJson<SavedSearch>("/api/proxy/saved-searches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function runSavedSearch(id: number): Promise<SavedSearchRunResult> {
  return clientJson<SavedSearchRunResult>(`/api/proxy/saved-searches/${id}/run`, {
    method: "POST",
  });
}

export function updateSavedSearch(
  id: number,
  payload: Partial<SavedSearchInput> & { is_active?: boolean }
): Promise<SavedSearch> {
  return clientJson<SavedSearch>(`/api/proxy/saved-searches/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteSavedSearch(id: number): Promise<void> {
  const response = await fetch(`/api/proxy/saved-searches/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`API request failed (${response.status}) for /api/v1/saved-searches/${id}`);
  }
}

export function listSavedSearches(): Promise<SavedSearch[]> {
  return getJson<SavedSearch[]>("/api/v1/saved-searches");
}

export function getSavedSearchMatches(id: number, limit = 20): Promise<Job[]> {
  return getJson<Job[]>(`/api/v1/saved-searches/${id}/matches?limit=${limit}`);
}

export function exportUrl(
  query: SearchQuery,
  format: "csv" | "json" | "xlsx" = "csv"
): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const params = new URLSearchParams();
  const merged: Record<string, unknown> = { ...query, format };
  for (const [key, value] of Object.entries(merged)) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      params.set(key, String(value));
    }
  }
  return `${base}/api/v1/jobs/export?${params.toString()}`;
}

export function getFxRates(): Promise<{ base: string; rates: Record<string, number> }> {
  return getJson<{ base: string; rates: Record<string, number> }>("/api/v1/fx");
}

export function getRuns(limit = 50, source?: string): Promise<CollectorRun[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (source) params.set("source", source);
  return getJson<CollectorRun[]>(`/api/v1/runs?${params.toString()}`);
}

export function getRunsSummary(): Promise<RunsSummary> {
  return getJson<RunsSummary>("/api/v1/runs/summary");
}

export function matchResume(
  resume: string,
  options: { limit?: number; country?: string; remoteType?: string } = {}
): Promise<MatchResponse> {
  return clientJson<MatchResponse>("/api/proxy/match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resume,
      limit: options.limit ?? 20,
      country: options.country || null,
      remote_type: options.remoteType || null,
    }),
  });
}

export type CollectorControlStatus = {
  source: string;
  paused: boolean;
  pause_reason: string | null;
  paused_at: string | null;
  note: string | null;
  last_run: {
    id: number;
    status: string;
    stopped_reason: string | null;
    jobs_inserted: number;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
  } | null;
  today_page_visits: number;
  today_detail_visits: number;
  daily_page_visit_limit: number;
  daily_detail_visit_limit: number;
};

export type CollectorStatus = {
  weekly: {
    target: number;
    new_jobs: number;
    by_source: Record<string, number>;
    week_start: string;
  };
  sources: CollectorControlStatus[];
};

export function getCollectorStatus(): Promise<CollectorStatus> {
  return getJson<CollectorStatus>("/api/v1/collector/status");
}

export function pauseCollector(source: string, reason = "manual"): Promise<unknown> {
  return clientJson(`/api/proxy/collector/${encodeURIComponent(source)}/pause`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function resumeCollector(source: string): Promise<unknown> {
  return clientJson(`/api/proxy/collector/${encodeURIComponent(source)}/resume`, {
    method: "POST",
  });
}

export function unsubscribeSavedSearch(token: string): Promise<{ status: string; name?: string }> {
  return getJson<{ status: string; name?: string }>(
    `/api/v1/saved-searches/unsubscribe?token=${encodeURIComponent(token)}`
  );
}
