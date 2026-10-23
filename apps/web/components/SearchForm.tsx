import Link from "next/link";

const COUNTRIES: [string, string][] = [
  ["", "全部国家"],
  ["US", "美国"],
  ["AU", "澳大利亚"],
];

const SOURCES: [string, string][] = [
  ["", "全部来源"],
  ["indeed", "Indeed"],
  ["glassdoor", "Glassdoor"],
  ["google", "Google Jobs"],
  ["seek", "SEEK"],
  ["usajobs", "USAJOBS"],
  ["adzuna", "Adzuna"],
  ["greenhouse", "Greenhouse"],
  ["lever", "Lever"],
  ["ashby", "Ashby"],
  ["workable", "Workable"],
  ["smartrecruiters", "SmartRecruiters"],
  ["recruitee", "Recruitee"],
  ["breezy", "Breezy HR"],
  ["workday", "Workday"],
  ["personio", "Personio"],
  ["teamtailor", "Teamtailor"],
  ["bamboohr", "BambooHR"],
  ["jazzhr", "JazzHR"],
  ["pinpoint", "Pinpoint"],
  ["rippling", "Rippling"],
  ["jobvite", "Jobvite"],
  ["remoteok", "RemoteOK"],
  ["ziprecruiter", "ZipRecruiter"],
  ["linkedin", "LinkedIn"],
];

const REMOTE_TYPES: [string, string][] = [
  ["", "不限"],
  ["remote", "远程"],
  ["hybrid", "混合"],
  ["onsite", "现场"],
];

const EMPLOYMENT_TYPES: [string, string][] = [
  ["", "不限"],
  ["full_time", "全职"],
  ["part_time", "兼职"],
  ["contract", "合同"],
  ["temporary", "临时"],
  ["internship", "实习"],
];

const SORT_OPTIONS: [string, string][] = [
  ["posted_at", "最新发布"],
  ["relevance", "相关度"],
  ["salary_max", "薪资"],
  ["first_seen_at", "最近加入"],
];

const CURRENCIES: [string, string][] = [
  ["", "原币种"],
  ["USD", "美元"],
  ["AUD", "澳元"],
  ["EUR", "欧元"],
  ["GBP", "英镑"],
];

export function SearchForm({ values }: { values: Record<string, string> }) {
  return (
    <form className="search-form" action="/" method="get" data-testid="search-form">
      <div className="search-main">
        <div className="field search-keyword">
          <label htmlFor="q">职位、技能或公司</label>
          <input
            id="q"
            name="q"
            type="search"
            placeholder="例如：Registered Nurse、Data Engineer"
            defaultValue={values.q ?? ""}
            data-testid="search-q"
          />
        </div>
        <div className="field search-country">
          <label htmlFor="country">国家或地区</label>
          <select id="country" name="country" defaultValue={values.country ?? ""} data-testid="search-country">
            {COUNTRIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="field search-city">
          <label htmlFor="city">城市</label>
          <input id="city" name="city" placeholder="任意城市" defaultValue={values.city ?? ""} />
        </div>
        <div className="field field-actions search-actions">
          <button type="submit" className="btn-primary" data-testid="search-submit">搜索职位</button>
          <Link className="search-reset" href="/">清除</Link>
        </div>
      </div>
      <details className="search-advanced" open={Boolean(values.source || values.remote_type || values.employment_type || values.min_salary || values.currency || values.sort === "salary_max")}>
        <summary>更多筛选 <span>来源、工作方式、雇佣类型、薪资和排序</span></summary>
        <div className="search-advanced-grid">
          <div className="field"><label htmlFor="source">职位来源</label><select id="source" name="source" defaultValue={values.source ?? ""}>{SOURCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          <div className="field"><label htmlFor="remote_type">工作方式</label><select id="remote_type" name="remote_type" defaultValue={values.remote_type ?? ""}>{REMOTE_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          <div className="field"><label htmlFor="employment_type">雇佣类型</label><select id="employment_type" name="employment_type" defaultValue={values.employment_type ?? ""}>{EMPLOYMENT_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          <div className="field"><label htmlFor="min_salary">最低年薪</label><input id="min_salary" name="min_salary" type="number" min={0} step={5000} placeholder="例如：80000" defaultValue={values.min_salary ?? ""} /></div>
          <div className="field"><label htmlFor="currency">薪资币种</label><select id="currency" name="currency" defaultValue={values.currency ?? ""}>{CURRENCIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          <div className="field"><label htmlFor="sort">排序方式</label><select id="sort" name="sort" defaultValue={values.sort ?? "posted_at"}>{SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        </div>
      </details>
    </form>
  );
}
