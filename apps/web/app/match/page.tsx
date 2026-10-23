"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { matchResume, type MatchResponse } from "@/lib/api";
import { formatLocation, formatSalary, labelSource } from "@/lib/format";

const SAMPLE_RESUMES: { label: string; text: string }[] = [
  {
    label: "数据分析师 / Data Analyst",
    text: `Zhanjun Yang - Data Analyst & Analytics Specialist
Education: B.S. in Statistics, GPA 3.5/4.0
Skills: Python (pandas, numpy, scikit-learn), SQL (PostgreSQL, Snowflake), Tableau, Power BI, Metabase, dbt, A/B Testing, ETL, Excel.
Experience:
- Built pricing-strategy and user growth dashboards using SQL and Tableau.
- Designed and ran A/B tests to evaluate marketing campaigns and product conversion.
- Automated ETL data pipelines and business KPI reporting with Python and SQL.`,
  },
  {
    label: "全栈 / 后端工程师",
    text: `Senior Software Engineer / Full Stack Developer
Skills: Go, Python, TypeScript, React, Next.js, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, REST APIs, Git, CI/CD.
Experience:
- Architected high-concurrency microservices in Go and Python with PostgreSQL and Redis.
- Developed modern web dashboards in Next.js and TypeScript.
- Managed containerized deployments on Kubernetes and automated CI/CD pipelines.`,
  },
  {
    label: "注册护士 / Registered Nurse",
    text: `Registered Nurse (RN) - Acute & Critical Care
Qualifications: Bachelor of Nursing, AHPRA Registered Nurse.
Skills: Acute Care, Patient Assessment, Triage, Clinical Documentation, Medication Administration, ICU Monitoring, Infection Control.
Experience:
- Provided direct patient care and bedside telemetry in emergency and intensive care units.
- Conducted patient triage, intravenous therapy, and clinical coordination with medical teams.`,
  },
];

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
        <h1>简历与职位智能匹配</h1>
        <p>
          基于<strong>特征哈希与余弦相似度</strong>（Feature Hashing & Cosine Similarity），
          综合<strong>关键词覆盖率、职位标题权重与发布时效</strong>（Keyword Coverage, Title Weight, Recency）
          进行多维度精准打分与排序。
        </p>
      </section>

      <div style={{ marginBottom: "1.25rem", display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.9rem", color: "#64748b", fontWeight: 500 }}>快速填入示例简历：</span>
        {SAMPLE_RESUMES.map((sample) => (
          <button
            key={sample.label}
            type="button"
            className="btn-secondary"
            style={{ fontSize: "0.85rem", padding: "0.3rem 0.75rem", cursor: "pointer" }}
            onClick={() => setResume(sample.text)}
          >
            {sample.label}
          </button>
        ))}
      </div>

      <form className="match-form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="country">目标国家</label>
          <select id="country" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">全部国家 (US + AU)</option>
            <option value="US">美国 (US)</option>
            <option value="AU">澳大利亚 (AU)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="remote">工作方式</label>
          <select id="remote" value={remoteType} onChange={(e) => setRemoteType(e.target.value)}>
            <option value="">不限</option>
            <option value="remote">远程 (Remote)</option>
            <option value="hybrid">混合 (Hybrid)</option>
            <option value="onsite">现场 (Onsite)</option>
          </select>
        </div>
        <div className="field field-wide">
          <label htmlFor="resume">简历文本或候选人经历技能</label>
          <textarea
            id="resume"
            rows={8}
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            placeholder="粘贴简历内容，或输入技能、过往经验及期望职位……"
            required
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || resume.trim().length === 0}>
            {busy ? "正在匹配中…" : "开始智能匹配"}
          </button>
        </div>
        {error ? <p className="form-message error">{error}</p> : null}
      </form>

      {data ? (
        <div className="match-results">
          <h2>
            {data.results.length} 个最佳匹配职位{" "}
            <span className="engine">
              （引擎：{data.engine}
              {data.reranked ? " · 已通过交叉编码重排" : ""}）
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
                    <div className="match-score">
                      <span style={{ fontSize: "1.4rem", fontWeight: "bold" }}>{result.score}</span>
                      <span style={{ fontSize: "0.75rem", opacity: 0.8 }}>分</span>
                    </div>
                    <div className="match-body">
                      <h3>
                        <Link href={`/jobs/${result.job.id}`}>{result.job.title}</Link>
                      </h3>
                      <p className="meta">
                        {result.job.company ?? "未知公司"} · {formatLocation(result.job)} · 来源：
                        {labelSource(result.job.source)}
                      </p>

                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", margin: "0.4rem 0" }}>
                        {result.semantic_score != null ? (
                          <span className="tag" style={{ background: "#e0f2fe", color: "#0369a1", fontSize: "0.78rem" }}>
                            余弦语义: {result.semantic_score}%
                          </span>
                        ) : null}
                        {result.keyword_coverage_score != null ? (
                          <span className="tag" style={{ background: "#f0fdf4", color: "#15803d", fontSize: "0.78rem" }}>
                            关键词覆盖: {result.keyword_coverage_score}%
                          </span>
                        ) : null}
                        {result.title_weight_score != null ? (
                          <span className="tag" style={{ background: "#fef3c7", color: "#b45309", fontSize: "0.78rem" }}>
                            职位标题匹配: {result.title_weight_score}%
                          </span>
                        ) : null}
                        {result.recency_score != null ? (
                          <span className="tag" style={{ background: "#f3e8ff", color: "#6b21a8", fontSize: "0.78rem" }}>
                            时效评分: {result.recency_score}
                          </span>
                        ) : null}
                        {result.rerank_score != null ? (
                          <span className="tag" style={{ background: "#ffe4e6", color: "#be123c", fontSize: "0.78rem" }}>
                            重排分: {result.rerank_score}
                          </span>
                        ) : null}
                      </div>

                      {salary ? <p className="salary">{salary}</p> : null}

                      {result.matched_skills.length > 0 ? (
                        <div className="tags" style={{ marginTop: "0.4rem" }}>
                          <span style={{ fontSize: "0.8rem", color: "#64748b", alignSelf: "center" }}>命中技能:</span>
                          {result.matched_skills.map((skill) => (
                            <span key={skill} className="tag skill">
                              ✓ {skill}
                            </span>
                          ))}
                        </div>
                      ) : null}

                      {result.missing_skills.length > 0 ? (
                        <div className="tags" style={{ marginTop: "0.2rem" }}>
                          <span style={{ fontSize: "0.8rem", color: "#94a3b8", alignSelf: "center" }}>职位所需补充:</span>
                          {result.missing_skills.slice(0, 5).map((skill) => (
                            <span key={skill} className="tag" style={{ background: "#f1f5f9", color: "#64748b", fontSize: "0.75rem" }}>
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
