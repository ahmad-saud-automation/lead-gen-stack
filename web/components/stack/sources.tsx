"use client";

/* Lead sources: Google Sheets and files the app reads leads from. Connect Google Sheet only
 * CHECKS a sheet (access, tabs, which pipeline columns are missing): it saves nothing and
 * never adds a column. Link local file checks a CSV, then saves it as a source. */

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { UploadBox } from "@/components/leads/list";
import { onlyReal } from "@/components/stack/common";
import { Card, PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { reloadWithNote } from "@/lib/nav";
import type { LocalCheck, SheetCheck, SourcesView } from "@/lib/stack-types";

const ICON: Record<string, IconName> = { demo: "folder", upload: "upload", local: "folder", sheet: "file-spreadsheet",
  pipeline: "file-spreadsheet" };

function ConnectSheet() {
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<SheetCheck | null>(null);
  const check = async () => {
    setBusy(true);
    try {
      setR(await postJson<SheetCheck>("/stack/sheet/check", { link }));
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
    setBusy(false);
  };
  return (
    <Card title="Connect Google Sheet" sub="Paste the sheet link. The app checks access and lists the tabs.">
      <div className="u-row">
        <input className="u-input" type="text" aria-label="Google Sheet link" placeholder="https://docs.google.com/spreadsheets/d/…"
          value={link} onChange={(e) => setLink(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button type="button" className="u-btn primary" disabled={!link.trim() || busy} onClick={check}>{busy ? "Checking…" : "Connect"}</button>
      </div>
      {r && !r.ok ? <div className="u-note warn" style={{ marginTop: 12 }}>{r.error}</div> : null}
      {r?.ok ? (
        <>
          <div className="u-note good" style={{ marginTop: 12 }}>Connected: <b>{r.title}</b> · {r.tab_count} tab{r.tab_count === 1 ? "" : "s"} · the app can read it</div>
          {(r.tabs ?? []).map((t) => (
            <div className="u-note" style={{ marginTop: 8 }} key={t.tab}>
              <b>{t.tab}</b>: columns matched: {t.matched.join(", ") || "none"} ({t.matched.length} of {t.of}).
              {" "}Pipeline columns missing: {t.missing.length}.
              {" "}<button type="button" className="u-btn sm" disabled title="Adding columns to a sheet needs your OK first">Add pipeline columns</button>
            </div>
          ))}
          <div className="u-small u-muted" style={{ marginTop: 8 }}>Only checked. Nothing was saved and no column was added. Adding the pipeline columns to a live sheet needs your OK first, and comes in a later update.</div>
        </>
      ) : null}
    </Card>
  );
}

function LinkLocal() {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [r, setR] = useState<LocalCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const check = async () => {
    setBusy(true);
    try {
      const c = await postJson<LocalCheck>("/stack/local/check", { path, name });
      setR(c);
      if (c.ok && !name) setName(c.name ?? "");
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
    setBusy(false);
  };
  const save = async () => {
    setBusy(true);
    try {
      const s = await postJson<LocalCheck>("/stack/local/save", { path, name });
      if (!s.ok) throw new Error(s.error || "Not saved.");
      reloadWithNote(`${s.name} linked: ${s.rows} rows.`);
    } catch (e) {
      setR({ ok: false, error: e instanceof Error ? e.message : String(e) });
      setBusy(false);
    }
  };
  return (
    <Card title="Link local file" sub="A CSV file on this computer. It is read fresh every time a campaign runs, and never written to.">
      <div className="u-row">
        <input className="u-input" type="text" aria-label="File path" placeholder="C:\Leads\new-firms.csv" value={path}
          onChange={(e) => { setPath(e.target.value); setR(null); }} style={{ flex: 2, minWidth: 200 }} />
        <button type="button" className="u-btn" disabled={!path.trim() || busy} onClick={check}>Check file</button>
      </div>
      {r && !r.ok ? <div className="u-note warn" style={{ marginTop: 12 }}>{r.error}</div> : null}
      {r?.ok ? (
        <>
          <div className="u-note good" style={{ marginTop: 12 }}>{r.rows} rows · {r.columns} columns · columns matched: {r.basics?.matched.join(", ") || "none"} ({r.basics?.matched.length} of {r.basics?.of})</div>
          <div className="u-row" style={{ marginTop: 10 }}>
            <input className="u-input" type="text" aria-label="Name for this source" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
            <button type="button" className="u-btn primary" disabled={!name.trim() || busy} onClick={save}>Link file</button>
          </div>
          {r.clash ? <div className="u-note warn" style={{ marginTop: 8 }}>{r.clash}</div> : null}
        </>
      ) : null}
    </Card>
  );
}

export function SourcesPage() {
  const [v, setV] = useState<SourcesView | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<"" | "connect" | "upload" | "local">("");
  const [tabsOf, setTabsOf] = useState("");
  useEffect(() => {
    getJson<SourcesView>("/stack/sources").then(setV).catch((e: Error) => setError(e.message));
  }, []);
  const toggle = (k: "connect" | "upload" | "local") => setOpen(open === k ? "" : k);

  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Lead sources" sub="Google Sheets and files the app reads leads from. A campaign uses one tab from one source."
        actions={<>
          <button type="button" className="u-btn" aria-expanded={open === "upload"} onClick={() => toggle("upload")}><Icon name="upload" size={16} />Upload file</button>
          <button type="button" className="u-btn" aria-expanded={open === "local"} onClick={() => toggle("local")}><Icon name="folder" size={16} />Link local file</button>
          <button type="button" className="u-btn primary" aria-expanded={open === "connect"} onClick={() => toggle("connect")}><Icon name="plus" size={16} />Connect Google Sheet</button>
        </>} />
      <div className="u-stack">
        {open === "connect" ? <ConnectSheet /> : null}
        {open === "upload" ? <Card title="Upload file"><UploadBox /></Card> : null}
        {open === "local" ? <LinkLocal /> : null}
        {error ? <ErrorBox title="Lead sources could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={5} /></div> : (
          <div className="u-list" data-testid="source-list">
            {onlyReal(v.sources, (s) => s.kind === "demo").map((s) => (
              <Fragment key={s.id}>
                <div className="u-li u-src2-li">
                  <div className="u-ico"><Icon name={ICON[s.kind] ?? "folder"} size={19} /></div>
                  <div className="t"><b>{s.name}</b><div>{s.sub}</div>{s.detail ? <div>{s.detail}</div> : null}</div>
                  <div className="u-small u-hide-t">{s.campaigns ? `${s.campaigns} campaign${s.campaigns === 1 ? "" : "s"}` : <span className="u-muted">Not in use</span>}</div>
                  <div className="u-hide-t"><span className={s.access.tone ? `u-pill ${s.access.tone}` : "u-pill"}>{s.access.label}</span></div>
                  {s.tabs ? (
                    <button type="button" className="u-btn sm" aria-expanded={tabsOf === s.id} onClick={() => setTabsOf(tabsOf === s.id ? "" : s.id)}>Tabs</button>
                  ) : <Link className="u-btn sm" href={s.href}>{s.action}</Link>}
                </div>
                {s.tabs && tabsOf === s.id ? (
                  <div className="u-subtabs">
                    {s.tabs.length ? s.tabs.map((t) => (
                      <Link key={t.tab} className="u-btn sm" href={`/sources/${encodeURIComponent(t.tab)}`}>{t.tab.trim() || t.tab}{t.campaigns ? ` · ${t.campaigns}` : ""}</Link>
                    )) : <span className="u-small u-muted">No tabs listed.</span>}
                  </div>
                ) : null}
              </Fragment>
            ))}
          </div>
        )}
        {v?.hidden !== undefined ? (
          <div className="u-note" data-testid="sources-hidden">Privacy is on: client lead sources are hidden.</div>
        ) : null}
        <Card title="How lead sources work">
          <div className="u-steps">
            <div className="u-stp"><b>1. Add a source</b>Google Sheet link, uploaded CSV file, or a CSV file on this computer.</div>
            <div className="u-stp"><b>2. Choose a tab</b>In a campaign, under Leads → Lead source.</div>
            <div className="u-stp"><b>3. Match columns</b>Company, website and contact columns are matched automatically. Missing columns are listed.</div>
            <div className="u-stp"><b>4. Write results</b>Google Sheets: results go into the pipeline columns only. Files: results stay in the app and can be exported.</div>
          </div>
          <div className="u-note" style={{ marginTop: 12 }}>Pipeline columns: <span className="u-mono">{(v?.columns ?? []).join(" · ")}</span>. They are added only after you confirm. Other columns are never changed.</div>
        </Card>
      </div>
    </div>
  );
}
