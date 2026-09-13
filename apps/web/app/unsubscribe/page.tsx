import Link from "next/link";

import { unsubscribeSavedSearch } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function UnsubscribePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const token = Array.isArray(params.token) ? params.token[0] : params.token;

  let status: "unsubscribed" | "missing" | "invalid" = "missing";
  let name: string | undefined;
  if (token) {
    try {
      const result = await unsubscribeSavedSearch(token);
      status = "unsubscribed";
      name = result.name;
    } catch {
      status = "invalid";
    }
  }

  return (
    <section className="hero">
      <h1>退订</h1>
      {status === "unsubscribed" ? (
        <p>
          已退订{name ? `“${name}”` : "该保存搜索"}。 <Link href="/alerts">返回告警页</Link>
        </p>
      ) : status === "missing" ? (
        <p className="notice">缺少退订令牌。</p>
      ) : (
        <p className="notice">该退订链接无效或已被使用。</p>
      )}
    </section>
  );
}
