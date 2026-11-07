"use client";

/* Live demo mode (build session 3): while it is on, the pages about the real campaigns
 * (Campaigns, Activity, Settings and the older sheet pages) are not shown at all — the page
 * is not even mounted, so it fetches nothing and no campaign or sheet name reaches the
 * screen. Other pages render at once; only a hidden page waits for the answer. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { PageHead } from "@/components/u";

export const HIDDEN_IN_DEMO = ["/campaigns", "/plan", "/recipes", "/activity", "/runs", "/history", "/log", "/settings",
  "/import", "/fieldmap"];

const under = (path: string, base: string) => path === base || path.startsWith(`${base}/`);

export function hiddenInDemo(path: string): boolean {
  return HIDDEN_IN_DEMO.some((b) => under(path, b)) || (path.startsWith("/sources/") && path !== "/sources/");
}

export function PresentingGate({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    fetch("/api/stack/presenting", { cache: "no-store" })
      .then((r) => r.json() as Promise<{ on: boolean }>)
      .then((r) => setOn(Boolean(r.on)))
      .catch(() => setOn(false));
  }, [path]);

  if (!hiddenInDemo(path)) return <>{children}</>;
  if (on === null) return null;
  if (!on) return <>{children}</>;
  return (
    <div className="u-page">
      <PageHead title="Hidden while Privacy is on" sub="This page shows client campaigns and sheets, so it is hidden while Privacy is on." />
      <div className="u-card u-hidden-note">
        <p className="u-muted" style={{ margin: "0 0 14px" }}>Turn Privacy off at the bottom of the menu to see it again.</p>
        <div className="u-row">
          <Link className="u-btn primary" href="/pipeline">Open Pipeline run</Link>
          <Link className="u-btn" href="/">Open Home</Link>
        </div>
      </div>
    </div>
  );
}
