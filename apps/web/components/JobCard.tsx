import Link from "next/link";

import type { Job } from "@/lib/api";
import {
  formatDate,
  formatLocation,
  formatSalary,
  labelEmployment,
  labelRemote,
  labelSource,
} from "@/lib/format";

export function JobCard({ job }: { job: Job }) {
  const salary = formatSalary(job);
  const posted = formatDate(job.posted_at ?? job.first_seen_at);
  const externalUrl = job.apply_url ?? job.canonical_url;

  return (
    <article className="job-card" data-testid="job-card">
      <div className="job-card-head">
        <h2>
          <Link href={`/jobs/${job.id}`}>{job.title}</Link>
        </h2>
        <span className="badge" title={`来源平台：${job.source}`}>
          {labelSource(job.source)}
        </span>
      </div>
      <p className="company">{job.company ?? "未知公司"}</p>
      <p className="meta">
        {formatLocation(job)} · 来源：{labelSource(job.source)}
      </p>

      <div className="tags">
        {job.remote_type ? <span className="tag">{labelRemote(job.remote_type)}</span> : null}
        {job.employment_type ? (
          <span className="tag">{labelEmployment(job.employment_type)}</span>
        ) : null}
        {posted ? <span className="tag muted">发布于 {posted}</span> : null}
      </div>

      {salary ? <p className="salary">{salary}</p> : null}
      {job.skills && job.skills.length > 0 ? (
        <div className="tags">
          {job.skills.slice(0, 6).map((skill) => (
            <span key={skill} className="tag skill">
              {skill}
            </span>
          ))}
        </div>
      ) : null}
      {job.summary || job.description ? (
        <p className="excerpt">{(job.summary ?? job.description ?? "").slice(0, 220)}</p>
      ) : null}

      <div className="job-card-actions">
        <Link className="btn-link" href={`/jobs/${job.id}`}>
          查看详情
        </Link>
        {externalUrl ? (
          <a
            className="btn-link"
            href={externalUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            去申请
          </a>
        ) : null}
      </div>
    </article>
  );
}
