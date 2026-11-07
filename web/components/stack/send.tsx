"use client";

/* Step 5, Sending. TEST MODE ONLY: leads go to a test sending campaign that keeps them in a
 * list; no email leaves the computer. One table per campaign (as the sample), the leads with
 * what happens to each, and one button. */

import { useEffect, useState } from "react";

import { DemoBar, LaterTile, SourcePicker, StepValue, onlyReal, useSource } from "@/components/stack/common";
import { Card, PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { reloadWithNote } from "@/lib/nav";
import type { SendResult, SendView } from "@/lib/stack-types";

export function SendPage() {
  const source = useSource();
  const [v, setV] = useState<SendView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (!source) return;
    getJson<SendView>("/stack/send", { source }).then((r) => { if (r.error) throw new Error(r.error); setV(r); })
      .catch((e: Error) => setError(e.message));
  }, [source]);

  const send = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<SendResult>("/stack/send/run", { source });
      if (!r.ok) throw new Error(r.error || "Nothing was sent.");
      reloadWithNote(source === "demo"
        ? `Test mode: ${r.pushed} lead${r.pushed === 1 ? "" : "s"} queued in the test sending campaign, ${r.held} held. No email was sent.`
        : `${r.pushed} lead${r.pushed === 1 ? "" : "s"} added to the Draft sending campaign, ${r.held} held. A Draft campaign sends nothing.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const n = v?.can_send ?? 0;
  const label = busy ? "Queueing…" : n ? `Send ${n} queued lead${n === 1 ? "" : "s"}` : "No lead ready";
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {source === "demo" ? <DemoBar /> : null}
      <PageHead title="Sending" sub="Step 5. Queues ready leads in the sending platform. A lead is ready when it has an email, an ice breaker and an approved template."
        actions={<>
          <SourcePicker path="/send" source={source || "demo"} />
          <button type="button" className="u-btn primary" disabled={!v || !n || busy} onClick={send}>{label}</button>
        </>} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Nothing was sent" detail={problem} /></div> : null}
      {error ? <ErrorBox title="Sending could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <div className="u-stack">
          <div className="u-card">
            <div className="u-scroll">
              <table className="u-table" data-testid="send-campaigns">
                <thead><tr><th>Campaign</th><th>Sending campaign</th><th>Queued</th><th>Held</th><th>Sent today</th><th>Daily limit</th><th>Mode</th></tr></thead>
                <tbody>
                  {onlyReal(v.rows, (r) => r.source === "demo").map((r) => (
                    <tr key={r.campaign}><td><b className="u-ink">{r.campaign}</b></td><td>{r.sending_campaign}</td><td>{r.queued}</td>
                      <td>{r.held}</td><td>{r.sent_today}</td><td>{r.daily_limit}</td>
                      <td><span className="u-pill warn">{r.demo === false ? "Draft" : "Test"}</span></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="u-note" style={{ marginTop: 12 }}>
              Writes <span className="u-mono">push_status</span>: pushed, held or failed. Leads added outside the app are recorded so they are never sent twice.
              {source === "demo" ? "Test mode is on: leads are queued in a test campaign and no email is sent."
                : "Leads go to a Draft campaign. The app checks it is Draft or Paused before every push, so no email is sent."}
            </div>
          </div>
          {!v.live_templates ? <div className="u-note warn">No approved template yet. Approve one on the Email template page before sending.</div> : null}
          <Card title="Leads with an email address" sub="Held leads stay here and are checked again on the next run.">
            {v.leads.length ? (
              <div className="u-scroll">
                <table className="u-table" data-testid="send-leads">
                  <thead><tr><th>Company</th><th>Email</th><th>Status</th><th>Reason or template</th></tr></thead>
                  <tbody>
                    {v.leads.map((l) => (
                      <tr key={l.key}><td><b className="u-ink">{l.company}</b></td><td className="u-small">{l.email || "—"}</td>
                        <td><StepValue p={l.status} /></td><td className="u-small">{l.reason || l.template || "—"}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="u-pempty">No lead has an email address yet. Run Find email first.</div>}
          </Card>
          {v.later.count ? <div className="u-grid3"><LaterTile count={v.later.count} why={v.later.why} /></div> : null}
        </div>
      )}
    </div>
  );
}
