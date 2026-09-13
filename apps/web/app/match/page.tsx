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
      setError(cause instanceof Error ? cause.message : "匹配失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>简历匹配</h1>
        <p>粘贴简历，按技能与关键词重合度给现有职位打分。评分在本地确定性完成。</p>
      </section>

      <form className="match-form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="country">国家</label>
          <select id="country" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">不限</option>
            <option value="US">美国</option>
            <option value="AU">澳大利亚</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="remote">工作方式</label>
          <select id="remote" value={remoteType} onChange={(e) => setRemoteType(e.target.value)}>
            <option value="">不限</option>
            <option value="remote">远程</option>
            <option value="hybrid">混合</option>
            <option value="onsite">现场</option>
          </select>
        </div>
        <div className="field field-wide">
          <label htmlFor="resume">你的简历</label>
          <textarea
            id="resume"
            rows={8}
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            placeholder="粘贴简历，或列出你的技能与经历……"
            required
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || resume.trim().length === 0}>
            {busy ? "匹配中…" : "开始匹配"}
          </button>
        </div>
        {error ? <p className="form-message error">{error}</p> : null}
      </form>

      {data ? (
        <div className="match-results">
          <h2>
            {data.results.length} 个匹配{" "}
            <span className="engine">
              （引擎 {data.engine}
              {data.reranked ? " · 已重排" : ""}）
            </span>
          </h2>
          {data.results.length === 0 ? (
            <p className="empty small">暂无可用于匹配的职位。</p>
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
                        {result.job.company ?? "未知公司"} · {formatLocation(result.job)}
                        {result.semantic_score != null
                          ? ` · 语义 ${result.semantic_score}`
                          : ""}
                        {result.rerank_score != null
                          ? ` · 重排 ${result.rerank_score}`
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
