"use client";

/* Health (build session 3, as the approved sample): today's tiles, the incident log, the
 * two lists (fixed automatically / always escalated) and the daily summary. The agent
 * itself is core/health.py; this page only reads what it wrote down. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { DemoBar } from "@/components/stack/common";
import { Card, PageHead, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson } from "@/lib/client-api";
import type { HealthView, Summary } from "@/lib/stack-types";

const RESULT: Record<string, [string, string]> = {
  resolved: ["Resolved", "good"], escalated: ["Escalated", "bad"], open: ["Saving again", "warn"],
};

export function SummaryMail({ s }: { s: Summary }) {
  return (
    <div className="u-mail" data-testid="daily-summary">
      <b className="u-ink">{s.title}</b>
      {s.lines.map((l, i) => <div key={i} style={{ marginTop: i === 1 ? 10 : 0 }}>{l}</div>)}
    </div>
  );
}

export function HealthPage() {
  const [v, setV] = useState<HealthView | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = () => getJson<HealthView>("/stack/health").then(setV).catch((e: Error) => setError(e.message));
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {v?.source === "demo" ? <DemoBar /> : null}
      <PageHead title="Health" sub="The monitoring agent checks every step every 5 minutes. Known issues are fixed automatically; everything else is escalated." />
      {error ? <ErrorBox title="Health could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <div className="u-stack">
          {v.clock_text ? <div className="u-note warn">{v.clock_text}</div> : null}
          <div className="u-grid3" data-testid="health-tiles">
            <Tile label="Issues today" value={v.tiles.issues} />
            <Tile label="Resolved automatically" value={v.tiles.resolved} />
            <Tile label="Waiting for you" value={v.tiles.waiting} />
          </div>
          <Card title="Incident log" sub={v.last_check ? `Last check ${v.last_check.slice(11, 16)}` : undefined}>
            {v.log.length ? (
              <div className="u-scroll">
                <table className="u-table" data-testid="incident-log">
                  <thead><tr><th>Time</th><th>Step</th><th>Issue</th><th>Action taken</th><th>Result</th></tr></thead>
                  <tbody>
                    {v.log.map((i) => {
                      const [label, tone] = RESULT[i.result] ?? [i.result, ""];
                      return (
                        <tr key={i.id}><td className="u-small">{i.time}</td><td>{i.step}</td><td>{i.issue}</td>
                          <td className="u-small">{i.action}</td><td><span className={`u-pill ${tone}`}>{label}</span></td></tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="u-pempty">No issues yet. <Link className="u-link" href="/pipeline">Start a pipeline run</Link> to see the agent at work.</div>
            )}
          </Card>
          <div className="u-grid2">
            <Card title="Resolved automatically">
              <ul className="u-checks" style={{ display: "grid" }} data-testid="allowed-list">
                {v.allowed.map((a) => <li key={a} className="ok"><span className="mk" aria-hidden="true">✓</span><span className="grow">{a}</span></li>)}
              </ul>
            </Card>
            <Card title="Always escalated">
              <ul className="u-checks" style={{ display: "grid" }}>
                {v.escalated.map((a) => <li key={a} className="no"><span className="mk" aria-hidden="true">!</span><span className="grow">{a}</span></li>)}
              </ul>
            </Card>
          </div>
          <Card title="Daily summary" sub="Written at 18:00 each day, and after every pipeline run. Shown here and on Home; never emailed.">
            {v.summary ? <SummaryMail s={v.summary} /> : <div className="u-pempty">No summary yet. The first one is written at 18:00, or when a pipeline run finishes.</div>}
          </Card>
        </div>
      )}
    </div>
  );
}
