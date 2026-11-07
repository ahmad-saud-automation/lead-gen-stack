"use client";

/* One run or one send. Live progress while it works (only new events are fetched each tick),
 * then three tabs: the leads and what happened to each, Send to Instantly (the exact data,
 * reviewed before anything leaves), and every step. */

import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";

import { Confirm } from "@/components/modal";
import { Card, Note, PageHead, Pill, Progress, Seg, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { money, num } from "@/lib/format";
import { flashNote, goWithNote } from "@/lib/nav";
import { runHref } from "@/lib/status";
import type { PushPreview, RunEvent, RunResult, RunSnapshot, RunStarted } from "@/lib/types";
import { resultWord, sourceWord, whenWords } from "@/lib/words";

const FEED_CAP = 3000;
const STAGE: Record<string, string> = {
  organize: "Getting the leads ready", gateway: "Checking email filters", endole: "Trying the email already in the sheet",
  pattern: "Guessing addresses", verify: "Checking addresses", icypeas: "Asking Icypeas", anymail: "Asking Anymailfinder",
  icebreaker: "Adding ice breakers", push: "Sending to Instantly", sheet: "Updating the sheet", result: "Saving the result", done: "Finished",
};
const DIRECTORS = ["Oldest Director Name", "Youngest Director Name", "Director 1 Name", "Director 2 Name", "Director 3 Name"];
type Tab = "leads" | "send" | "log";

function duration(a?: string, b?: string | null): string {
  if (!a || !b) return "";
  const s = Math.max(0, Math.round((new Date(b.replace(" ", "T")).getTime() - new Date(a.replace(" ", "T")).getTime()) / 1000));
  return s < 90 ? `${s} seconds` : `${Math.round(s / 60)} minutes`;
}

function LeadsTable({ rows, simulated }: { rows: RunResult[]; simulated?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!rows.length) return <p className="u-muted">No leads yet.</p>;
  return (
    <div className="u-scroll">
      <table className="u-table">
        <thead><tr><th>Company</th><th>Person</th><th>Email</th><th>Where it came from</th><th>Result</th></tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const w = r.pushed ? resultWord("pushed") : resultWord(r.status ?? "");
            const directors = [...new Set(DIRECTORS.map((k) => r[k]).filter((v): v is string => typeof v === "string" && !!v))];
            return (
              <Fragment key={i}>
                <tr onClick={() => setOpen(open === i ? null : i)} style={{ cursor: "pointer" }} aria-expanded={open === i}>
                  <td><b className="u-ink">{r.company || "—"}</b></td>
                  <td>{r.selected_director || "—"}</td>
                  <td className="u-mono">{r.found_email || "—"}</td>
                  <td className="u-small">{sourceWord(r.email_source) || "—"}</td>
                  <td><Pill tone={w.tone}>{w.text}</Pill></td>
                </tr>
                {open === i ? (
                  <tr>
                    <td colSpan={5} style={{ background: "var(--white)" }}>
                      <div className="u-kv" style={{ fontSize: 13 }}>
                        <span>check result</span><span>{r.verification || "—"}</span>
                        <span>directors</span><span>{directors.join(" · ") || "—"}</span>
                        <span>email filter</span><span>{r.gateway_provider || "none"}</span>
                        <span>addresses tried</span>
                        <span>{r.tries?.length ? r.tries.map((t, k) => <div key={k}>{t.accepted ? "✓" : "·"} <span className="u-mono">{t.email}</span> → {t.verification || "—"}</div>) : "none guessed"}</span>
                        <span>ice breaker</span><span>{r.icebreaker || "—"}</span>
                      </div>
                      {simulated ? <p className="u-small u-muted">Free test: this address was made up from a name pattern and never checked. Never email it.</p> : null}
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <p className="u-small u-muted" style={{ marginTop: 8 }}>Click a lead to see what was tried.</p>
    </div>
  );
}

export function RunPage({ id, initialTab }: { id: string; initialTab?: string }) {
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>((["leads", "send", "log"] as Tab[]).includes(initialTab as Tab) ? (initialTab as Tab) : "leads");
  const [filter, setFilter] = useState<"all" | "fail" | "success">("all");
  const [preview, setPreview] = useState<PushPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [confirmSend, setConfirmSend] = useState(false);
  const [busy, setBusy] = useState(false);
  const since = useRef(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    since.current = 0;
    setEvents([]);
    const tick = async () => {
      try {
        const r = await getJson<RunSnapshot>("/run/status", { run_id: id, since: String(since.current) });
        if (!alive) return;
        setRun(r);
        setError("");
        const fresh = r.events ?? [];
        if (fresh.length) {
          since.current = Math.max(since.current, ...fresh.map((e) => e.seq)) + 1;
          setEvents((x) => [...x, ...fresh].slice(-FEED_CAP));
        }
        if (r.status === "running") timer = setTimeout(tick, 900);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        timer = setTimeout(tick, 4000);          // the engine may be restarting
      }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  const finishedRun = run?.status === "finished" && run.kind !== "push";
  useEffect(() => {
    if (tab !== "send" || !finishedRun || preview) return;
    getJson<PushPreview>("/push/preview", { run_id: id }).then(setPreview).catch((e: Error) => setPreviewError(e.message));
  }, [tab, finishedRun, id, preview]);

  if (!run) return <div className="u-page">{error ? <ErrorBox title="This run could not be loaded" detail={error} /> : <div className="u-card"><Loading rows={6} /></div>}</div>;
  if (run.status === "none" || !run.run_id) {
    return <div className="u-page"><PageHead title="Run not found" back={{ href: "/activity", label: "Activity" }} sub="It may be older than the 300 runs the app keeps." /></div>;
  }

  const c = run.counters ?? {};
  const live = run.status === "running";
  const isPush = run.kind === "push";
  const who = run.campaign_name || run.campaign || "";   // older runs did not record it
  const title = isPush
    ? (run.test_mode ? "Dry run of a send" : "Sent to Instantly")
    : who ? `${who} — ${run.test_mode ? "free test" : "live run"}` : (run.test_mode ? "Free test" : "Live run");
  const sub = live
    ? `${STAGE[run.stage ?? ""] ?? "Working"} · started ${whenWords(run.started ?? "")}`
    : `${whenWords(run.started ?? "")}${run.finished ? ` · took ${duration(run.started, run.finished)}` : ""}${run.status === "cancelled" ? " · stopped" : ""}${run.test_mode ? " · nothing was spent or sent" : ""}`;
  const shown = events.filter((e) => filter === "all" || e.status === filter);

  const stop = async () => {
    setBusy(true);
    try {
      const r = await postJson<{ ok: boolean }>("/run/cancel", { run_id: id });
      flashNote(r.ok ? "Stopping after the current lead…" : { text: "It has probably just finished.", tone: "warn" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };
  const send = async (test: boolean) => {
    setConfirmSend(false);
    setBusy(true);
    setPreviewError("");
    try {
      const r = await postJson<RunStarted>("/push/start", { run_id: id, test_mode: test, confirm: true });
      if (r.error || !r.run_id) throw new Error(r.error || "The send did not start.");
      goWithNote(runHref(r.run_id), test ? "Dry run started — nothing is being sent." : "Sending to Instantly…");
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="u-page">
      <PageHead back={{ href: "/activity", label: "Activity" }} title={title} sub={sub}
        actions={<>
          {live ? <button type="button" className="u-btn danger" onClick={stop} disabled={busy}>Stop</button> : null}
          {run.campaign ? <Link className="u-btn" href={`/campaigns/${encodeURIComponent(run.campaign)}`}>Open the campaign</Link> : null}
          {isPush && run.source_run ? <Link className="u-btn" href={runHref(run.source_run)}>The run it came from</Link> : null}
        </>} />
      {error ? <div style={{ marginBottom: 12 }}><ErrorBox soft title="Lost contact with the engine — retrying" detail={error} /></div> : null}
      {live ? (
        <div className="u-card" style={{ marginBottom: 14 }}>
          <b className="u-ink">{num(run.processed)} of {num(run.total)} leads done</b>
          <Progress done={run.processed ?? 0} total={run.total ?? 0} />
        </div>
      ) : null}
      {run.test_mode && !isPush ? <div style={{ marginBottom: 14 }}><Note tone="warn">Free test: the addresses below were made up from name patterns and never checked. Never email them.</Note></div> : null}

      <div className="u-grid4">
        {isPush ? (
          <>
            <Tile label={run.test_mode ? "Would be added" : "Added to Instantly"} value={num(c.pushed)} />
            <Tile label="Skipped by Instantly" value={num(c.push_skipped)} sub="already there, or on a do-not-contact list" />
            <Tile label="Failed" value={num(c.push_failed)} sub={c.push_failed ? "see Step by step" : undefined} />
            <Tile label="Mode" value={run.test_mode ? "Dry run" : "Live"} sub={run.test_mode ? "nothing was sent" : undefined} />
          </>
        ) : (
          <>
            <Tile label="Leads worked on" value={`${num(run.processed)}${live ? ` / ${num(run.total)}` : ""}`} />
            <Tile label="Emails found" value={num(c.found)} sub={c.held ? `${num(c.held)} held (strict email filter)` : undefined} />
            <Tile label="No email found" value={num((c.not_found ?? 0) + (c.no_website ?? 0))} sub={c.no_website ? `${num(c.no_website)} had no website` : undefined} />
            <Tile label="Cost" value={money(run.test_mode ? 0 : run.credits?.total_usd)} sub={run.test_mode ? "free test" : `${num(run.credits?.total_credits)} credits`} />
          </>
        )}
      </div>

      <div style={{ marginTop: 14 }}><Card>
        <div className="u-tabs" role="tablist">
          <button type="button" className={tab === "leads" ? "on" : undefined} onClick={() => setTab("leads")}>Leads ({num(run.results?.length ?? 0)})</button>
          {!isPush ? <button type="button" className={tab === "send" ? "on" : undefined} onClick={() => setTab("send")}>Send to Instantly</button> : null}
          <button type="button" className={tab === "log" ? "on" : undefined} onClick={() => setTab("log")}>Step by step</button>
        </div>

        {tab === "leads" ? (
          <>
            <LeadsTable rows={run.results ?? []} simulated={run.test_mode} />
            <p className="u-small" style={{ marginTop: 6 }}><a className="u-link" href={`/api/results/download?run_id=${id}`}>Download the leads as CSV</a></p>
          </>
        ) : null}

        {tab === "send" ? (
          !finishedRun ? <p className="u-muted">{live ? "Wait for the run to finish." : "This run did not finish, so nothing can be sent from it."}</p>
            : !preview ? (previewError ? <ErrorBox title="Could not prepare the send" detail={previewError} /> : <Loading rows={4} />)
            : (
              <div className="u-stack">
                <Note tone={preview.ready ? "good" : undefined}>
                  <b>{num(preview.ready)}</b> lead{preview.ready === 1 ? " is" : "s are"} ready to send{preview.campaign_name ? ` from ${preview.campaign_name}` : ""}.
                  {preview.already_sent ? <> {num(preview.already_sent)} {preview.already_sent === 1 ? "is" : "are"} already in Instantly, so {preview.already_sent === 1 ? "it is" : "they are"} not sent again.</> : null}
                  {preview.held_not_send_ready ? <> {num(preview.held_not_send_ready)} found an address that did not pass the check, so they stay back.</> : null}
                  {preview.waiting_icebreaker ? <> {num(preview.waiting_icebreaker)} are waiting for an ice breaker from Icebreaker Studio{preview.waiting_companies?.length ? ` (${preview.waiting_companies.slice(0, 5).join(", ")}${preview.waiting_companies.length > 5 ? "…" : ""})` : ""}.</> : null}
                </Note>
                {preview.icebreaker_note ? <Note tone="warn">{preview.icebreaker_note}</Note> : null}
                {preview.from_test ? <Note tone="warn">This was a free test, so these addresses were made up. You can do a dry run to see what would be sent, but to really send, run the campaign live first.</Note> : null}
                {!preview.has_key ? <Note tone="bad">No Instantly key yet — add it in <Link className="u-link" href="/settings">Settings</Link>.</Note> : null}
                {!preview.campaign_id ? <Note tone="bad">The campaign has no Instantly campaign chosen.</Note> : null}
                {(preview.leads ?? []).length ? (
                  <div>
                    <b className="u-ink">What Instantly gets</b> <span className="u-small u-muted">(first {Math.min(25, preview.leads?.length ?? 0)})</span>
                    {(preview.leads ?? []).slice(0, 25).map((l, i) => (
                      <details key={i} className="u-adv small" style={{ marginTop: 6 }}>
                        <summary>{String(l.company_name ?? "")} <span className="u-muted u-small">· {String(l.email ?? "")}</span></summary>
                        <div className="u-kv">
                          {Object.entries(l).flatMap(([k, v]) => (k === "custom_variables" && v && typeof v === "object"
                            ? Object.entries(v as Record<string, unknown>).map(([ck, cv]) => [`{{${ck}}}`, cv] as const)
                            : [[k, v] as const])).map(([k, v]) => [
                            <span key={`k${k}`}>{k}</span>, <span key={`v${k}`}>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</span>,
                          ])}
                        </div>
                      </details>
                    ))}
                  </div>
                ) : null}
                {previewError ? <ErrorBox title="Not sent" detail={previewError} /> : null}
                <div className="u-row">
                  <button type="button" className="u-btn" onClick={() => send(true)} disabled={busy || !preview.ready}>Dry run (sends nothing)</button>
                  <button type="button" className="u-btn primary" onClick={() => setConfirmSend(true)}
                    disabled={busy || !preview.ready || !preview.has_key || !preview.campaign_id || !!preview.from_test}
                    title={preview.from_test ? "A free test's addresses cannot be sent" : undefined}>
                    Send {num(preview.ready)} lead{preview.ready === 1 ? "" : "s"} to Instantly
                  </button>
                  {preview.delay ? <span className="u-small u-muted">One every {preview.delay} seconds.</span> : null}
                </div>
                {run.campaign && !run.test_mode ? (
                  <p className="u-small u-muted">This sends only this run. To send everything the campaign found that is still waiting, use{" "}
                    <Link className="u-link" href={`/campaigns/${encodeURIComponent(run.campaign)}/send`}>Send all waiting leads</Link>.</p>
                ) : null}
              </div>
            )
        ) : null}

        {tab === "log" ? (
          <>
            <div className="u-row" style={{ marginBottom: 10 }}>
              <Seg label="Show" value={filter} onChange={setFilter} options={[{ value: "all", label: "Everything" }, { value: "fail", label: "Problems" }, { value: "success", label: "Successes" }]} />
              <a className="u-link u-small" href={`/api/log/download?run_id=${id}`}>Download as CSV</a>
            </div>
            {shown.length === 0 ? <p className="u-muted">{events.length ? "Nothing of this kind." : "No steps recorded yet."}</p> : (
              <div className="u-list" style={{ maxHeight: 520, overflowY: "auto" }}>
                {shown.slice(-500).map((e) => (
                  <div key={e.seq} className="u-li" style={{ gridTemplateColumns: "28px minmax(0,1fr)", padding: "10px 14px" }}>
                    <span className={e.status === "fail" ? "u-dot bad" : e.status === "success" ? "u-dot ok" : "u-dot n"}>{e.status === "fail" ? "!" : e.status === "success" ? "✓" : "–"}</span>
                    <div className="t"><b>{e.company || STAGE[e.stage ?? ""] || e.stage}</b><div>{(e.ts ?? "").slice(11, 19)} · {STAGE[e.stage ?? ""] ?? e.stage} · {e.detail}</div></div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : null}
      </Card></div>

      {confirmSend && preview ? (
        <Confirm title="Send these leads to Instantly?" danger confirmLabel={`Yes, send ${num(preview.ready)}`} onConfirm={() => send(false)} onClose={() => setConfirmSend(false)}
          body={<>
            <p>This <b>leaves your computer</b>: {num(preview.ready)} lead{preview.ready === 1 ? "" : "s"} will be added to {preview.campaign_name ? <b>{preview.campaign_name}</b> : "the campaign"} in Instantly.</p>
            <p className="muted">Your Google Sheet is updated row by row as each one goes.</p>
          </>} />
      ) : null}
    </div>
  );
}
