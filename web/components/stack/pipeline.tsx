"use client";

/* Pipeline run (2026-11-06; replaces "Live demo" in the menu). Pick a campaign that can run,
 * select Start run: the engine schedules ONE one-time trigger 10 seconds ahead, and when it
 * fires it runs steps 1–6 by itself. For a pipeline campaign the services are real and the
 * push goes to a Draft Instantly campaign (no email can go out). This page only watches:
 * /api/stack/demo/status?source=… every half second while the run is counting down or
 * running. Each step card says what the step PRODUCED, not how many leads it looked at. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { StepValue, realPickers } from "@/components/stack/common";
import { SummaryMail } from "@/components/stack/health";
import { Icon } from "@/components/icons";
import { PageHead, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import type { DemoStatus, Picker } from "@/lib/stack-types";

const LIVE = ["scheduled", "running"];

export function PipelineRunPage() {
  const [pickers, setPickers] = useState<Picker[]>([]);
  const [source, setSource] = useState("");
  const [v, setV] = useState<DemoStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const timer = useRef<number | null>(null);
  const src = useRef("");

  const load = async () => {
    try {
      const r = await getJson<DemoStatus>(`/stack/demo/status?source=${encodeURIComponent(src.current)}`);
      if (r.error) throw new Error(r.error);
      setV(r);
      setError("");
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
  const pick = (id: string) => {
    src.current = id;
    setSource(id);
    setV(null);
    const u = new URL(window.location.href);
    u.searchParams.set("source", id);
    window.history.replaceState(null, "", u.toString());
    load().then((r) => { if (r?.run && LIVE.includes(r.run.state)) poll(); });
  };
  useEffect(() => {
    getJson<{ pickers: Picker[] }>("/stack/pickers")
      .then((r) => {
        const runnable = realPickers((r.pickers ?? []).filter((p) => p.runnable));
        setPickers(runnable);
        const want = new URLSearchParams(window.location.search).get("source") ?? "";
        const first = runnable.find((p) => p.id === want) ?? runnable.find((p) => !p.demo) ?? runnable[0];
        if (first) pick(first.id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string }>("/stack/run/start", { source });
      if (!r.ok) throw new Error(r.error || "The run did not start.");
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

  const run = v?.run ?? null;
  const live = !!run && LIVE.includes(run.state);
  const sample = v?.demo ?? source === "demo";
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Pipeline run"
        sub="Runs all six steps on one campaign's leads. A trigger is scheduled 10 seconds ahead, then each step starts by itself."
        actions={<>
          {pickers.length > 1 ? (
            <select className="u-input" aria-label="Campaign" value={source} disabled={live} onChange={(e) => pick(e.target.value)}
              data-testid="run-source" style={{ width: "auto" }}>
              {pickers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          ) : null}
          {sample ? <button type="button" className="u-btn" disabled={busy || live} onClick={reset}>Reset</button> : null}
          <button type="button" className="u-btn primary" disabled={busy || live || !source} onClick={start} data-testid="run-start">
            <Icon name="player-play" size={16} />{live ? "Running…" : "Start run"}
          </button>
        </>} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not started" detail={problem} /></div> : null}
      {error ? <ErrorBox title="The run could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <>
          <div className="u-card" data-testid="run-trigger"><Trigger v={v} sample={sample} /></div>
          <div className="u-card" style={{ marginTop: 14 }}>
            <div className="u-chain" data-testid="run-chain">
              {v.chain.map((c, i) => (
                <div key={c.key} className={`u-cst ${c.state}`}>
                  <div className="h">{c.state === "done" ? "✓ " : ""}{i + 1} · {c.label}</div>
                  <div className="v u-small" style={{ fontWeight: 600, lineHeight: 1.35 }}>{c.text || <span className="u-muted">—</span>}</div>
                  <div className="s">{{ run: "Running", done: "Completed", waiting: "Waiting for you", pending: "Pending" }[c.state]}</div>
                </div>
              ))}
            </div>
            <div className="u-progress" role="progressbar" aria-label="Run progress" aria-valuenow={v.progress} aria-valuemax={100}>
              <span style={{ width: `${v.progress}%` }} />
            </div>
          </div>
          <div className="u-split u-demo-split">
            <div className="u-pane list">
              <table className="u-table" data-testid="run-leads">
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
              <div className="u-log" data-testid="run-log">
                {run?.events.length ? run.events.map((e, i) => (
                  <div key={run.events.length - i} className={`u-ev ${e.tone}`}><span className="t">{e.t}</span>{e.text}</div>
                )) : <div className="u-muted">No activity yet.</div>}
              </div>
            </div>
          </div>
          {v.result ? (
            <div className="u-card" style={{ marginTop: 14 }} data-testid="run-result">
              <div className="u-card-head">
                <div><h2 className="u-h2">Pipeline completed in {v.result.seconds} seconds</h2><p>Started by a scheduled trigger. No manual steps.</p></div>
                <Link className="u-btn sm" href="/health">Open Health</Link>
              </div>
              <div className="u-grid4">
                <Tile label="Leads" value={v.result.leads} />
                <Tile label="Websites read" value={v.result.websites} />
                <Tile label="Emails found" value={v.result.emails} />
                <Tile label={sample ? "Queued (test)" : "Pushed to Draft"} value={v.result.sent}
                  sub={`${v.result.interested} interested repl${v.result.interested === 1 ? "y" : "ies"}`} />
              </div>
              <div className="u-small u-muted" style={{ margin: "10px 0" }}>
                {sample
                  ? `Sample leads with stand-in services: $0.00. The same run on the real services would cost about $${v.result.would_cost.toFixed(2)}.`
                  : `Real services this run: about $${v.result.would_cost.toFixed(2)}. The sending campaign is a Draft, so no email went out.`}
              </div>
              {v.result.summary ? <SummaryMail s={v.result.summary} /> : null}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function Trigger({ v, sample }: { v: DemoStatus; sample: boolean }) {
  const r = v.run;
  const what = sample ? `${v.total} sample leads` : `${v.total} leads from ${v.name ?? "the campaign"}`;
  let icon = "clock", cls = "", title = "Ready", sub = `Select Start run. A one-time trigger is scheduled 10 seconds ahead (${what}).`;
  let extra: React.ReactNode = null;
  if (r?.state === "scheduled") {
    title = `Trigger scheduled for ${r.due}`;
    sub = `Starts automatically in ${r.seconds_left} second${r.seconds_left === 1 ? "" : "s"}.`;
    extra = <Link className="u-btn sm" href="/schedules">View in Schedules</Link>;
  } else if (r?.state === "running") {
    icon = "bolt"; cls = "ok"; title = `Trigger fired at ${r.started.slice(11, 19)}`; sub = `Pipeline running on ${what}.`;
  } else if (r?.state === "done") {
    icon = "check"; cls = "ok"; title = "Pipeline completed"; sub = `Trigger fired at ${r.started.slice(11, 19)}. Every step ran by itself.`;
  } else if (r && ["waiting", "failed", "interrupted"].includes(r.state)) {
    icon = "alert-circle"; cls = "bad"; title = "Stopped: waiting for you"; sub = r.message || "Open Health for details.";
    extra = <Link className="u-btn sm" href="/health">Open Health</Link>;
  } else if (r?.state === "stopped") {
    sub = "The last run was stopped. Select Start run to run it again.";
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
