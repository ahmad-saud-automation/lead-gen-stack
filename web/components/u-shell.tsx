"use client";

/* The V7 menu (the approved full-stack sample, 2026-11-06): the places, then the six pipeline
 * steps, then operations. Places not built yet are grey and open a short "planned" page.
 * On a phone it becomes a bar across the top that scrolls sideways. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, useEffect, useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { money } from "@/lib/format";
import type { ModeBox } from "@/lib/stack-types";
import type { CampaignsView, HistoryRow } from "@/lib/types";

/** Where the light/dark choice is kept. app/layout.tsx reads it before the first paint. */
export const THEME_KEY = "leadgen:theme";

type Place = { href: string; label: string; icon?: IconName; step?: number; owns: string[]; soon?: boolean; demo?: boolean;
  group?: string; real?: boolean };

/* `owns`: older addresses that now live inside this place, so the menu still lights up
 * correctly while those pages are being replaced. `soon`: not built yet. `real`: about his
 * own campaigns and sheets, so hidden while Live demo mode is on. */
export const PLACES: Place[] = [
  { href: "/", label: "Home", icon: "home", owns: [] },
  { href: "/campaigns", label: "Campaigns", icon: "list-details", owns: ["/plan", "/recipes"], real: true },
  { href: "/leads", label: "Leads", icon: "table", owns: [] },
  { href: "/sources", label: "Lead sources", icon: "file-spreadsheet", owns: ["/import", "/fieldmap"] },
  { href: "/find", label: "Find email", step: 1, owns: [], group: "Pipeline" },
  { href: "/research", label: "Website research", step: 2, owns: [] },
  { href: "/ice", label: "Ice breakers", step: 3, owns: [] },
  { href: "/email", label: "Email template", step: 4, owns: [] },
  { href: "/send", label: "Sending", step: 5, owns: [] },
  { href: "/replies", label: "Replies", step: 6, owns: [] },
  { href: "/pipeline", label: "Pipeline run", icon: "player-play", owns: ["/demo"], group: "Operations" },
  { href: "/schedules", label: "Schedules", icon: "clock", owns: [] },
  { href: "/health", label: "Health", icon: "heartbeat", owns: [] },
  { href: "/activity", label: "Activity", icon: "activity", owns: ["/runs", "/history", "/log"], real: true },
  { href: "/settings", label: "Settings", icon: "settings", owns: [], real: true },
];

const under = (path: string, base: string) => path === base || path.startsWith(`${base}/`);

function placeOf(path: string): string {
  if (path === "/") return "/";
  const hit = PLACES.find((p) => p.href !== "/" && (under(path, p.href) || p.owns.some((o) => under(path, o))));
  return hit?.href ?? "";
}

export function USidebar() {
  const path = usePathname() ?? "/";
  const [dark, setDark] = useState(false);
  const [canSignOut, setCanSignOut] = useState(false);
  const [needs, setNeeds] = useState(0);
  const [spend, setSpend] = useState<{ today: number; cap: number } | null>(null);
  const [mode, setMode] = useState<ModeBox | null>(null);

  useEffect(() => {
    setDark(document.documentElement.dataset.theme === "dark");
    // Sending runs in test mode only in this version; the box says so on every page
    fetch("/api/stack/mode", { cache: "no-store" })
      .then((r) => r.json() as Promise<ModeBox>)
      .then(setMode)
      .catch(() => setMode({ test_mode: true, title: "Test mode", text: "Emails are prepared, not sent.", can_change: false }));
    fetch("/api/auth/status", { cache: "no-store" })
      .then((r) => r.json())
      .then((s: { required?: boolean; signed_in?: boolean }) => setCanSignOut(Boolean(s.required && s.signed_in)))
      .catch(() => {});
  }, []);

  // refreshed on every page change: the badge and the spend follow what was just done
  useEffect(() => {
    if (path === "/login") return;
    Promise.all([
      fetch("/api/campaigns", { cache: "no-store" }).then((r) => r.json() as Promise<CampaignsView>),
      fetch("/api/history", { cache: "no-store" }).then((r) => r.json() as Promise<{ runs: HistoryRow[] }>),
    ]).then(([c, h]) => {
      setNeeds((c.campaigns ?? []).filter((l) => l.enabled && (!l.instantly_campaign_id || l.schedule?.problems?.length)).length);
      const today = new Date();
      const key = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const spent = (h.runs ?? []).filter((r) => !r.test_mode && String(r.when).startsWith(key))
        .reduce((n, r) => n + (Number(r.spent_usd) || 0), 0);
      setSpend({ today: spent, cap: Number(c.globals?.daily_spend_cap_usd) || 0 });
    }).catch(() => {});
  }, [path]);

  if (path === "/login") return null;

  const toggleTheme = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setDark(!dark);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // storage off: the choice lasts until the page closes
    }
  };
  const signOut = () => {
    fetch("/api/auth/logout", { method: "POST" }).catch(() => {}).finally(() => window.location.assign("/login"));
  };
  const here = placeOf(path);

  return (
    <aside className="u-side">
      <Link className="u-brand" href="/" aria-label="Lead Gen Stack, Home" style={{ textDecoration: "none" }}>
        <i aria-hidden="true">LG</i>Lead Gen Stack
      </Link>
      <nav className="u-nav" aria-label="Main">
        {PLACES.map((p) => {
          const cls = [here === p.href ? "on" : "", p.soon ? "soon" : "", p.demo ? "demo" : ""].filter(Boolean).join(" ");
          return (
            <Fragment key={p.href}>
              {p.group ? <div className="u-grp">{p.group}</div> : null}
              <Link href={p.href} className={cls || undefined} aria-current={here === p.href ? "page" : undefined}
                title={p.soon ? "Planned for the next build" : undefined}>
                {p.step ? <span className="n">{p.step}</span> : p.icon ? <Icon name={p.icon} size={18} /> : null}
                {p.label}
                {p.href === "/" && needs ? <span className="u-count" title={`${needs} campaign${needs > 1 ? "s" : ""} need you`}>{needs}</span> : null}
              </Link>
            </Fragment>
          );
        })}
      </nav>
      <div className="u-side-foot">
        {mode?.test_mode ? (
          <div className="u-mode" data-testid="test-mode-box" role="status">
            <b>{mode.title}</b>
            <br />
            <span className="u-muted">{mode.text}</span>
          </div>
        ) : null}
        {spend ? (
          <div className="u-spend">
            <b>Spent today</b>
            <br />
            {money(spend.today)}
            {spend.cap ? ` of ${money(spend.cap)} limit` : ""}
          </div>
        ) : null}
        <button type="button" className="u-btn sm" onClick={toggleTheme}>
          <Icon name={dark ? "sun" : "moon"} size={16} />
          {dark ? "Light mode" : "Dark mode"}
        </button>
        {canSignOut ? (
          <button type="button" className="u-btn sm" onClick={signOut}>
            <Icon name="logout" size={16} />
            Sign out
          </button>
        ) : null}
      </div>
    </aside>
  );
}
