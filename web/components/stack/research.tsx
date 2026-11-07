"use client";

/* Step 2, Website research (only leads Find email found an address for): how it works, the results table, the facts for the company
 * picked in it, and where the data is kept. Only the demo can run in this version. */

import { useEffect, useState } from "react";

import { DemoBar, NotYet, SourcePicker, StepValue, useSource } from "@/components/stack/common";
import { Card, PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { reloadWithNote } from "@/lib/nav";
import type { ResearchView, RunResult } from "@/lib/stack-types";

export function ResetDemo() {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="u-btn sm" disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await postJson("/stack/demo/reset");
          reloadWithNote("The demo was cleared. Every demo lead is back to not researched.");
        } catch {
          setBusy(false);
        }
      }}>{busy ? "Clearing…" : "Start the demo again"}</button>
  );
}

export function ResearchPage() {
  const source = useSource();
  const [v, setV] = useState<ResearchView | null>(null);
  const [sel, setSel] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    if (!source) return;
    getJson<ResearchView>("/stack/research", { source })
      .then((r) => { if (r.error) throw new Error(r.error); setV(r); setSel(r.rows[0]?.key ?? ""); })
      .catch((e: Error) => setError(e.message));
  }, [source]);

  const run = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<RunResult>("/stack/research/run", { source });
      if (!r.ok) throw new Error(r.error || "Not run.");
      reloadWithNote(`Website research finished: ${r.processed} companies read, ${r.found} websites found. Cost $0.00.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const n = v?.to_research ?? 0;
  const one = v?.rows.find((r) => r.key === sel);
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {v?.demo ? <DemoBar /> : null}
      <PageHead title="Website research" sub="Step 2. Reads the website of each lead that has an email address and stores the facts used for ice breakers."
        actions={<>
          <SourcePicker path="/research" source={source || "demo"} />
          <button type="button" className="u-btn primary" disabled={!v || !v.runnable || !n || busy} onClick={run}>
            {busy ? "Researching…" : n ? `Research ${n} new lead${n === 1 ? "" : "s"}` : "No lead with an email is waiting"}
          </button>
        </>} />
      {v && !v.runnable ? <NotYet why={v.why} /> : null}
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Website research did not run" detail={problem} /></div> : null}
      <div className="u-stack">
        <Card title="How it works">
          <div className="u-steps">
            <div className="u-stp"><b>1. Check the domain</b>Unreachable domains are marked and skipped.</div>
            <div className="u-stp"><b>2. Read key pages</b>Home, About, Services, Careers and News, up to 5 pages.</div>
            <div className="u-stp"><b>3. Extract facts</b>Open roles, awards, sectors served, software partnerships, case studies.</div>
            <div className="u-stp"><b>4. Store</b>Facts are saved in the app. The sheet receives <span className="u-mono">website_status</span> only.</div>
          </div>
        </Card>
        <Card title="Results" sub="Select a company to see the extracted facts." right={v?.demo && v.rows.length ? <ResetDemo /> : undefined}>
          {error ? <ErrorBox title="Results could not be loaded" detail={error} /> : !v ? <Loading rows={5} /> : !v.rows.length ? (
            <div className="u-pempty">No company has been researched yet.{v.runnable ? ` Select "Research ${n} new leads" to start.` : ""}</div>
          ) : (
            <>
              <div className="u-scroll">
                <table className="u-table" data-testid="research-table">
                  <thead><tr><th>Company</th><th>Website</th><th>Result</th><th>Facts</th><th>Checked</th></tr></thead>
                  <tbody>
                    {v.rows.map((r) => (
                      <tr key={r.key} className={r.key === sel ? "click sel" : "click"} tabIndex={0} aria-selected={r.key === sel}
                        onClick={() => setSel(r.key)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(r.key))}>
                        <td><b className="u-ink">{r.company}</b></td>
                        <td className="u-mono">{r.host || "—"}</td>
                        <td><StepValue p={r.status} /></td>
                        <td>{r.chips.length ? r.chips.map((c) => <span key={c} className="u-fchip">{c}</span>) : <span className="u-muted">—</span>}</td>
                        <td className="u-small u-muted">{r.checked}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {one ? (
                <div className="u-ev" style={{ marginTop: 12 }} data-testid="research-facts">
                  <b className="u-ink">{one.company}:</b> {one.detail}.
                  {one.facts.length ? (
                    <ul style={{ marginTop: 6 }}>
                      {one.facts.map((f, i) => (
                        <li key={i}><b className="u-ink">{f.kind}:</b> {f.text}{f.url ? <> · <a className="u-link" href={f.url} target="_blank" rel="noreferrer">{f.url.replace(/^https?:\/\//, "")}</a></> : null}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </Card>
        <Card title="Data storage">
          <div className="u-scroll">
            <table className="u-table">
              <thead><tr><th>Data</th><th>Location</th></tr></thead>
              <tbody>
                <tr><td>Extracted facts per company</td><td>App database on this computer, one record per company</td></tr>
                <tr><td>Research result</td><td>Sheet column <span className="u-mono">website_status</span>: {(v?.values ?? []).map((x) => x.label.toLowerCase()).join(", ") || "found, not found, unreachable, blocked"}</td></tr>
                <tr><td>Refresh</td><td>Companies researched in the last 30 days are skipped</td></tr>
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
