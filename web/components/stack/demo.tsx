"use client";

/* Live demo (build session 3, as the approved sample). Start demo asks the engine for ONE
 * one-time trigger 10 seconds ahead; when it fires, the engine runs steps 1–6 on the Demo
 * firms by itself. This page only watches: it reads /api/stack/demo/status every half
 * second while the run is counting down or running. The Live demo mode switch hides his own
 * campaign and sheet names everywhere in the app. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { StepValue } from "@/components/stack/common";
import { SummaryMail } from "@/components/stack/health";
import { Icon } from "@/components/icons";
import { PageHead, SwitchRow, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { reloadWithNote } from "@/lib/nav";
import type { DemoStatus } from "@/lib/stack-types";

const LIVE = ["scheduled", "running"];

export function DemoPage() {
  const [v, setV] = useState<DemoStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [presenting, setPresenting] = useState<boolean | null>(null);
  const timer = useRef<number | null>(null);

  const load = async () => {
    try {
      const r = await getJson<DemoStatus>("/stack/demo/status");
      setV(r);
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  };
  const poll = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const r = await load();
      if (r?.run && LIVE.includes(r.run.state)) poll();
    }, 500);
  };
  useEffect(() => {
    load().then((r) => { if (r?.run && LIVE.includes(r.run.state)) poll(); });
    getJson<{ on: boolean }>("/stack/presenting").then((r) => setPresenting(r.on)).catch(() => setPresenting(false));
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string }>("/stack/demo/start");
      if (!r.ok) throw new Error(r.error || "The demo did not start.");
      await load();
      poll();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setBusy(true);
    setProblem("");
    if (timer.current) window.clearTimeout(timer.current);
    await postJson("/stack/demo/reset").catch(() => {});
    await load();
    setBusy(false);
  };
  const present = async (on: boolean) => {
    await postJson("/stack/presenting", { on });
    reloadWithNote(on ? "Live demo mode is on. Only Demo firms are shown." : "Live demo mode is off.");
  };

  const run = v?.run ?? null;
  const live = !!run && LIVE.includes(run.state);
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Live demo" sub="Runs the full pipeline on 12 sample leads. A trigger is scheduled 10 seconds ahead, then each step starts automatically."
        actions={<>
          <button type="button" className="u-btn" disabled={busy} onClick={reset}>Reset</button>
          <button type="button" className="u-btn primary" disabled={busy || live} onClick={start} data-testid="demo-start">
            <Icon name="player-play" size={16} />{live ? "Running…" : "Start demo"}
          </button>
        </>} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not started" detail={problem} /></div> : null}
      {presenting !== null ? (
        <div className="u-card" style={{ marginBottom: 14, paddingTop: 4, paddingBottom: 4 }}>
          <SwitchRow title="Live demo mode" checked={presenting} onChange={present}
            desc="Hides your own campaign and sheet names everywhere in the app. Only Demo firms are shown." />
        </div>
      ) : null}
      {error ? <ErrorBox title="The demo could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <>
          <div className="u-card" data-testid="demo-trigger"><Trigger v={v} /></div>
          <div className="u-card" style={{ marginTop: 14 }}>
            <div className="u-chain" data-testid="demo-chain">
              {v.chain.map((c, i) => (
                <div key={c.key} className={`u-cst ${c.state}`}>
                  <div className="h">{c.state === "done" ? "✓ " : ""}{i + 1} · {c.label}</div>
                  <div className="v">{c.n}<span className="u-small u-muted" style={{ fontWeight: 400 }}> / {v.total}</span></div>
                  <div className="s">{{ run: "Running", done: "Completed", waiting: "Waiting for you", pending: "Pending" }[c.state]}</div>
                </div>
              ))}
            </div>
            <div className="u-progress" role="progressbar" aria-valuenow={v.progress} aria-valuemax={100}><span style={{ width: `${v.progress}%` }} /></div>
          </div>
          <div className="u-split u-demo-split">
            <div className="u-pane list">
              <table className="u-table" data-testid="demo-leads">
                <thead><tr><th>Company</th><th>Website</th><th>Email</th><th>Ice breaker</th><th>Template</th><th>Sent</th><th>Reply</th></tr></thead>
                <tbody>
                  {v.leads.map((l) => (
                    <tr key={l.key}><td><b className="u-ink">{l.company}</b></td><td><StepValue p={l.website} /></td><td><StepValue p={l.email} /></td>
                      <td><StepValue p={l.ice} /></td><td>{l.template ? <span className="u-pill good">{l.template}</span> : <span className="u-muted">—</span>}</td>
                      <td><StepValue p={l.sent} /></td><td><StepValue p={l.reply} /></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="u-pane detail">
              <h3 className="u-h4" style={{ marginTop: 0, marginBottom: 8 }}>Activity</h3>
              <div className="u-log" data-testid="demo-log">
                {run?.events.length ? run.events.map((e, i) => (
                  <div key={run.events.length - i} className={`u-ev ${e.tone}`}><span className="t">{e.t}</span>{e.text}</div>
                )) : <div className="u-muted">No activity yet.</div>}
              </div>
            </div>
          </div>
          {v.result ? (
            <div className="u-card" style={{ marginTop: 14 }} data-testid="demo-result">
              <div className="u-card-head">
                <div><h2 className="u-h2">Pipeline completed in {v.result.seconds} seconds</h2><p>Started by a scheduled trigger. No manual steps.</p></div>
                <Link className="u-btn sm" href="/health">Open Health</Link>
              </div>
              <div className="u-grid4">
                <Tile label="Leads" value={v.result.leads} />
                <Tile label="Websites researched" value={v.result.websites} sub="websites found" />
                <Tile label="Emails found" value={v.result.emails} />
                <Tile label="Sent (test)" value={v.result.sent} sub={`${v.result.interested} interested repl${v.result.interested === 1 ? "y" : "ies"}`} />
              </div>
              <div className="u-small u-muted" style={{ margin: "10px 0" }}>
                Cost of this demo: $0.00. The same run on the real services would cost about ${v.result.would_cost.toFixed(2)}.
              </div>
              {v.result.summary ? <SummaryMail s={v.result.summary} /> : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function Trigger({ v }: { v: DemoStatus }) {
  const r = v.run;
  let icon = "clock", cls = "", title = "Ready", sub = "Select Start demo. A one-time trigger is scheduled 10 seconds ahead.";
  let extra: React.ReactNode = null;
  if (r?.state === "scheduled") {
    title = `Trigger scheduled for ${r.due}`;
    sub = `Starts automatically in ${r.seconds_left} second${r.seconds_left === 1 ? "" : "s"}.`;
    extra = <Link className="u-btn sm" href="/schedules">View in Schedules</Link>;
  } else if (r?.state === "running") {
    icon = "bolt"; cls = "ok"; title = `Trigger fired at ${r.started.slice(11, 19)}`; sub = `Pipeline running on ${v.total} sample leads.`;
  } else if (r?.state === "done") {
    icon = "check"; cls = "ok"; title = "Pipeline completed"; sub = `Trigger fired at ${r.started.slice(11, 19)}. Every step ran by itself.`;
  } else if (r && ["waiting", "failed", "interrupted"].includes(r.state)) {
    icon = "alert-circle"; cls = "bad"; title = "Stopped: waiting for you"; sub = r.message || "Open Health for details.";
    extra = <Link className="u-btn sm" href="/health">Open Health</Link>;
  } else if (r?.state === "stopped") {
    sub = "The last run was stopped. Select Start demo to run it again.";
  }
  return (
    <div className="u-trig">
      <span className={`mk ${cls}`} aria-hidden="true">
        {icon === "clock" ? <Icon name="clock" size={18} /> : icon === "bolt" ? <Icon name="player-play" size={16} /> : icon === "check" ? "✓" : "!"}
      </span>
      <div className="grow"><b className="u-ink">{title}</b><div className="u-small u-muted">{sub}</div></div>
      {extra}
    </div>
  );
}
