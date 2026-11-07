"use client";

/* Step 6, Replies: master-detail like Leads. The list scrolls on the left, the selected reply
 * stays in view on the right. "Check now" collects new replies; a person can change the
 * category (which rewrites reply_status) or mark a reply as handled. */

import { useEffect, useRef, useState } from "react";

import { DemoBar, SourcePicker, StepValue, useSource } from "@/components/stack/common";
import { PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { flashNote, reloadWithNote } from "@/lib/nav";
import type { RepliesView, Reply } from "@/lib/stack-types";

export function RepliesPage() {
  const source = useSource();
  const [v, setV] = useState<RepliesView | null>(null);
  const [error, setError] = useState("");
  const [sel, setSel] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const load = () =>
    getJson<RepliesView>("/stack/replies", { source })
      .then((r) => {
        if (r.error) throw new Error(r.error);
        setV(r);
        // ?open=<id> (Home's "Open reply") selects that reply on the first load
        const asked = Number(new URLSearchParams(window.location.search).get("open") || 0);
        setSel((s) => (r.replies.some((x) => x.id === s) ? s
          : r.replies.some((x) => x.id === asked) ? asked : r.replies[0]?.id ?? 0));
      })
      .catch((e: Error) => setError(e.message));
  useEffect(() => { if (source) load(); }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  const check = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string; new?: number }>("/stack/replies/check", { source });
      if (!r.ok) throw new Error(r.error || "Not checked.");
      reloadWithNote(r.new ? `${r.new} new repl${r.new === 1 ? "y" : "ies"} collected and classified.` : "No new replies.");
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  const update = async (id: number, body: Record<string, unknown>, note: string) => {
    setProblem("");
    const r = await postJson<{ ok: boolean; error?: string }>("/stack/replies/update", { source, id, ...body });
    if (!r.ok) return setProblem(r.error || "Not saved.");
    flashNote(note);
    load();
  };

  const shown = v?.replies.find((r) => r.id === sel) ?? v?.replies[0];
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {source === "demo" ? <DemoBar /> : null}
      <PageHead title="Replies" sub="Step 6. New replies are collected every 30 minutes and classified. Select a reply to open it."
        actions={<>
          <SourcePicker path="/replies" source={source || "demo"} />
          <button type="button" className="u-btn" disabled={busy || !source} onClick={check}>{busy ? "Checking…" : "Check now"}</button>
        </>} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not done" detail={problem} /></div> : null}
      {error ? <ErrorBox title="Replies could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <div className="u-stack">
          {!v.replies.length ? (
            <div className="u-card"><div className="u-pempty">
              {v.pushed ? "No replies yet. Select Check now to collect them." : "No lead has been sent yet. Replies appear here after Sending."}</div></div>
          ) : (
            <div className="u-split">
              <div className="u-pane list" data-testid="reply-list">
                <table className="u-table">
                  <thead><tr><th>From</th><th>Message</th><th>Category</th></tr></thead>
                  <tbody>
                    {v.replies.map((q) => (
                      <tr key={q.id} className={q.id === shown?.id ? "click sel" : "click"} tabIndex={0} aria-selected={q.id === shown?.id}
                        onClick={() => setSel(q.id)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(q.id))}>
                        <td><b className="u-ink">{q.sender}</b><div className="u-small u-muted">{q.company}</div></td>
                        <td className="u-small">{q.message.length > 52 ? `${q.message.slice(0, 52)}…` : q.message}<div className="u-muted">{q.received}</div></td>
                        <td><StepValue p={q.category} />{q.handled ? <div className="u-small u-muted">Handled</div> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {shown ? <ReplyPane q={shown} v={v} update={update} /> : null}
            </div>
          )}
          <div className="u-card">
            <h2 className="u-h2">How replies are handled</h2>
            <div className="u-steps">
              <div className="u-stp"><b>1. Collect</b>New replies from the sending platform, every 30 minutes.</div>
              <div className="u-stp"><b>2. Classify</b>Interested, not interested, out of office, wrong person or unsubscribe.</div>
              <div className="u-stp"><b>3. Record</b><span className="u-mono">reply_status</span> is written to the sheet, so the lead is not contacted again by mistake.</div>
              <div className="u-stp"><b>4. Notify</b>Interested replies appear on Home under Needs your decision.</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ReplyPane({ q, v, update }: { q: Reply; v: RepliesView; update: (id: number, b: Record<string, unknown>, note: string) => void }) {
  const pane = useRef<HTMLDivElement>(null);
  const [changing, setChanging] = useState(false);
  useEffect(() => {
    if (pane.current) pane.current.scrollTop = 0;
    setChanging(false);
  }, [q.id]);
  return (
    <div className="u-pane detail" ref={pane} data-testid="reply-detail" aria-live="polite">
      <div className="u-small u-muted">{q.campaign} · {q.received}</div>
      <h2 className="u-h2" style={{ margin: "2px 0 12px" }}>{q.sender} · {q.company}</h2>
      <div className="u-mail">{q.message}</div>
      <div className="u-rkv" style={{ marginTop: 14 }}>
        <span>Category</span><span><StepValue p={q.category} />{q.changed ? <span className="u-small u-muted"> (changed by hand)</span> : null}</span>
        <span>Recommended action</span><span>{q.action}</span>
        <span>Sheet update</span><span className="u-mono">reply_status = {q.category.value}</span>
      </div>
      {changing ? (
        <div className="u-row" style={{ marginTop: 14 }}>
          <select className="u-input u-sel" aria-label="New category" defaultValue={q.category.value}
            onChange={(e) => update(q.id, { category: e.target.value }, "Category changed. reply_status updated.")}>
            {v.categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <button type="button" className="u-btn sm" onClick={() => setChanging(false)}>Cancel</button>
        </div>
      ) : (
        <div className="u-row" style={{ marginTop: 14 }}>
          <button type="button" className="u-btn sm" onClick={() => setChanging(true)}>Change category</button>
          <button type="button" className={q.handled ? "u-btn sm" : "u-btn sm primary"}
            onClick={() => update(q.id, { handled: !q.handled }, q.handled ? "Marked as not handled." : "Marked as handled.")}>
            {q.handled ? "Mark as not handled" : "Mark as handled"}</button>
        </div>
      )}
      {v.demo ? <div className="u-small u-muted" style={{ marginTop: 10 }}>In the demo, replies come from a stand-in inbox. A live campaign also offers Open conversation.</div> : null}
    </div>
  );
}
