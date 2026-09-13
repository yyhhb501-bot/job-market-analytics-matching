import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Job Aggregator — US & Australia",
  description:
    "Search aggregated jobs from public ATS boards, USAJOBS, SEEK, Indeed, Glassdoor and Adzuna.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <div className="container header-inner">
            <Link href="/" className="brand">
              Job Aggregator
            </Link>
            <span className="brand-sub">United States &amp; Australia</span>
            <nav className="site-nav">
              <Link href="/">Search</Link>
              <Link href="/match">Résumé match</Link>
              <Link href="/alerts">Alerts</Link>
              <Link href="/status">Status</Link>
            </nav>
          </div>
        </header>
        <main className="container">{children}</main>
        <footer className="site-footer">
          <div className="container">
            Aggregated from public ATS boards, USAJOBS, SEEK, Indeed, Glassdoor and Adzuna.
          </div>
        </footer>
      </body>
    </html>
  );
}
