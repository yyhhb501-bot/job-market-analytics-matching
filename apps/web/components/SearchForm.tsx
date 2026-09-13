const COUNTRIES: [string, string][] = [
  ["", "All countries"],
  ["US", "United States"],
  ["AU", "Australia"],
];

const SOURCES: [string, string][] = [
  ["", "All sources"],
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
  ["", "Any"],
  ["remote", "Remote"],
  ["hybrid", "Hybrid"],
  ["onsite", "On-site"],
];

const EMPLOYMENT_TYPES: [string, string][] = [
  ["", "Any"],
  ["full_time", "Full-time"],
  ["part_time", "Part-time"],
  ["contract", "Contract"],
  ["temporary", "Temporary"],
  ["internship", "Internship"],
];

const SORT_OPTIONS: [string, string][] = [
  ["posted_at", "Newest"],
  ["relevance", "Relevance"],
  ["salary_max", "Salary"],
  ["first_seen_at", "Recently added"],
];

const CURRENCIES: [string, string][] = [
  ["", "Original"],
  ["USD", "USD"],
  ["AUD", "AUD"],
  ["EUR", "EUR"],
  ["GBP", "GBP"],
];

export function SearchForm({ values }: { values: Record<string, string> }) {
  return (
    <form className="search-form" action="/" method="get">
      <div className="field field-grow">
        <label htmlFor="q">Keywords</label>
        <input
          id="q"
          name="q"
          type="search"
          placeholder="e.g. data engineer"
          defaultValue={values.q ?? ""}
        />
      </div>
      <div className="field">
        <label htmlFor="country">Country</label>
        <select id="country" name="country" defaultValue={values.country ?? ""}>
          {COUNTRIES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="source">Source</label>
        <select id="source" name="source" defaultValue={values.source ?? ""}>
          {SOURCES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="city">City</label>
        <input id="city" name="city" placeholder="e.g. Sydney" defaultValue={values.city ?? ""} />
      </div>
      <div className="field">
        <label htmlFor="remote_type">Workplace</label>
        <select id="remote_type" name="remote_type" defaultValue={values.remote_type ?? ""}>
          {REMOTE_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="employment_type">Employment</label>
        <select
          id="employment_type"
          name="employment_type"
          defaultValue={values.employment_type ?? ""}
        >
          {EMPLOYMENT_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="sort">Sort</label>
        <select id="sort" name="sort" defaultValue={values.sort ?? "posted_at"}>
          {SORT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="min_salary">Min salary</label>
        <input
          id="min_salary"
          name="min_salary"
          type="number"
          min={0}
          step={5000}
          placeholder="120000"
          defaultValue={values.min_salary ?? ""}
        />
      </div>
      <div className="field">
        <label htmlFor="currency">Salary currency</label>
        <select id="currency" name="currency" defaultValue={values.currency ?? ""}>
          {CURRENCIES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field field-actions">
        <button type="submit" className="btn-primary">
          Search
        </button>
        <a className="btn-ghost" href="/">
          Reset
        </a>
      </div>
    </form>
  );
}
