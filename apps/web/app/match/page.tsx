"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { matchResume, type MatchResponse } from "@/lib/api";
import { formatLocation, formatSalary } from "@/lib/format";

export default function MatchPage() {
  const [resume, setResume] = useState("");
  const [country, setCountry] = useState("");
  const [remoteType, setRemoteType] = useState("");
  const [data, setData] = useState<MatchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setData(null);
    try {
      setData(
        await matchResume(resume, {
          country: country || undefined,
          remoteType: remoteType || undefined,
        })
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Matching failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>Résumé match</h1>
        <p>
          Paste your résumé to score current openings by skill and keyword overlap. Scoring runs
          locally and deterministically.
        </p>
      </section>

      <form className="match-form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="country">Country</label>
          <select id="country" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">Any</option>
            <option value="US">United States</option>
            <option value="AU">Australia</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="remote">Workplace</label>
          <select id="remote" value={remoteType} onChange={(e) => setRemoteType(e.target.value)}>
            <option value="">Any</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
          </select>
        </div>
        <div className="field field-wide">
          <label htmlFor="resume">Your résumé</label>
          <textarea
            id="resume"
            rows={8}
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            placeholder="Paste your résumé or a list of skills and experience…"
            required
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || resume.trim().length === 0}>
            {busy ? "Matching…" : "Match jobs"}
          </button>
        </div>
        {error ? <p className="form-message error">{error}</p> : null}
      </form>

      {data ? (
        <div className="match-results">
          <h2>
            {data.results.length} matches{" "}
            <span className="engine">
              ({data.engine}
              {data.reranked ? " · reranked" : ""})
            </span>
          </h2>
          {data.results.length === 0 ? (
            <p className="empty small">No jobs available to match against yet.</p>
          ) : (
            <ol className="match-list">
              {data.results.map((result) => {
                const salary = formatSalary(result.job);
                return (
                  <li key={result.job.id} className="match-item">
                    <div className="match-score">{result.score}</div>
                    <div className="match-body">
                      <h3>
                        <Link href={`/jobs/${result.job.id}`}>{result.job.title}</Link>
                      </h3>
                      <p className="meta">
                        {result.job.company ?? "Unknown company"} · {formatLocation(result.job)}
                        {result.semantic_score != null
                          ? ` · semantic ${result.semantic_score}`
                          : ""}
                        {result.rerank_score != null
                          ? ` · rerank ${result.rerank_score}`
                          : ""}
                      </p>
                      {salary ? <p className="salary">{salary}</p> : null}
                      {result.matched_skills.length > 0 ? (
                        <div className="tags">
                          {result.matched_skills.map((skill) => (
                            <span key={skill} className="tag skill">
                              {skill}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      ) : null}
    </>
  );
}
