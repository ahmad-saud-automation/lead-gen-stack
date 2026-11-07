"use client";

/* Step 3, Ice breakers. /ice lists the campaigns and the rule sets; /ice?open=demo opens one
 * campaign with four tabs: Rungs (turn on/off, drag to reorder, edit, add), Template, Preview
 * and Leads. Every rung change is saved at once. Only Demo firms can run in this version. */

import Link from "next/link";
import { Fragment, useEffect, useState, type DragEvent, type KeyboardEvent } from "react";

import { DemoBar, LaterTile, onlyReal, useParam } from "@/components/stack/common";
import { ResetDemo } from "@/components/stack/research";
import { Card, PageHead, Switch } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { flashNote, reloadWithNote } from "@/lib/nav";
import type { IceCamp, IceLead, IceOverview, IcePreview, IceRung, IceRunResult, RuleSet } from "@/lib/stack-types";

export function IcePage() {
  const open = useParam("open");
  if (open === null) return <div className="u-page"><Loading rows={6} /></div>;
  return open ? <IceCampPage source={open} /> : <IceList />;
}

function IceList() {
  const [v, setV] = useState<IceOverview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getJson<IceOverview>("/stack/ice").then(setV).catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Ice breakers" sub="Step 3. Each campaign uses one rule set. Select a campaign to write, review or change its ice breakers." />
      {error ? <ErrorBox title="Ice breakers could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={5} /></div> : (
        <div className="u-stack">
          <div className="u-grid3" data-testid="ice-campaigns">
            {onlyReal(v.campaigns, (c) => c.demo).map((c) => (
              <div className="u-tile" key={c.id}>
                <div className="u-row sb"><b className="u-ink">{c.name}</b><span className="u-pill good">Live</span></div>
                <div className="u-small u-muted" style={{ margin: "4px 0 10px" }}>Rule set: {c.ruleset || "not selected"}</div>
                <div className="u-small">{c.counts.written} written · {c.counts.waiting} waiting</div>
                <Link className="u-btn sm primary" style={{ marginTop: 12 }} href={`/ice?open=${encodeURIComponent(c.id)}`}>Open</Link>
              </div>
            ))}
            <LaterTile count={v.later.count} why={v.later.why} />
          </div>
          <Card title="Rule sets" sub="A rule set holds the rungs and the template. Campaigns can share a rule set.">
            <div className="u-scroll">
              <table className="u-table">
                <thead><tr><th>Rule set</th><th>Rungs</th><th>Used by</th><th>Written</th></tr></thead>
                <tbody>
                  {v.rulesets.map((r) => (
                    <tr key={r.id}><td><b className="u-ink">{r.name}</b></td><td>{r.rungs} and a default ({r.on} on)</td>
                      <td>{r.used_by.join(", ")}</td><td>{r.written}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

const TABS = [["rungs", "Rungs"], ["tpl", "Template"], ["prev", "Preview"], ["leads", "Leads"]] as const;
type TabId = (typeof TABS)[number][0];

function IceCampPage({ source }: { source: string }) {
  const [v, setV] = useState<IceCamp | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<TabId>("rungs");
  const [sel, setSel] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");

  const load = () =>
    getJson<IceCamp>("/stack/ice/camp", { source })
      .then((r) => { if (r.error) throw new Error(r.error); setV(r); })
      .catch((e: Error) => setError(e.message));
  useEffect(() => { load(); }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (rewrite: boolean) => {
    setBusy(rewrite ? "rewrite" : "write");
    setProblem("");
    try {
      const r = await postJson<IceRunResult>("/stack/ice/run", { source, keys: rewrite ? sel : [], rewrite });
      if (!r.ok) throw new Error(r.error || "Not run.");
      const bits = [`${r.written} written`, r.default ? `${r.default} from the Default line` : "", r.skipped_sent ? `${r.skipped_sent} already sent, left as they are` : ""].filter(Boolean);
      reloadWithNote(`Ice breakers: ${bits.join(", ")}. Cost $0.00.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy("");
    }
  };

  const saveRules = async (rs: RuleSet, note: string) => {
    setProblem("");
    const r = await postJson<{ ok: boolean; error?: string }>("/stack/ice/ruleset", { source, ruleset: rs });
    if (!r.ok) {
      setProblem(r.error || "Not saved.");
      return false;
    }
    flashNote(note);
    await load();
    return true;
  };

  const waiting = v?.counts.waiting ?? 0;
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {v?.demo ? <DemoBar /> : null}
      <PageHead back={{ href: "/ice", label: "Ice breakers" }}
        title={`Ice breakers · ${v?.name ?? "…"}`}
        sub={v ? `Rule set: ${v.ruleset.name}. Leads need an email address and website facts.` : undefined}
        actions={v ? <>
          <button type="button" className="u-btn" disabled={!sel.length || !!busy} onClick={() => run(true)}>
            {busy === "rewrite" ? "Rewriting…" : sel.length ? `Rewrite ${sel.length} selected` : "Rewrite selected"}</button>
          <button type="button" className="u-btn primary" disabled={!waiting || !!busy} onClick={() => run(false)}>
            {busy === "write" ? "Writing…" : waiting ? `Write ${waiting} waiting` : "None waiting"}</button>
        </> : null} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not done" detail={problem} /></div> : null}
      {error ? <ErrorBox title="This campaign could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={8} /></div> : (
        <div className="u-card">
          <div className="u-tabs" role="tablist">
            {TABS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : undefined}
                onClick={() => setTab(id)}>{label}{id === "leads" ? ` (${v.leads.length})` : ""}</button>
            ))}
          </div>
          {tab === "rungs" ? <Rungs v={v} save={saveRules} /> : null}
          {tab === "tpl" ? <TemplateTab rs={v.ruleset} /> : null}
          {tab === "prev" ? <PreviewTab source={source} options={v.preview} /> : null}
          {tab === "leads" ? <LeadsTab leads={v.leads} sel={sel} setSel={setSel} /> : null}
          {v.demo && (v.counts.written || v.counts.no_facts) ? <div style={{ marginTop: 14 }}><ResetDemo /></div> : null}
        </div>
      )}
    </div>
  );
}

const BLANK: IceRung = { id: "", name: "", source: "", on: true, fact: "", implication: "" };

function Rungs({ v, save }: { v: IceCamp; save: (rs: RuleSet, note: string) => Promise<boolean> }) {
  // shown at once, then saved; the saved version replaces it (or puts it back if refused)
  const [local, setLocal] = useState<IceRung[]>(v.ruleset.rungs);
  useEffect(() => setLocal(v.ruleset.rungs), [v.ruleset]);
  const rs = { ...v.ruleset, rungs: local };
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<IceRung>(BLANK);
  const [drag, setDrag] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);

  const strip = (r: IceRung): IceRung => ({ id: r.id, name: r.name, source: r.source, on: r.on, fact: r.fact, implication: r.implication });
  const withRungs = (rungs: IceRung[]): RuleSet => ({ ...rs, rungs: rungs.map(strip) });

  const move = (from: number, to: number) => {
    if (to < 0 || to >= rs.rungs.length || from === to) return;
    const next = [...rs.rungs];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setLocal(next);
    save(withRungs(next), `Order saved. ${x.name} is now rung ${to + 1}.`).then((done) => { if (!done) setLocal(v.ruleset.rungs); });
  };
  const toggle = (i: number, on: boolean) => {
    const next = rs.rungs.map((r, j) => (j === i ? { ...r, on } : r));
    setLocal(next);
    save(withRungs(next), `${rs.rungs[i].name} turned ${on ? "on" : "off"}.`).then((done) => { if (!done) setLocal(v.ruleset.rungs); });
  };
  const startEdit = (i: number) => { setAdding(false); setEditing(i); setDraft(strip(rs.rungs[i])); };
  const saveEdit = async () => {
    const next = adding ? [...rs.rungs, draft] : rs.rungs.map((r, j) => (j === editing ? draft : r));
    if (await save(withRungs(next), adding ? `Rung added: ${draft.name}.` : `${draft.name} saved.`)) {
      setEditing(null);
      setAdding(false);
    }
  };
  const onKey = (i: number) => (e: KeyboardEvent) => {
    if (e.key === "ArrowUp") { e.preventDefault(); move(i, i - 1); }
    if (e.key === "ArrowDown") { e.preventDefault(); move(i, i + 1); }
  };
  const editor = (
    <div className="u-rung-edit">
      <label>Rung name<input className="u-input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
      <label>Fact it needs
        <select className="u-input" value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
          <option value="">Choose a fact</option>
          {v.sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </label>
      <label>Fact text. Write {"{item}"} where the website fact goes.
        <input className="u-input" value={draft.fact} placeholder="is hiring a {item}" onChange={(e) => setDraft({ ...draft, fact: e.target.value })} /></label>
      <label>What it usually means
        <input className="u-input" value={draft.implication} onChange={(e) => setDraft({ ...draft, implication: e.target.value })} /></label>
      <div className="u-row">
        <button type="button" className="u-btn sm primary" onClick={saveEdit}>Save rung</button>
        <button type="button" className="u-btn sm" onClick={() => { setEditing(null); setAdding(false); }}>Cancel</button>
      </div>
    </div>
  );

  return (
    <div data-testid="ice-rungs">
      <p className="u-small u-muted" style={{ margin: "0 0 4px" }}>Rungs are checked from top to bottom. The first rung with a matching fact is used. Drag to reorder.</p>
      {rs.rungs.map((r, i) => (
        <Fragment key={r.id}>
          <div className={["u-rung", r.on ? "" : "off", drag === i ? "drag" : ""].filter(Boolean).join(" ")} data-testid="rung"
            draggable onDragStart={() => setDrag(i)} onDragEnd={() => setDrag(null)}
            onDragOver={(e: DragEvent) => e.preventDefault()}
            onDrop={(e: DragEvent) => { e.preventDefault(); if (drag !== null) move(drag, i); setDrag(null); }}>
            <button type="button" className="u-handle" aria-label={`Move ${r.name}. Use the up and down arrow keys.`} onKeyDown={onKey(i)}>⋮⋮</button>
            <span className="u-num">{i + 1}</span>
            <div><b className="u-ink">{r.name}</b><div className="u-small u-muted">{r.needs}</div></div>
            <div className="u-row">
              <span className={r.on ? (r.used ? "u-pill good" : "u-pill") : "u-pill"}>{r.on ? `${r.used ?? 0} used` : "Off"}</span>
              <button type="button" className="u-link u-small" onClick={() => startEdit(i)}>Edit</button>
              <Switch checked={r.on} onChange={(on) => toggle(i, on)} label={`${r.name} on or off`} />
            </div>
            {editing === i && !adding ? editor : null}
          </div>
        </Fragment>
      ))}
      <div className="u-rung">
        <span className="u-handle" aria-hidden="true" />
        <span className="u-num">D</span>
        <div><b className="u-ink">Default</b><div className="u-small u-muted">Used when no rung matches. {rs.default.length} versions, assigned evenly.</div></div>
        <div className="u-row"><span className="u-pill">{rs.default_used ?? 0} used</span></div>
      </div>
      {adding ? <div className="u-rung"><span /><span className="u-num">+</span><div><b className="u-ink">New rung</b></div><span />{editor}</div> : (
        <button type="button" className="u-btn sm" style={{ marginTop: 10 }}
          onClick={() => { setEditing(null); setAdding(true); setDraft({ ...BLANK }); }}>+ Add rung</button>
      )}
    </div>
  );
}

function Highlight({ text }: { text: string }) {
  const parts = text.split(/(\{[a-z_]+\})/g);
  return <>{parts.map((p, i) => (/^\{[a-z_]+\}$/.test(p) ? <span key={i} className="u-var">{p}</span> : <Fragment key={i}>{p}</Fragment>))}</>;
}

function TemplateTab({ rs }: { rs: RuleSet }) {
  return (
    <div data-testid="ice-template">
      <p className="u-small u-muted" style={{ margin: "0 0 8px" }}>Highlighted fields are filled for each lead. The greeting comes from the email template.</p>
      <div className="u-mail"><Highlight text={rs.template} /></div>
      <div className="u-scroll">
        <table className="u-table" style={{ marginTop: 12 }}>
          <thead><tr><th>Field</th><th>Source</th></tr></thead>
          <tbody>
            <tr><td><span className="u-var">{"{company}"}</span></td><td>Short company name</td></tr>
            <tr><td><span className="u-var">{"{shared_ground}"}</span></td>
              <td>Fixed per campaign, A/B tested: {rs.shared_ground.map((g) => `“${g}”`).join(" / ")}</td></tr>
            <tr><td><span className="u-var">{"{fact}"}</span> <span className="u-var">{"{implication}"}</span></td><td>The matching rung, from website research</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PreviewTab({ source, options }: { source: string; options: { key: string; company: string }[] }) {
  const [key, setKey] = useState(options[0]?.key ?? "");
  const [p, setP] = useState<IcePreview | null>(null);
  useEffect(() => {
    if (!key) return;
    getJson<IcePreview>("/stack/ice/preview", { source, key }).then(setP).catch(() => setP(null));
  }, [source, key]);
  if (!options.length) return <div className="u-pempty">No lead can have an ice breaker yet. Run Find email and Website research first.</div>;
  return (
    <div data-testid="ice-preview">
      <div className="u-row" style={{ marginBottom: 10 }}>
        <span className="u-small u-muted">Lead</span>
        <select className="u-input u-sel" aria-label="Lead to preview" value={key} onChange={(e) => setKey(e.target.value)}>
          {options.map((o) => <option key={o.key} value={o.key}>{o.company}</option>)}
        </select>
      </div>
      {!p ? <Loading rows={2} /> : p.error ? <ErrorBox title="No preview" detail={p.error} /> : (
        <>
          <div className="u-kv"><span>Rung</span><span><b className="u-ink">{p.rung || "—"}</b></span><span>Fact</span><span>{p.fact || "—"}</span></div>
          {p.line ? <div className="u-mail" style={{ marginTop: 10 }}>{p.line}</div> : null}
          {p.note ? <div className="u-small u-muted" style={{ marginTop: 6 }}>{p.note}</div> : null}
        </>
      )}
    </div>
  );
}

function LeadsTab({ leads, sel, setSel }: { leads: IceLead[]; sel: string[]; setSel: (k: string[]) => void }) {
  const can = (l: IceLead) => !l.sent && (l.status.value === "written" || l.status.value === "waiting");
  const flip = (k: string) => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k]);
  return (
    <div className="u-scroll" data-testid="ice-leads">
      <table className="u-table">
        <thead><tr><th><span className="u-sr">Select</span></th><th>Company</th><th>Rung</th><th>Ice breaker</th><th>Status</th></tr></thead>
        <tbody>
          {leads.map((l) => (
            <tr key={l.key}>
              <td><input type="checkbox" aria-label={`Select ${l.company}`} disabled={!can(l)} checked={sel.includes(l.key)} onChange={() => flip(l.key)} /></td>
              <td><b className="u-ink">{l.company}</b></td>
              <td>{l.rung || "—"}</td>
              <td><div className="u-cut" title={l.line}>{l.line || "—"}</div></td>
              <td><span className={l.status.tone ? `u-pill ${l.status.tone}` : "u-pill"}>{l.sent ? `${l.status.label} · sent` : l.status.label}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="u-note" style={{ marginTop: 12 }}>Writes <span className="u-mono">icebreaker_status</span>: written or failed. A lead with no matching rung, no website or nothing readable on it gets the Default line. The line itself is kept in the app. A lead that was already sent is never rewritten.</div>
    </div>
  );
}
