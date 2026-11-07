"use client";

/* Leads: where leads come from — the tabs of the Google Sheet and files you upload. Each row
 * opens its own page (health, column matching, first rows). Rows and matching load one source
 * at a time after the page appears, so the page itself is instant. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Empty, Note, PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson } from "@/lib/client-api";
import { num } from "@/lib/format";
import { goWithNote } from "@/lib/nav";
import type { CampaignsView, ImportPreview, ImportRecord, ImportsView, SheetInfo } from "@/lib/types";
import { FIELD_WORDS, WRITTEN_GROUP } from "@/lib/words";

type Src = { tab: string; kind: "sheet" | "upload"; name: string; sub: string };
type Health = { rows: number; matched: number; needed: number; blocking: number } | { error: string };

export const sourceHref = (tab: string) => `/sources/${encodeURIComponent(tab)}`;

/** How many of the fields a lead source can fill are matched to a column. */
export function matchedCount(resolved: Record<string, string> | undefined): { matched: number; needed: number } {
  const readable = Object.keys(FIELD_WORDS).filter((f) => FIELD_WORDS[f].group !== WRITTEN_GROUP);
  return { matched: readable.filter((f) => resolved?.[f]).length, needed: readable.length };
}

export function UploadBox({ onDone }: { onDone?: (rec: ImportRecord) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const send = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setProblem("");
    const body = new FormData();
    body.append("file", file);
    try {
      const res = await fetch("/api/imports/upload", { method: "POST", body });
      const r = (await res.json()) as { ok?: boolean; error?: string; import?: ImportRecord };
      if (!r.ok || !r.import) throw new Error(r.error || `${res.status} ${res.statusText}`);
      if (onDone) onDone(r.import);
      else goWithNote(sourceHref(r.import.tab), `${r.import.name} uploaded: ${num(r.import.rows)} rows.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <>
      <div className={over ? "u-dropfile over" : "u-dropfile"} role="button" tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files?.[0]); }}>
        <b className="u-ink">{busy ? "Uploading…" : "Drop a CSV here, or click to choose one"}</b>
        <div className="u-small u-muted">Nothing is spent by uploading. You will see what is inside before any campaign uses it.</div>
        <input ref={input} type="file" accept=".csv,.tsv,.txt,text/csv" hidden onChange={(e) => send(e.target.files?.[0])} />
      </div>
      {problem ? <div style={{ marginTop: 10 }}><ErrorBox title="Not uploaded" detail={problem} /></div> : null}
    </>
  );
}

export function LeadsList() {
  const [sheet, setSheet] = useState<SheetInfo | null>(null);
  const [srcs, setSrcs] = useState<Src[] | null>(null);
  const [users, setUsers] = useState<Record<string, number>>({});
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [upload, setUpload] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getJson<SheetInfo>("/sheets/info"), getJson<ImportsView>("/imports"), getJson<CampaignsView>("/campaigns")])
      .then(([sh, im, cv]) => {
        setSheet(sh);
        const list: Src[] = [
          ...sh.tabs.map((t) => ({ tab: t, kind: "sheet" as const, name: t.trim(), sub: "Google Sheet tab" })),
          ...im.imports.map((i) => ({ tab: i.tab, kind: "upload" as const, name: i.name, sub: `Uploaded ${i.uploaded.slice(0, 10)} · ${num(i.rows)} rows · never written back to` })),
        ];
        setSrcs(list);
        const u: Record<string, number> = {};
        for (const c of cv.campaigns ?? []) u[c.tab] = (u[c.tab] ?? 0) + 1;
        setUsers(u);
        // one source at a time: each may read thousands of rows from Google
        (async () => {
          for (const s of list) {
            try {
              const p = await getJson<ImportPreview>("/imports/preview", { tab: s.tab });
              const m = matchedCount(p.check?.resolved);
              setHealth((h) => ({ ...h, [s.tab]: p.error ? { error: p.error } : { rows: p.stats.rows, ...m, blocking: p.check?.blocking?.length ?? 0 } }));
            } catch (e) {
              setHealth((h) => ({ ...h, [s.tab]: { error: e instanceof Error ? e.message : String(e) } }));
            }
          }
        })();
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="u-page"><ErrorBox title="Lead sources could not be loaded" detail={error} /></div>;

  return (
    <div className="u-page">
      <PageHead title="Leads" sub="Where your leads come from: the tabs of your Google Sheet, and files you upload."
        actions={<button type="button" className="u-btn primary" onClick={() => setUpload(!upload)}>+ Upload a CSV</button>} />
      {upload ? <div style={{ marginBottom: 14 }}><UploadBox /></div> : null}
      {sheet ? (
        <div style={{ marginBottom: 12 }}>
          <Note tone={sheet.ok ? "good" : "warn"}>
            {sheet.ok ? <>Google Sheet connected: {sheet.detail}</> : <>Google Sheet: {sheet.detail}. <Link className="u-link" href="/settings">Settings → Connections</Link></>}
          </Note>
        </div>
      ) : null}
      {!srcs ? (
        <div className="u-card"><Loading rows={5} /></div>
      ) : srcs.length === 0 ? (
        <Empty title="No lead sources yet">Connect your Google Sheet in Settings, or upload a CSV.</Empty>
      ) : (
        <div className="u-list">
          {srcs.map((s) => {
            const h = health[s.tab];
            const n = users[s.tab] ?? 0;
            return (
              <Link key={s.tab} className="u-li u-src-li" href={sourceHref(s.tab)}>
                <div className="t"><b>{s.name}</b><div>{s.sub}{h && "rows" in h && s.kind === "sheet" ? ` · ${num(h.rows)} rows` : ""}</div></div>
                <div className="u-small u-hide-m">{n ? `Used by ${n} campaign${n > 1 ? "s" : ""}` : <span className="u-muted">Not used yet</span>}</div>
                <div className="u-small u-hide-m">
                  {!h ? <span className="u-muted">checking…</span>
                    : "error" in h ? <span className="u-badmark">! could not read</span>
                    : h.blocking ? <span className="u-badmark">✕ needs matching</span>
                    : <><span className="u-tick">✓</span> {h.matched} of {h.needed} columns matched</>}
                </div>
                <span className="u-btn sm">Open</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
