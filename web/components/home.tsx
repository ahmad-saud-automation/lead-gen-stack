"use client";

/* Home: what happens today, and anything that needs you. A new user (anything in the setup
 * list not done yet) gets the setup checklist first — each step says what it is for and has
 * the button that does it. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { describe } from "@/components/activity/list";
import { HealthToday, NeedsDecision, PipelineCard } from "@/components/stack/decisions";
import { Card, Checklist, PageHead, Progress, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson } from "@/lib/client-api";
import { money, num } from "@/lib/format";
import { campaignStatus, runHref } from "@/lib/status";
import type { DecisionsView } from "@/lib/stack-types";
import type { CampaignsView, Config, HistoryRow, LedgerView, SheetInfo } from "@/lib/types";
import { whenWords } from "@/lib/words";

type Data = { sheet: SheetInfo | null; cfg: Config; camps: CampaignsView; hist: HistoryRow[]; ledger: LedgerView | null };

export function Home() {
  const [d, setD] = useState<Data | null>(null);
  const [dec, setDec] = useState<DecisionsView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // Live demo mode first: when it is on, nothing about the real campaigns is even fetched
    getJson<DecisionsView>("/stack/decisions")
      .then((x) => {
        setDec(x);
        if (x.presenting) return;
        return Promise.all([
          getJson<SheetInfo>("/sheets/info").catch(() => null),
          getJson<Config>("/config"),
          getJson<CampaignsView>("/campaigns"),
          getJson<{ runs: HistoryRow[] }>("/history"),
          getJson<LedgerView>("/ledger").catch(() => null),
        ]).then(([sheet, cfg, camps, h, ledger]) => setD({ sheet, cfg, camps, hist: h.runs ?? [], ledger }));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="u-page"><PageHead title="Home" /><ErrorBox title="Home could not be loaded" detail={error} /></div>;
  if (dec?.presenting) return <DemoHome dec={dec} />;
  if (!d || !dec) return <div className="u-page"><PageHead title="Home" /><div className="u-card"><Loading rows={6} /></div></div>;

  const keys = d.cfg.keys_set ?? {};
  const camps = d.camps.campaigns ?? [];
  const ranTest = d.hist.some((r) => (r.kind ?? "run") === "run");
  const setup = [
    { ok: !!d.sheet?.ok, text: <><b className="u-ink">Connect your Google Sheet</b><div className="u-small u-muted">{d.sheet?.ok ? `Connected — ${d.sheet.detail}.` : "Where your leads are, and where results are written."}</div></>, href: "/settings#s-conn", btn: "Connect" },
    { ok: !!keys.millionverifier_api_key, text: <><b className="u-ink">Add your email-checking key (MillionVerifier)</b><div className="u-small u-muted">Every email is checked before it is sent.</div></>, href: "/settings#s-conn", btn: "Add key" },
    { ok: !!keys.instantly_api_key, text: <><b className="u-ink">Add your Instantly key</b><div className="u-small u-muted">So the app can list your Instantly campaigns and send leads to them.</div></>, href: "/settings#s-conn", btn: "Add key" },
    { ok: camps.length > 0, text: <><b className="u-ink">Create your first campaign</b><div className="u-small u-muted">Which leads, how many, and where they go.</div></>, href: "/campaigns/new", btn: "Create" },
    { ok: ranTest, text: <><b className="u-ink">Run a free test</b><div className="u-small u-muted">Shows what a real run would do. Nothing is spent and nothing is sent.</div></>, href: camps[0] ? `/campaigns/${encodeURIComponent(camps[0].id)}` : "/campaigns", btn: "Open campaign" },
  ];
  const done = setup.filter((s) => s.ok).length;

  // today
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 864e5);
  const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const runs = d.hist.filter((r) => (r.kind ?? "run") === "run");
  const foundWeek = runs.filter((r) => !r.test_mode && new Date(r.when.replace(" ", "T")) >= weekAgo).reduce((n, r) => n + (r.found || 0), 0);
  const spentMonth = d.hist.filter((r) => !r.test_mode && r.when.startsWith(monthKey)).reduce((n, r) => n + (Number(r.spent_usd) || 0), 0);
  const next = camps.filter((c) => c.enabled && c.schedule?.active && c.schedule.next_run).sort((a, b) => (a.schedule!.next_run < b.schedule!.next_run ? -1 : 1))[0];
  const issues = (id: string) => (d.camps.issues ?? []).filter((i) => i.campaign === id).length;
  const needs = camps.map((c) => ({ c, st: campaignStatus(c, issues(c.id)) })).filter((x) => x.st.tone === "attn");

  return (
    <div className="u-page">
      <PageHead title="Home" sub="What happens today, and anything that needs you." />

      {done < setup.length ? (
        <Card title="Get set up" sub="Five short steps. Each one turns green when it is done." right={<b className="u-ink">{done} of {setup.length} done</b>}>
          <Progress done={done} total={setup.length} />
          <Checklist numbered items={setup.map((s) => ({ ok: s.ok ? true : null, text: s.text, action: s.ok ? undefined : <Link className="u-btn sm" href={s.href}>{s.btn}</Link> }))} />
        </Card>
      ) : null}

      <div className="u-grid4" style={{ marginTop: done < setup.length ? 14 : 0 }}>
        <Tile label="Next run" value={next ? whenWords(next.schedule!.next_run) : "None planned"}
          sub={next ? `${next.name} · ${next.schedule!.test_mode ? "free test" : "live"}` : "Campaigns run when you press Run, or on their schedule"} />
        <Tile label="Emails found this week" value={num(foundWeek)} sub="in live runs" />
        <Tile label="Found, not sent yet" value={num(d.ledger?.pending_push ?? 0)} sub={<Link className="u-link" href="/activity">See the runs →</Link>} />
        <Tile label="Spent this month" value={money(spentMonth)} sub={`limit ${money(d.camps.globals?.daily_spend_cap_usd)} per day`} />
      </div>

      <div className="u-stack" style={{ marginTop: 14 }}>
        {dec.decisions.length ? <NeedsDecision d={dec} /> : null}
        {needs.length ? (
          <Card title="Needs you" sub="Each has a button that takes you to the fix.">
            <Checklist items={needs.map(({ c, st }) => ({
              ok: false, text: <>“{c.name}”: {st.why}</>,
              action: <Link className="u-btn sm" href={`/campaigns/${encodeURIComponent(c.id)}`}>Fix</Link>,
            }))} />
          </Card>
        ) : null}

        <Card title="Latest activity" right={<Link className="u-link" href="/activity">All activity →</Link>}>
          {d.hist.length === 0 ? <p className="u-muted">Nothing has run yet.</p> : (
            <div className="u-list">
              {d.hist.slice(0, 4).map((r) => {
                const x = describe(r);
                return (
                  <Link key={r.run_id} className="u-li" href={runHref(r.run_id)} style={{ gridTemplateColumns: "28px minmax(0,1fr) auto" }}>
                    <span className={`u-dot ${x.tone}`}>{x.icon}</span>
                    <div className="t"><b>{x.title}</b><div>{x.detail}</div></div>
                    <span className="u-small u-muted">Open</span>
                  </Link>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

/** Home while Privacy is on: results of the campaign that ran last, and what needs a decision. */
function DemoHome({ dec }: { dec: DecisionsView }) {
  const c = dec.counts;
  const name = dec.name ?? "Demo firms";
  return (
    <div className="u-page">
      <PageHead title="Home" sub={`Results on ${name}, and the items that need a decision.`}
        actions={<Link className="u-btn primary" href={`/pipeline?source=${encodeURIComponent(dec.source ?? "demo")}`}>Open Pipeline run</Link>} />
      <div className="u-grid4">
        <Tile label="Active leads" value={num(c.leads)} sub={name} />
        <Tile label="Emails found" value={num(c.emails)} sub={c.websites ? `of ${c.websites} leads with a website` : "Start a pipeline run"} />
        <Tile label="Sent" value={num(c.sent)} sub={dec.demo === false ? "Pushed to a Draft campaign" : "Test mode"} />
        <Tile label="Replies" value={num(c.replies)} sub={`${c.interested} interested`} />
      </div>
      <div className="u-stack" style={{ marginTop: 14 }}>
        <PipelineCard d={dec} />
        <div className="u-grid2">
          <NeedsDecision d={dec} />
          <HealthToday d={dec} />
        </div>
      </div>
    </div>
  );
}
