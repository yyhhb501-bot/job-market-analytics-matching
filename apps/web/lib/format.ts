import type { Job } from "@/lib/api";

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatSalary(job: Job): string | null {
  const hasDisplay = job.salary_display_currency != null;
  const salary_min = hasDisplay ? job.salary_display_min : job.salary_min;
  const salary_max = hasDisplay ? job.salary_display_max : job.salary_max;
  const currencyCode = hasDisplay ? job.salary_display_currency : job.salary_currency;
  const salary_period = hasDisplay ? job.salary_display_period : job.salary_period;

  if (salary_min == null && salary_max == null) return null;
  const currency = currencyCode ? `${currencyCode} ` : "";
  let amount: string;
  if (salary_min != null && salary_max != null && salary_min !== salary_max) {
    amount = `${numberFormat.format(salary_min)} - ${numberFormat.format(salary_max)}`;
  } else {
    amount = numberFormat.format((salary_min ?? salary_max) as number);
  }
  const period = salary_period ? ` / ${salary_period}` : "";
  return `${currency}${amount}${period}`.trim();
}

export function formatLocation(job: Job): string {
  const parts = [job.city, job.state, job.country].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "Location not specified";
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
