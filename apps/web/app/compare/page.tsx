import Link from "next/link";

import { compareMarkets, type CompareAreaMetrics } from "@/lib/api";
import { formatDate, labelSource } from "@/lib/format";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

function single(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value ?? undefined;
}

function num(value: number | null | undefined, fallback = "—"): string {
  return value === null || value === undefined ? fallback : value.toLocaleString();
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

function salary(area: CompareAreaMetrics): string {
  if (area.salary_median === null) return "—";
  return `${area.salary_median.toLocaleString()} ${area.salary_currency ?? ""}`.trim();
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const values = {
    q: single(sp.q) ?? "",
    a_country: single(sp.a_country) ?? "",
    a_state: single(sp.a_state) ?? "",
    a_city: single(sp.a_city) ?? "",
    b_country: single(sp.b_country) ?? "",
    b_state: single(sp.b_state) ?? "",
    b_city: single(sp.b_city) ?? "",
    days: single(sp.days) ?? "30",
    currency: single(sp.currency) ?? "USD",
  };

  let data = null;
  let error: string | null = null;
  try {
    data = await compareMarkets({
      q: values.q || undefined,
      area_a_country: values.a_country || undefined,
      area_a_state: values.a_state || undefined,
      area_a_city: values.a_city || undefined,
      area_b_country: values.b_country || undefined,
      area_b_state: values.b_state || undefined,
      area_b_city: values.b_city || undefined,
      days: values.days,
      currency: values.currency,
    });
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "无法连接 API";
  }

  const rows: { label: string; a: string; b: string }[] = data
    ? [
        { label: "活跃职位", a: num(data.area_a.active_jobs), b: num(data.area_b.active_jobs) },
        {
          label: `近 ${data.period_days} 天新增`,
          a: num(data.area_a.new_jobs),
          b: num(data.area_b.new_jobs),
        },
        {
          label: "招聘公司数",
          a: num(data.area_a.unique_companies),
          b: num(data.area_b.unique_companies),
        },
        {
          label: "远程职位占比",
          a: percent(data.area_a.remote_ratio),
          b: percent(data.area_b.remote_ratio),
        },
        {
          label: "有薪资比例",
          a: percent(data.area_a.salary_coverage),
          b: percent(data.area_b.salary_coverage),
        },
        { label: "薪资中位数", a: salary(data.area_a), b: salary(data.area_b) },
      ]
    : [];

  return (
    <>
      <section className="hero">
        <h1>地区就业市场对比</h1>
        <p>比较两个地区同一职业的岗位数量、薪资、远程比例、技能与趋势。</p>
      </section>

      <form className="search-form" action="/compare" method="get" data-testid="compare-form">
        <div className="field field-grow">
          <label htmlFor="q">职业</label>
          <input
            id="q"
            name="q"
            placeholder="例如：data analyst / registered nurse"
            defaultValue={values.q}
          />
        </div>
        <div className="field">
          <label>地区 A · 国家</label>
          <select name="a_country" defaultValue={values.a_country}>
            <option value="">不限</option>
            <option value="AU">澳大利亚</option>
            <option value="US">美国</option>
          </select>
        </div>
        <div className="field">
          <label>地区 A · 城市</label>
          <input name="a_city" placeholder="Melbourne" defaultValue={values.a_city} />
        </div>
        <div className="field">
          <label>地区 B · 国家</label>
          <select name="b_country" defaultValue={values.b_country}>
            <option value="">不限</option>
            <option value="US">美国</option>
            <option value="AU">澳大利亚</option>
          </select>
        </div>
        <div className="field">
          <label>地区 B · 城市</label>
          <input name="b_city" placeholder="San Francisco" defaultValue={values.b_city} />
        </div>
        <div className="field">
          <label>时间范围</label>
          <select name="days" defaultValue={values.days}>
            <option value="7">最近 7 天</option>
            <option value="30">最近 30 天</option>
            <option value="90">最近 90 天</option>
          </select>
        </div>
        <div className="field">
          <label>币种</label>
          <select name="currency" defaultValue={values.currency}>
            <option value="USD">USD 美元</option>
            <option value="AUD">AUD 澳元</option>
          </select>
        </div>
        <div className="field field-actions">
          <button type="submit" className="btn-primary">
            开始对比
          </button>
          <Link className="btn-ghost" href="/compare">
            重置
          </Link>
        </div>
      </form>

      {error ? <div className="notice">无法连接 API（{error}）。</div> : null}

      {data ? (
        <>
          <div className="notice" data-testid="compare-summary">
            {data.summary}
            <div className="meta" style={{ marginTop: 6 }}>
              数据质量：{data.data_quality.deduplicated ? "已按去重统计" : "含重复来源"} ·
              数据更新时间：{formatDate(data.data_quality.last_updated_at) ?? "—"} · 薪资样本：
              {data.area_a.label} {data.area_a.salary_sample} 条 / {data.area_b.label}{" "}
              {data.area_b.salary_sample} 条
            </div>
          </div>

          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>指标</th>
                  <th>{data.area_a.label}</th>
                  <th>{data.area_b.label}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.a}</td>
                    <td>{row.b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="job-grid" style={{ marginTop: 18 }}>
            <div className="job-card">
              <div className="job-card-head">
                <h2>高频技能 · {data.area_a.label}</h2>
              </div>
              {data.area_a.top_skills.length === 0 ? (
                <p className="meta">暂无</p>
              ) : (
                <ul className="bars">
                  {data.area_a.top_skills.map((item) => (
                    <li key={item.skill}>
                      <span>{item.skill}</span>
                      <span className="meta">{item.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="job-card">
              <div className="job-card-head">
                <h2>高频技能 · {data.area_b.label}</h2>
              </div>
              {data.area_b.top_skills.length === 0 ? (
                <p className="meta">暂无</p>
              ) : (
                <ul className="bars">
                  {data.area_b.top_skills.map((item) => (
                    <li key={item.skill}>
                      <span>{item.skill}</span>
                      <span className="meta">{item.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="job-card">
              <div className="job-card-head">
                <h2>来源构成 · {data.area_a.label}</h2>
              </div>
              <ul className="bars">
                {data.area_a.source_counts.map((item) => (
                  <li key={item.source}>
                    <span>{labelSource(item.source)}</span>
                    <span className="meta">{item.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="job-card">
              <div className="job-card-head">
                <h2>来源构成 · {data.area_b.label}</h2>
              </div>
              <ul className="bars">
                {data.area_b.source_counts.map((item) => (
                  <li key={item.source}>
                    <span>{labelSource(item.source)}</span>
                    <span className="meta">{item.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
