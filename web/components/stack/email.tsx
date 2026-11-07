"use client";

/* Step 4, Cold email. /email lists the campaigns; /email?open=demo opens one with three tabs:
 * Templates (live ones share the leads evenly; drafts are approved, edited or rejected),
 * Requests to Claude (the queue), and Preview (one lead + one template, filled in). */

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { DemoBar, LaterTile, onlyReal, useParam } from "@/components/stack/common";
import { PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { flashNote } from "@/lib/nav";
import type { EmailCamp, EmailOverview, EmailPreview, Template } from "@/lib/stack-types";

export function EmailPage() {
  const open = useParam("open");
  if (open === null) return <div className="u-page"><Loading rows={6} /></div>;
  return open ? <EmailCampPage source={open} /> : <EmailList />;
}

function EmailList() {
  const [v, setV] = useState<EmailOverview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getJson<EmailOverview>("/stack/email").then(setV).catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Email template" sub="Step 4. Email templates for each campaign, scored against the copy rulebook." />
      {error ? <ErrorBox title="Email templates could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={4} /></div> : (
        <div className="u-grid3" data-testid="email-campaigns">
          {onlyReal(v.campaigns, (c) => c.demo).map((c) => (
            <div className="u-tile" key={c.id}>
              <b className="u-ink">{c.name}</b>
              <div className="u-small u-muted" style={{ margin: "4px 0 10px" }}>
                {c.live ? `${c.live} live template${c.live === 1 ? "" : "s"}` : "No template"}{c.drafts ? ` · ${c.drafts} awaiting approval` : ""}</div>
              <div className="u-small">{c.live ? <>Top score: <b className="u-ink">{c.top_score}</b></> : "Request one from Claude"}</div>
              <Link className="u-btn sm primary" style={{ marginTop: 12 }} href={`/email?open=${encodeURIComponent(c.id)}`}>Open</Link>
            </div>
          ))}
          <LaterTile count={v.later.count} why={v.later.why} />
        </div>
      )}
    </div>
  );
}

const TABS = [["tpl", "Templates"], ["ask", "Requests to Claude"], ["prev", "Preview"]] as const;
type TabId = (typeof TABS)[number][0];

function EmailCampPage({ source }: { source: string }) {
  const [v, setV] = useState<EmailCamp | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<TabId>("tpl");
  const [problem, setProblem] = useState("");

  const load = () =>
    getJson<EmailCamp>("/stack/email/camp", { source })
      .then((r) => { if (r.error) throw new Error(r.error); setV(r); })
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
    if (new URLSearchParams(window.location.search).get("tab") === "ask") setTab("ask");
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (id: number, action: string, extra: Record<string, string> = {}, note = "") => {
    setProblem("");
    const r = await postJson<{ ok: boolean; error?: string; score?: number }>("/stack/email/template", { source, id, action, ...extra });
    if (!r.ok) {
      setProblem(r.error || "Not done.");
      return false;
    }
    flashNote(note || (action === "edit" ? `Saved. New score: ${r.score}.` : "Done."));
    await load();
    return true;
  };

  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      {v?.demo ? <DemoBar /> : null}
      <PageHead back={{ href: "/email", label: "Email template" }} title={`Email template · ${v?.name ?? "…"}`}
        sub="Leads are split evenly between live templates. Drafts are used only after approval." />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not done" detail={problem} /></div> : null}
      {error ? <ErrorBox title="This campaign could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={8} /></div> : (
        <div className="u-card">
          <div className="u-tabs" role="tablist">
            {TABS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : undefined}
                onClick={() => setTab(id)}>{label}</button>
            ))}
          </div>
          {tab === "tpl" ? (
            <div data-testid="email-templates">
              <div className="u-grid3">
                {v.templates.map((t) => <TemplateTile key={t.id} t={t} act={act} />)}
              </div>
              <div className="u-note" style={{ marginTop: 14 }}>
                Score: {v.templates[0]?.of ?? 8} checks from the copy rulebook, 100 points. Any figure in an email must have a recorded source, or the template is blocked.
                Drafts from Claude scoring {v.auto_approve_at} or more are approved automatically. Approved figures: {v.approved_figures.join(", ")}.
              </div>
            </div>
          ) : null}
          {tab === "ask" ? <Requests v={v} source={source} reload={load} setProblem={setProblem} /> : null}
          {tab === "prev" ? <Preview v={v} source={source} /> : null}
        </div>
      )}
    </div>
  );
}

function Fields({ text }: { text: string }) {
  const parts = text.split(/(\{\{[a-z_]+\}\})/g);
  return <>{parts.map((p, i) => (/^\{\{[a-z_]+\}\}$/.test(p) ? <span key={i} className="u-var">{p}</span> : <Fragment key={i}>{p}</Fragment>))}</>;
}

function TemplateTile({ t, act }: { t: Template; act: (id: number, action: string, extra?: Record<string, string>, note?: string) => Promise<boolean> }) {
  const [edit, setEdit] = useState(false);
  const [sub, setSub] = useState(t.subject);
  const [body, setBody] = useState(t.body);
  const draft = t.state.value === "draft";
  const live = t.state.value === "live";
  const missed = t.checks.filter((c) => !c.ok).map((c) => c.name);
  return (
    <div className={draft ? "u-tile attn" : "u-tile"} data-testid="template">
      <div className="u-row sb"><b className="u-ink">{t.name}</b>
        <span className={`u-pill ${t.state.tone}`}>{live ? `Live · ${t.share}%` : t.state.label}</span></div>
      <div className="u-small u-muted">
        Score {t.score}{live ? ` · ${t.sent} sent · ${t.replies} repl${t.replies === 1 ? "y" : "ies"}` : t.request ? ` · request: “${t.request}”` : ""}
        {t.approved_by === "auto" ? " · approved automatically" : ""}
      </div>
      {t.blocked ? <div className="u-note bad" style={{ marginTop: 8 }}>Blocked: {t.unapproved.join(", ") || "an unknown field"} has no recorded source.</div> : null}
      {edit ? (
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          <input className="u-input" aria-label="Subject" value={sub} onChange={(e) => setSub(e.target.value)} />
          <textarea className="u-input" aria-label="Body" rows={9} value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="u-row">
            <button type="button" className="u-btn sm primary" onClick={async () => { if (await act(t.id, "edit", { subject: sub, body })) setEdit(false); }}>Save and score</button>
            <button type="button" className="u-btn sm" onClick={() => { setEdit(false); setSub(t.subject); setBody(t.body); }}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="u-mail sm"><b>Subject:</b> <Fields text={t.subject} />{"\n\n"}<Fields text={t.body} /></div>
      )}
      <div className="u-small u-muted" style={{ marginTop: 8 }}>
        {t.passed} of {t.of} checks{missed.length ? `. Missing: ${missed.join(", ").toLowerCase()}` : ""}.
        {t.mistakes.length ? ` Mistakes: ${t.mistakes.map((m) => `${m.name.toLowerCase()} (−${m.cost})`).join(", ")}.` : ""}
      </div>
      {draft && !edit ? (
        <div className="u-row" style={{ marginTop: 10 }}>
          <button type="button" className="u-btn sm primary" disabled={t.blocked} title={t.blocked ? "Blocked drafts cannot be approved" : undefined}
            onClick={() => act(t.id, "approve", {}, `${t.name} approved. Leads are now split between the live templates.`)}>Approve</button>
          <button type="button" className="u-btn sm" onClick={() => setEdit(true)}>Edit</button>
          <button type="button" className="u-btn sm" onClick={() => act(t.id, "reject", {}, `${t.name} rejected.`)}>Reject</button>
        </div>
      ) : null}
    </div>
  );
}

function Requests({ v, source, reload, setProblem }: { v: EmailCamp; source: string; reload: () => Promise<void>; setProblem: (s: string) => void }) {
  const [kind, setKind] = useState(v.kinds[0]?.id ?? "new");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string; state?: string; score?: number; auto_approved?: boolean; blocked?: boolean }>(
        "/stack/email/request", { source, kind, instructions: text });
      if (!r.ok) throw new Error(r.error || "Not sent.");
      flashNote(r.state === "queued" ? "Request queued." : r.auto_approved
        ? `Draft scored ${r.score} and was approved automatically.`
        : `Draft ready, score ${r.score}${r.blocked ? ", blocked by a figure without a source" : ""}. Approve it on the Templates tab.`);
      setText("");
      await reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };
  return (
    <div className="u-grid2" style={{ alignItems: "start" }} data-testid="email-requests">
      <div>
        <div className="u-small u-muted" style={{ marginBottom: 6 }}>Request type</div>
        <select className="u-input" aria-label="Request type" style={{ marginBottom: 8 }} value={kind} onChange={(e) => setKind(e.target.value)}>
          {v.kinds.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
        <div className="u-small u-muted" style={{ marginBottom: 6 }}>Instructions</div>
        <textarea className="u-input" aria-label="Instructions" rows={4} value={text} placeholder="New template for small businesses. Shorter. Lead with month-end close."
          onChange={(e) => setText(e.target.value)} />
        <button type="button" className="u-btn primary" style={{ marginTop: 8 }} disabled={busy || text.trim().length < 5} onClick={submit}>
          {busy ? "Sending request…" : "Submit request"}</button>
        <div className="u-note" style={{ marginTop: 10 }}>
          Requests are processed by Claude Code with the rulebook and approved facts, either on demand or every morning at 08:00. Results return here as drafts.
          {v.demo ? " In the demo a stand-in answers at once with a fixed draft for each request type." : ""}
        </div>
      </div>
      <div>
        <div className="u-small u-muted" style={{ marginBottom: 6 }}>Request history</div>
        <div className="u-scroll">
          <table className="u-table">
            <thead><tr><th>Request</th><th>Status</th></tr></thead>
            <tbody>
              {v.requests.length ? v.requests.map((r) => (
                <tr key={r.id}><td>{r.instructions}<div className="u-small u-muted">{r.kind}</div></td>
                  <td><span className={`u-pill ${r.state.tone}`}>{r.state.label}</span></td></tr>
              )) : <tr><td colSpan={2} className="u-muted">No requests yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Preview({ v, source }: { v: EmailCamp; source: string }) {
  const usable = v.templates.filter((t) => t.state.value !== "rejected");
  const [key, setKey] = useState(v.preview[0]?.key ?? "");
  const [tid, setTid] = useState(usable[0]?.id ?? 0);
  const [p, setP] = useState<EmailPreview | null>(null);
  useEffect(() => {
    if (!key || !tid) return;
    getJson<EmailPreview>("/stack/email/preview", { source, key, template: String(tid) }).then(setP).catch(() => setP(null));
  }, [source, key, tid]);
  if (!v.preview.length) return <div className="u-pempty">No lead has an ice breaker yet. Write ice breakers first, then preview an email here.</div>;
  return (
    <div data-testid="email-preview">
      <div className="u-row" style={{ marginBottom: 10 }}>
        <span className="u-small u-muted">Lead</span>
        <select className="u-input u-sel" aria-label="Lead to preview" value={key} onChange={(e) => setKey(e.target.value)}>
          {v.preview.map((o) => <option key={o.key} value={o.key}>{o.company}</option>)}
        </select>
        <span className="u-small u-muted">Template</span>
        <select className="u-input u-sel" aria-label="Template to preview" value={tid} onChange={(e) => setTid(Number(e.target.value))}>
          {usable.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      {!p ? <Loading rows={4} /> : p.error ? <ErrorBox title="No preview" detail={p.error} /> : (
        <>
          <div className="u-mail"><span className="u-muted">To:</span> {p.to}{"\n"}<span className="u-muted">Subject:</span> {p.subject}{"\n\n"}{p.body}</div>
          {p.note ? <div className="u-note warn" style={{ marginTop: 8 }}>{p.note}</div> : null}
        </>
      )}
    </div>
  );
}
