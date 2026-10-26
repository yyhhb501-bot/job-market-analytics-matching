"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import type { MatchResponse } from "@/lib/api";
import { formatLocation, formatSalary, labelSource } from "@/lib/format";

/**
 * Anonymous match demonstration — no registration, no phone number.
 *
 * Submits to /api/demo-match (keyless demo endpoint on the API server with a
 * conservative per-proxy rate limit). Resume text is processed in memory only: it is
 * not stored and not written to any log. Samples are fictional personas.
 */

const DEMO_RESUME_MAX_CHARS = 8000;

const SAMPLE_RESUMES: { label: string; text: string }[] = [
  {
    label: "数据分析师 / Data Analyst",
    text: `Data Analyst — Analytics Specialist
Education: B.S. in Statistics
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

export default function DemoMatchPage() {
  const [illustrative, setIllustrative] = useState(false);
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
      const response = await fetch("/api/demo-match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume,
          country: country || null,
          remote_type: remoteType || null,
          limit: 10,
          illustrative,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body?.detail ?? "匹配失败");
      }
      setData(body as MatchResponse);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "匹配失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>简历匹配 · 免注册演示</h1>
        <p>
          无需注册或手机号即可体验：基于<strong>特征哈希与余弦相似度</strong>，综合
          <strong>关键词覆盖率、职位标题权重与发布时效</strong>的多维评分排序。
          演示为受限模式（简历最长 {DEMO_RESUME_MAX_CHARS} 字符、最多返回 10 条、限每分钟少数几次请求）；
          输入仅在内存中处理，不保存、不记录。
        </p>
      </section>

      <div className="notice">
        <label><input type="checkbox" checked={illustrative} onChange={event=>{setIllustrative(event.target.checked);setData(null);}} /> 使用虚构示例职位体验算法（非真实招聘，不计入采集数量）</label>
        <p className="small">默认仅匹配已批准公开展示的真实职位；没有公开样本时，可勾选示例模式。真实采集数量见<Link href="/collection">采集看板</Link>。</p>
      </div>

      <div style={{ marginBottom: "1.25rem", display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.9rem", color: "#64748b", fontWeight: 500 }}>一键填入虚构示例简历：</span>
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
          <label htmlFor="demo-resume">
            简历文本或技能经历（虚构内容即可，最长 {DEMO_RESUME_MAX_CHARS} 字符）
          </label>
          <textarea
            id="demo-resume"
            rows={8}
            maxLength={DEMO_RESUME_MAX_CHARS}
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            placeholder="粘贴简历内容，或输入技能、过往经验及期望职位……"
            required
          />
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary" disabled={busy || resume.trim().length === 0}>
            {busy ? "正在匹配中…" : "开始匹配演示"}
          </button>
        </div>
      </form>
      {error ? <p className="form-message error">{error}</p> : null}

      {data ? (
        <div className="match-results">
          <h2>
            {data.results.length} 个匹配职位{" "}
            <span className="engine">
              （引擎：{data.engine}
              {data.reranked ? " · 已通过交叉编码重排" : ""}）
            </span>
          </h2>
          {data.results.length === 0 ? (
            <p className="empty small">当前筛选条件下暂无已批准公开展示的职位。你可以切换上方“虚构示例职位”体验算法，或前往采集看板查看真实统计。</p>
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
                        {data.data_scope==="illustrative_examples"?<span>{result.job.title} · 虚构示例</span>:<Link href={`/jobs/${result.job.id}`}>{result.job.title}</Link>}
                      </h3>
                      <p className="meta">
                        {result.job.company ?? "未知公司"} · {formatLocation(result.job)} · 来源：
                        {labelSource(result.job.source)}
                      </p>

                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", margin: "0.4rem 0" }}>
                        {result.semantic_score != null ? (
                          <span className="tag" style={{ background: "#e0f2fe", color: "#0369a1", fontSize: "0.78rem" }}>
                            余弦相似度: {result.semantic_score}%
                          </span>
                        ) : data.engine.startsWith("semantic") ? (
                          <span
                            className="tag"
                            title="该职位无可兼容向量，本条按关键词降级排序，未参与余弦比较"
                            style={{ background: "#f1f5f9", color: "#475569", fontSize: "0.78rem" }}
                          >
                            该职位无向量 · 关键词降级
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
                      </div>

                      {salary ? <p className="salary">{salary}</p> : null}

                      {result.matched_skills.length > 0 ? (
                        <p className="skills">
                          <strong>匹配技能：</strong>
                          {result.matched_skills.join("、")}
                        </p>
                      ) : null}
                      {result.missing_skills.length > 0 ? (
                        <p className="skills">
                          <strong>缺失技能：</strong>
                          {result.missing_skills.join("、")}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          <p className="small" style={{ opacity: 0.75, marginTop: "0.75rem" }}>
            最终分数 = 0.40 × 余弦相似度 + 0.30 × 关键词覆盖 + 0.15 × 标题权重 + 0.15 × 时效（无向量职位按 0.55 / 0.25 / 0.20 的关键词权重组合降级）。
            {data.data_scope==="illustrative_examples"?"本次使用虚构职位，仅演示真实算法计算，不代表招聘或真实采集结果。":""}
            {data.reranked?"本次另启用了重排：最终结果为重排分数与上述组合分数各占 50%。":""}
            {data.data_scope==="illustrative_examples"?"本次只考察固定虚构示例，不查询私人采集库；示例没有发布时间，时效分采用缺失日期的默认值。":"演示模式从最近公开职位中最多考察 200 条候选，结果不代表全库匹配。"}
          </p>
        </div>
      ) : null}
    </>
  );
}
