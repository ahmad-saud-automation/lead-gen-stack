"use client";

/* Step 1, Find email (every lead, website or not): four tiles, the recipe's rungs with how many addresses each found, and
 * what is written. Only the demo can run in this version; it uses free stand-ins. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { DemoBar, NotYet, SourcePicker, useSource } from "@/components/stack/common";
import { ResetDemo } from "@/components/stack/research";
import { Card, PageHead, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { money } from "@/lib/format";
import { reloadWithNote } from "@/lib/nav";
import type { FindView, RunResult } from "@/lib/stack-types";

export function FindPage() {
  const source = useSource();
  const [v, setV] = useState<FindView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    if (!source) return;
    getJson<FindView>("/stack/find", { source })
      .then((r) => { if (r.error) throw new Error(r.error); setV(r); })
      .catch((e: Error) => setError(e.message));
  }, [source]);

  const run = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<RunResult>("/stack/find/run", { source });
      if (!r.ok) throw new Error(r.error || "Not run.");
      reloadWithNote(`Find email finished: ${r.processed} leads, ${r.found} emails found. Cost $0.00 (about ${money(r.would_cost)} on the real services).`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const n = v?.ready ?? 0;
  const label = busy ? "Finding emails…" : n ? `Find emails for ${n} lead${n === 1 ? "" : "s"}` : "All leads done";
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {v?.demo ? <DemoBar /> : null}
      <PageHead title="Find email" sub="Step 1. Searches every lead. Tries each rung in order and stops at the first verified address. A lead with no website is searched by company name."
        actions={<>
          <SourcePicker path="/find" source={source || "demo"} />
          <button type="button" className="u-btn primary" disabled={!v || !v.runnable || !n || busy} onClick={run}>{label}</button>
        </>} />
      {v && !v.runnable ? <NotYet why={v.why} /> : null}
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Find email did not run" detail={problem} /></div> : null}
      {error ? <ErrorBox title="Find email could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={6} /></div> : (
        <div className="u-stack">
          <div className="u-grid4" data-testid="find-tiles">
            <Tile label="Leads processed" value={v.processed} sub={v.no_website ? `${v.no_website} skipped: no website` : n ? `${n} waiting` : "None skipped"} />
            <Tile label="Emails found" value={v.found} sub={`${v.from_sheet} from sheet · ${v.found_new} found · ${v.company_address} company`} />
            <Tile label="Not found" value={v.not_found} sub={v.not_found ? "All rungs tried" : "—"} />
            <Tile label="Cost" value={money(v.demo ? 0 : v.would_cost)}
              sub={v.demo ? `Stand-ins are free. About ${money(v.would_cost)} on the real services.` : "Verification and finder"} />
          </div>
          <Card title={`Recipe: ${v.recipe.name || "none chosen"}`} sub="Free methods run first. Paid methods run only when needed."
            right={<div className="u-row">{v.demo && v.processed ? <ResetDemo /> : null}{v.recipe.id && !v.demo ? <Link className="u-btn sm" href={`/recipes/${encodeURIComponent(v.recipe.id)}`}>Edit recipe</Link> : null}</div>}>
            {v.rungs.length ? v.rungs.map((r) => (
              <div className="u-srung" key={r.n} data-testid="rung">
                <span className="u-num">{r.n}</span>
                <div><b className="u-ink">{r.name}</b><div className="u-small u-muted">{r.hint}</div></div>
                <span className={r.found ? "u-pill good" : "u-pill"}>{r.found ? `${r.found} found` : v.processed ? "0 used" : "Not run yet"}</span>
              </div>
            )) : <div className="u-pempty">This campaign has no finding recipe. It uses the older fixed order of methods.</div>}
          </Card>
          <div className="u-note">
            Writes <span className="u-mono">email_status</span> and the address{v.demo ? " (kept in the app for the demo and for files)" : " to the sheet"}.
            Values: {v.values.map((x) => x.label.toLowerCase()).join(", ")}.
          </div>
        </div>
      )}
    </div>
  );
}
