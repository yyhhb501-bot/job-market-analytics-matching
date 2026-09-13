import Link from "next/link";
import { notFound } from "next/navigation";

import { getJob } from "@/lib/api";
import {
  formatDate,
  formatLocation,
  formatSalary,
  labelEmployment,
  labelRemote,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const job = await getJob(id);
  if (!job) notFound();

  const salary = formatSalary(job);
  const externalUrl = job.apply_url ?? job.canonical_url;
  const posted = formatDate(job.posted_at);

  return (
    <article className="job-detail">
      <Link href="/" className="back-link">
        &larr; 返回搜索
      </Link>

      <div className="job-card-head">
        <h1>{job.title}</h1>
        <span className="badge">{job.source}</span>
      </div>
      <p className="company">{job.company ?? "未知公司"}</p>
      <p className="meta">{formatLocation(job)}</p>

      <div className="tags">
        {job.remote_type ? <span className="tag">{labelRemote(job.remote_type)}</span> : null}
        {job.employment_type ? (
          <span className="tag">{labelEmployment(job.employment_type)}</span>
        ) : null}
        {posted ? <span className="tag muted">发布于 {posted}</span> : null}
      </div>

      {salary ? <p className="salary large">{salary}</p> : null}

      {job.skills && job.skills.length > 0 ? (
        <div className="tags">
          {job.skills.map((skill) => (
            <span key={skill} className="tag skill">
              {skill}
            </span>
          ))}
        </div>
      ) : null}

      {externalUrl ? (
        <a
          className="btn-primary inline"
          href={externalUrl}
          target="_blank"
          rel="noreferrer noopener"
        >
          前往 {job.source} 申请
        </a>
      ) : null}

      {job.summary ? (
        <>
          <h2 className="section-title">摘要</h2>
          <p className="description">{job.summary}</p>
        </>
      ) : null}

      {job.description ? (
        <>
          <h2 className="section-title">职位描述</h2>
          <p className="description">{job.description}</p>
        </>
      ) : null}

      <h2 className="section-title">详情</h2>
      <dl className="facts">
        <div>
          <dt>来源</dt>
          <dd>{job.source}</dd>
        </div>
        <div>
          <dt>来源职位 ID</dt>
          <dd>{job.source_job_id}</dd>
        </div>
        <div>
          <dt>首次出现</dt>
          <dd>{formatDate(job.first_seen_at) ?? "—"}</dd>
        </div>
        <div>
          <dt>最近出现</dt>
          <dd>{formatDate(job.last_seen_at) ?? "—"}</dd>
        </div>
      </dl>
    </article>
  );
}
