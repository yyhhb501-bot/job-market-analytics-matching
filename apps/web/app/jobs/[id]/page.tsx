import Link from "next/link";
import { notFound } from "next/navigation";

import { getJob } from "@/lib/api";
import { formatDate, formatLocation, formatSalary, titleCase } from "@/lib/format";

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
        &larr; Back to search
      </Link>

      <div className="job-card-head">
        <h1>{job.title}</h1>
        <span className="badge">{job.source}</span>
      </div>
      <p className="company">{job.company ?? "Unknown company"}</p>
      <p className="meta">{formatLocation(job)}</p>

      <div className="tags">
        {job.remote_type ? <span className="tag">{titleCase(job.remote_type)}</span> : null}
        {job.employment_type ? (
          <span className="tag">{titleCase(job.employment_type)}</span>
        ) : null}
        {posted ? <span className="tag muted">Posted {posted}</span> : null}
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
          Apply on {job.source}
        </a>
      ) : null}

      {job.summary ? (
        <>
          <h2 className="section-title">Summary</h2>
          <p className="description">{job.summary}</p>
        </>
      ) : null}

      {job.description ? (
        <>
          <h2 className="section-title">Description</h2>
          <p className="description">{job.description}</p>
        </>
      ) : null}

      <h2 className="section-title">Details</h2>
      <dl className="facts">
        <div>
          <dt>Source</dt>
          <dd>{job.source}</dd>
        </div>
        <div>
          <dt>Source job id</dt>
          <dd>{job.source_job_id}</dd>
        </div>
        <div>
          <dt>First seen</dt>
          <dd>{formatDate(job.first_seen_at) ?? "—"}</dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd>{formatDate(job.last_seen_at) ?? "—"}</dd>
        </div>
      </dl>
    </article>
  );
}
