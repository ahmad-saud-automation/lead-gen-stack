"use client";

/* New campaign: the same four sections as the campaign page, one at a time, then a Review that
 * says in one sentence what the campaign will do. It ends with a free test, so nothing is spent
 * or sent until the person has seen what it does. */

import { useCallback, useEffect, useMemo, useState } from "react";

import { DEFAULT_SCHEDULE, WhenSection } from "@/components/campaign/when";
import { ManySection, SendSection } from "@/components/campaign/sections";
import { WhoSection, type SourceOption } from "@/components/campaign/who";
import { Confirm } from "@/components/modal";
import { Checklist, Field, Note, PageHead } from "@/components/u";
import { ErrorBox } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { money, num } from "@/lib/format";
import { goWithNote } from "@/lib/nav";
import { runHref } from "@/lib/status";
import type {
  CampaignCounts, CampaignDetail, CampaignRaw, CampaignsSaved, CampaignsView, ImportPreview, ImportsView,
  InstantlyOptions, LaneSchedule, RunStarted, SchedulePreview, SheetInfo,
} from "@/lib/types";
import { rulesSentence } from "@/lib/words";

const STEPS = ["Who", "How many", "Send to", "When", "Review"];
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63);

const BLANK: CampaignRaw = {
  id: "", name: "", tab: "", fieldmap: "", rules: {}, order: [], labels: [], auto_push: false,
  limits: { per_run: 50, per_day: 100, max_spend_usd: 2 }, instantly: {}, writeback: { enabled: true },
};

export function NewCampaignWizard({ presetTab }: { presetTab?: string }) {
  const [step, setStep] = useState(0);
  const [c, setC] = useState<CampaignRaw>({ ...BLANK, tab: presetTab ?? "" });
  const [sched, setSched] = useState<LaneSchedule>(DEFAULT_SCHEDULE);
  const [copyFrom, setCopyFrom] = useState("");
  const [lanes, setLanes] = useState<CampaignsView["campaigns"]>([]);
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [src, setSrc] = useState<ImportPreview | null>(null);
  const [counts, setCounts] = useState<CampaignCounts | null>(null);
  const [counting, setCounting] = useState(false);
  const [inst, setInst] = useState<InstantlyOptions | null>(null);
  const [sp, setSp] = useState<SchedulePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [askAuto, setAskAuto] = useState(false);

  const loadInstantly = useCallback(() => {
    setInst(null);
    getJson<InstantlyOptions>("/instantly/options").then(setInst).catch((e: Error) => setInst({ ok: false, detail: e.message, campaigns: [], lists: [] }));
  }, []);

  useEffect(() => {
    getJson<CampaignsView>("/campaigns").then((v) => setLanes(v.campaigns ?? [])).catch(() => {});
    Promise.all([getJson<SheetInfo>("/sheets/info").catch(() => null), getJson<ImportsView>("/imports").catch(() => null)]).then(([sh, im]) => {
      const list = [
        ...(sh?.tabs ?? []).map((t) => ({ tab: t, label: `Google Sheet → ${t.trim()}` })),
        ...(im?.imports ?? []).map((i) => ({ tab: i.tab, label: `Uploaded → ${i.name} (${num(i.rows)} rows)` })),
      ];
      setSources(list);
      setC((x) => (x.tab ? x : { ...x, tab: list[0]?.tab ?? "" }));
    });
    loadInstantly();
  }, [loadInstantly]);

  // the column-matching file follows the source: the one its campaigns use, else its own new one
  const tab = c.tab ?? "";
  useEffect(() => {
    if (!tab) return;
    const used = lanes.find((l) => l.tab === tab)?.fieldmap;
    const own = tab.startsWith("import:") ? `fieldmap.${tab.slice(7)}.json` : `fieldmap.${slug(tab) || "source"}.json`;
    setC((x) => ({ ...x, fieldmap: used || own }));
    setSrc(null);
    getJson<ImportPreview>("/imports/preview", { tab }).then((p) => setSrc(p.error ? null : p)).catch(() => setSrc(null));
  }, [tab, lanes]);

  const countKey = JSON.stringify({ tab: c.tab, rules: c.rules, order: c.order, limits: c.limits, fieldmap: c.fieldmap });
  useEffect(() => {
    if (!c.tab) return;
    setCounting(true);
    const t = setTimeout(() => {
      postJson<CampaignCounts>("/campaigns/preview", c).then(setCounts).catch(() => setCounts(null)).finally(() => setCounting(false));
    }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countKey]);

  useEffect(() => {
    if (step !== 4) return;
    postJson<SchedulePreview>("/schedules/preview", sched).then(setSp).catch(() => setSp(null));
  }, [step, sched]);

  // "Start from a copy": the other campaign's filters, order, limits and extra info — never its
  // Instantly campaign (sharing one is allowed, but it is typed in on purpose, not copied)
  const pickCopy = async (id: string) => {
    setCopyFrom(id);
    if (!id) return;
    try {
      const d = await getJson<CampaignDetail>("/campaigns/detail", { id });
      if (d.error) throw new Error(d.error);
      const s = d.campaign;
      setC((x) => ({
        ...x, tab: s.tab ?? x.tab, rules: s.rules ?? {}, order: s.order ?? [], labels: s.labels ?? [],
        limits: { ...x.limits, ...(s.limits ?? {}) },
        instantly: { ...(s.instantly ?? {}), campaign_id: "" },
        writeback: { enabled: s.writeback?.enabled !== false },
      }));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  };

  const set = (patch: Partial<CampaignRaw>) => setC((x) => ({ ...x, ...patch }));
  const setIn = <K extends "limits" | "writeback" | "instantly">(key: K, patch: NonNullable<CampaignRaw[K]>) =>
    setC((x) => ({ ...x, [key]: { ...(x[key] ?? {}), ...patch } }));

  const id = slug(c.name ?? "");
  const taken = lanes.some((l) => l.id === id);
  const nameOk = !!id && !taken;
  const instName = inst?.campaigns.find((x) => x.id === c.instantly?.campaign_id)?.name;
  const sentence = useMemo(() => rulesSentence(c.rules), [c.rules]);

  const create = async (test: boolean) => {
    setBusy(true);
    setProblem("");
    let made = "";
    try {
      const r = await postJson<CampaignsSaved>("/campaigns/create", { name: c.name, id, tab: c.tab, fieldmap: c.fieldmap, copy_from: copyFrom || undefined });
      if (!r.ok || !r.campaign) throw new Error((r.issues ?? []).map((i) => i.issue).join(" · ") || "Not created.");
      made = r.campaign;
      const s = await postJson<CampaignsSaved>("/campaigns/save", {
        id: made, name: c.name, rules: c.rules, order: c.order, labels: c.labels, limits: c.limits, auto_push: !!c.auto_push,
        instantly: c.instantly, writeback: { ...(c.writeback ?? {}), campaign_type: made },
      });
      if (!s.ok) throw new Error((s.issues ?? []).map((i) => i.issue).join(" · "));
      if (sched.enabled) {
        const q = await postJson<{ ok: boolean; problems?: string[] }>("/campaigns/schedule", { id: made, schedule: sched });
        if (!q.ok) throw new Error(`Schedule not saved: ${(q.problems ?? []).join(" · ")}`);
      }
      if (test) {
        const run = await postJson<RunStarted>("/campaign/run", { campaign: made, test_mode: true });
        if (run.error || !run.run_id) throw new Error(`Created, but the free test did not start: ${run.error}`);
        goWithNote(runHref(run.run_id), `“${c.name}” created. Its free test is running — nothing is spent or sent.`);
      } else {
        goWithNote(`/campaigns/${encodeURIComponent(made)}`, `“${c.name}” created. It is off — switch it on when you are ready.`);
      }
    } catch (e) {
      const why = e instanceof Error ? e.message : String(e);
      setProblem(made ? `${why} — the campaign was created; open it from Campaigns to finish.` : why);
      setBusy(false);
    }
  };

  const canNext = step === 0 ? nameOk && !!c.tab : true;

  return (
    <div className="u-page">
      <PageHead back={{ href: "/campaigns", label: "Campaigns" }} title="New campaign"
        sub="Four short steps. You can change everything later, and it ends with a free test." />
      <div className="u-stepper">
        {STEPS.map((s, i) => <span key={s} className={i === step ? "on" : i < step ? "done" : undefined}>{i + 1} · {s}</span>)}
      </div>
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="That did not work" detail={problem} /></div> : null}

      {step === 0 ? (
        <div className="u-stack">
          <div className="u-card">
            <div className="u-fgrid two">
              <Field label="Name" bad={taken} hint={taken ? "There is already a campaign with this name." : id ? <>Saved as <span className="u-mono">{id}</span></> : "e.g. Practices 51-200 staff"}>
                <input className="u-input" aria-label="Name" autoFocus value={c.name ?? ""} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Practices 51-200 staff" />
              </Field>
              <Field label="Start from" hint={copyFrom ? "Copies its filters, order, limits and extra info — never its Instantly campaign." : "An empty campaign."}>
                <select className="u-input" aria-label="Start from" value={copyFrom} onChange={(e) => pickCopy(e.target.value)}>
                  <option value="">Nothing — start empty</option>
                  {lanes.map((l) => <option key={l.id} value={l.id}>A copy of {l.name}</option>)}
                </select>
              </Field>
            </div>
          </div>
          <WhoSection c={c} set={set} sources={sources} headers={src?.headers ?? []} resolved={src?.check?.resolved ?? {}} counts={counts} counting={counting} />
        </div>
      ) : null}
      {step === 1 ? <ManySection c={c} setIn={setIn} counts={counts} /> : null}
      {step === 2 ? (
        <SendSection c={c} setIn={setIn} inst={inst} reload={loadInstantly}
          onAutoPush={(v) => (v ? setAskAuto(true) : set({ auto_push: false }))} />
      ) : null}
      {step === 3 ? <WhenSection s={sched} set={(p) => setSched((x) => ({ ...x, ...p }))} /> : null}
      {step === 4 ? (
        <div className="u-card">
          <h2 className="u-h2">Ready to create</h2>
          <p className="u-muted">This is exactly what the campaign will do.</p>
          <Note>
            <span style={{ fontSize: 15, lineHeight: 1.7, color: "var(--ink)" }}>
              Take leads from <b>{(c.tab ?? "").replace(/^import:/, "uploaded file ").trim()}</b>
              {sentence ? <> where <b>{sentence}</b></> : " (every lead in it)"}
              {counts && !counts.error ? <> — <b>{num(counts.not_contacted)}</b> never contacted</> : null},
              {" "}<b>{num(c.limits?.per_run ?? 0)} per run</b>, at most <b>{c.limits?.per_day ? `${num(c.limits.per_day)} a day` : "no daily limit"}</b> and <b>{money(c.limits?.max_spend_usd ?? 0)} a run</b>,
              and send them to <b>{instName ?? (c.instantly?.campaign_id ? c.instantly.campaign_id : "no Instantly campaign yet")}</b>
              {c.auto_push ? " automatically" : " after you review them"}.
              {" "}{sched.enabled ? <>Runs by itself: <b>{sp?.summary ?? "…"}</b>{sched.test_mode ? " (free tests)" : " (live)"}.</> : <>Runs <b>only when you press Run</b>.</>}
            </span>
          </Note>
          <Checklist items={[
            { ok: !!src?.check?.ok, text: src?.check?.ok ? "Every column it needs is matched" : "Some columns need matching — fix them on the Leads page after creating" },
            { ok: !!c.instantly?.campaign_id, text: c.instantly?.campaign_id ? "Instantly campaign chosen" : "No Instantly campaign yet — fine for a test, needed before going live" },
            { ok: true, text: "It starts switched off, and last in the order — it cannot take leads from your other campaigns until you switch it on" },
          ]} />
          {sp?.problems.length && sched.enabled ? <div style={{ marginTop: 10 }}><Note tone="bad">{sp.problems.join(" · ")}</Note></div> : null}
        </div>
      ) : null}

      <div className="u-row" style={{ justifyContent: "space-between", marginTop: 18 }}>
        <button type="button" className="u-btn" style={{ visibility: step ? "visible" : "hidden" }} onClick={() => setStep(step - 1)} disabled={busy}>Back</button>
        <div className="u-row">
          {step === 4 ? <button type="button" className="u-btn" onClick={() => create(false)} disabled={busy}>Create only</button> : null}
          <button type="button" className="u-btn primary" disabled={!canNext || busy}
            onClick={() => (step === 4 ? create(true) : setStep(step + 1))}
            title={!canNext ? "Give it a name first" : undefined}>
            {step === 4 ? (busy ? "Creating…" : "Create and run a free test") : "Next"}
          </button>
        </div>
      </div>

      {askAuto ? (
        <Confirm title="Send to Instantly without asking?" confirmLabel="Yes, send automatically" onConfirm={() => { set({ auto_push: true }); setAskAuto(false); }} onClose={() => setAskAuto(false)}
          body={<p>After each run, every checked lead with an ice breaker goes straight into the Instantly campaign. For a new campaign, most people leave this off until they have seen a few runs.</p>} />
      ) : null}
    </div>
  );
}
