import type { Job } from "@/lib/api";

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const PERIOD_LABELS: Record<string, string> = {
  year: "年",
  month: "月",
  week: "周",
  day: "天",
  hour: "小时",
};

const REMOTE_LABELS: Record<string, string> = {
  remote: "远程",
  hybrid: "混合",
  onsite: "现场",
  unknown: "未知",
};

const EMPLOYMENT_LABELS: Record<string, string> = {
  full_time: "全职",
  part_time: "兼职",
  contract: "合同",
  temporary: "临时",
  internship: "实习",
  casual: "临时工",
  other: "其他",
};

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
  const period = salary_period ? ` / ${PERIOD_LABELS[salary_period] ?? salary_period}` : "";
  return `${currency}${amount}${period}`.trim();
}

export function formatLocation(job: Job): string {
  const parts = [job.city, job.state, job.country].filter(Boolean);
  return parts.length > 0 ? parts.join("，") : "地点未注明";
}

export function formatDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}

export function labelRemote(value: string | null | undefined): string {
  if (!value) return "";
  return REMOTE_LABELS[value] ?? value;
}

export function labelEmployment(value: string | null | undefined): string {
  if (!value) return "";
  return EMPLOYMENT_LABELS[value] ?? value;
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
