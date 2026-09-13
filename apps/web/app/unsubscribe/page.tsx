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
      <h1>Unsubscribe</h1>
      {status === "unsubscribed" ? (
        <p>
          You have been unsubscribed from {name ? `“${name}”` : "this saved search"}.{" "}
          <Link href="/alerts">Back to alerts</Link>
        </p>
      ) : status === "missing" ? (
        <p className="notice">Missing unsubscribe token.</p>
      ) : (
        <p className="notice">This unsubscribe link is invalid or has already been used.</p>
      )}
    </section>
  );
}
