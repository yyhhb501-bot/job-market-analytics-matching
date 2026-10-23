import { cookies } from "next/headers";

import { readSessionToken, SESSION_COOKIE } from "@/lib/session";
import type { Job, SavedSearch } from "@/lib/api";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

async function memberHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  if (process.env.API_KEY) headers["X-API-Key"] = process.env.API_KEY;
  const cookieStore = await cookies();
  const identity = await readSessionToken(cookieStore.get(SESSION_COOKIE)?.value);
  if (identity?.kind === "member") headers["X-Member-ID"] = String(identity.id);
  return headers;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: await memberHeaders(),
  });
  if (!response.ok) throw new Error(`API request failed (${response.status}) for ${path}`);
  return (await response.json()) as T;
}

export function listSavedSearches(): Promise<SavedSearch[]> {
  return getJson<SavedSearch[]>("/api/v1/saved-searches");
}

export function getSavedSearchMatches(id: number, limit = 20): Promise<Job[]> {
  return getJson<Job[]>(`/api/v1/saved-searches/${id}/matches?limit=${limit}`);
}
