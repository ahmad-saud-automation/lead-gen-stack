"use client";

/* Leads: every lead of one source, master-detail. The list scrolls on the left; the record
 * pane stays in view on the right and scrolls on its own. Under 900 px the record sits under
 * the list. Choosing a lead does not reload the page. */

import { useEffect, useRef, useState } from "react";

import { DemoBar, NotYet, SourcePicker, StepValue, useSource } from "@/components/stack/common";
import { PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson } from "@/lib/client-api";
import type { LeadRecord, LeadsView } from "@/lib/stack-types";

export function LeadsPage() {
  const source = useSource();
  const [view, setView] = useState<LeadsView | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [sel, setSel] = useState("");

  useEffect(() => {
    if (!source) return;
    getJson<LeadsView>("/stack/leads", { source })
      .then((v) => {
        if (v.error) throw new Error(v.error);
        setView(v);
        const want = new URLSearchParams(window.location.search).get("lead") || "";
        setSel(v.rows.some((r) => r.key === want) ? want : v.rows[0]?.key ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [source]);

  const rows = (view?.rows ?? []).filter((r) => r.filters.includes(filter)).slice(0, view?.show || undefined);
  const inFilter = view?.filters.find((f) => f.id === filter)?.count ?? 0;
  const shown = rows.some((r) => r.key === sel) ? sel : rows[0]?.key ?? "";
  const pick = (key: string) => {
    setSel(key);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("lead", key);
      window.history.replaceState(null, "", u.toString());
    } catch {
      // the address is only a convenience
    }
  };

  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {view?.demo ? <DemoBar /> : null}
      <PageHead title="Leads" sub="All leads in one source. Select a lead to see its full record."
        actions={<SourcePicker path="/leads" source={source || "demo"} />} />
      {error ? <ErrorBox title="Leads could not be loaded" detail={error} /> : !view ? <div className="u-card"><Loading rows={8} /></div> : (
        <>
          {!view.runnable ? <NotYet why={`This source is shown read-only. ${view.why}`} /> : null}
          <div className="u-chips2" role="group" aria-label="Filter leads">
            {view.filters.map((f) => (
              <button key={f.id} type="button" className={f.id === filter ? "u-btn sm primary" : "u-btn sm"}
                aria-pressed={f.id === filter} onClick={() => setFilter(f.id)}>{f.label} ({f.count})</button>
            ))}
          </div>
          {inFilter > rows.length ? <div className="u-small u-muted" style={{ marginBottom: 8 }}>Showing the first {rows.length.toLocaleString("en-GB")} of {inFilter.toLocaleString("en-GB")} leads.</div> : null}
          <div className="u-split">
            <div className="u-pane list" data-testid="lead-list">
              {rows.length ? (
                <table className="u-table">
                  <thead><tr><th>Company</th><th>Website</th><th>Email</th><th>Ice breaker</th><th>Sent</th><th>Reply</th></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className={r.key === shown ? "click sel" : "click"} tabIndex={0} aria-selected={r.key === shown}
                        onClick={() => pick(r.key)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick(r.key))}>
                        <td><b className="u-ink">{r.company}</b><div className="u-small u-muted">{r.person || "No contact"}</div></td>
                        <td><StepValue p={r.steps.website_status} /></td>
                        <td><StepValue p={r.steps.email_status} /></td>
                        <td><StepValue p={r.steps.icebreaker_status} /></td>
                        <td><StepValue p={r.steps.push_status} /></td>
                        <td><StepValue p={r.steps.reply_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="u-pempty">No leads match this filter.</div>}
            </div>
            <RecordPane source={source} leadKey={shown} />
          </div>
        </>
      )}
    </div>
  );
}

function RecordPane({ source, leadKey }: { source: string; leadKey: string }) {
  const [rec, setRec] = useState<LeadRecord | null>(null);
  const [error, setError] = useState("");
  const pane = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!leadKey) return setRec(null);
    setError("");
    getJson<{ lead: LeadRecord; error?: string }>("/stack/lead", { source, key: leadKey })
      .then((r) => {
        if (r.error || r.lead?.error) throw new Error(r.error || r.lead.error);
        setRec(r.lead);
        if (pane.current) pane.current.scrollTop = 0;
      })
      .catch((e: Error) => setError(e.message));
  }, [source, leadKey]);

  return (
    <div className="u-pane detail" ref={pane} data-testid="lead-detail" aria-live="polite">
      {!leadKey ? <div className="u-pempty">No leads match this filter.</div>
        : error ? <ErrorBox title="This lead could not be loaded" detail={error} />
        : !rec ? <Loading rows={6} /> : (
          <>
            <div className="u-small u-muted">Lead record</div>
            <h2 className="u-h2" style={{ margin: "2px 0" }}>{rec.company}</h2>
            <div className="u-muted u-small" style={{ marginBottom: 14 }}>{[rec.person, rec.title].filter(Boolean).join(", ") || "No contact named"}</div>
            <div className="u-rkv" style={{ marginBottom: 14 }}>
              <span>Email</span><span>{rec.email || "—"}</span>
              <span>Website</span><span>{rec.website || "—"}</span>
              <span>Next step</span><span><b className="u-ink">{rec.next}</b></span>
            </div>
            <h3 className="u-h4" style={{ marginTop: 0 }}>Pipeline status</h3>
            <div className="u-scroll">
              <table className="u-table">
                <thead><tr><th>Step</th><th>Status</th><th>Sheet column</th></tr></thead>
                <tbody>
                  {rec.steps.map((s) => (
                    <tr key={s.n}><td>{s.n} · {s.name}</td><td><StepValue p={s} /></td><td className="u-mono">{s.column}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rec.research ? (
              <>
                <h3 className="u-h4">Website facts</h3>
                {rec.research.facts.length ? (
                  <div className="u-ev"><ul>
                    {rec.research.facts.map((f, i) => (
                      <li key={i}><b className="u-ink">{f.kind}:</b> {f.text}{f.url ? <> · <a className="u-link" href={f.url} target="_blank" rel="noreferrer">source page</a></> : null}</li>
                    ))}
                  </ul></div>
                ) : <div className="u-ev">{rec.research.detail}</div>}
                {rec.research.pages.length ? <div className="u-small u-muted" style={{ marginTop: 6 }}>Pages read: {rec.research.pages.map((p) => p.kind).join(", ")}</div> : null}
              </>
            ) : null}
            {rec.find ? (
              <>
                <h3 className="u-h4">Email search</h3>
                <div className="u-ev">
                  {rec.find.email ? <>Found <b className="u-ink">{rec.find.email}</b>{rec.find.rung ? ` by ${rec.find.rung}` : ""}.</> : <>No address found.</>}
                  {" "}{rec.find.checks} check{rec.find.checks === 1 ? "" : "s"}, {rec.find.finder_calls} finder call{rec.find.finder_calls === 1 ? "" : "s"}.
                  {rec.find.steps.length ? <ul style={{ marginTop: 6 }}>{rec.find.steps.map((s, i) => <li key={i}>{s.detail}</li>)}</ul> : null}
                </div>
              </>
            ) : null}
            <h3 className="u-h4">History</h3>
            <div className="u-ev">{rec.history.length ? <ul>{rec.history.map((h, i) => <li key={i}>{h}</li>)}</ul> : "No activity yet"}</div>
          </>
        )}
    </div>
  );
}
