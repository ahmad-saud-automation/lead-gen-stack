"use client";

/* Settings (docs/UX-REDESIGN.md §3, technical settings §§1, 6–11): set once, then left alone.
 * Every one of the engine's settings is here — the common ones in plain groups, the rare ones
 * under Advanced. One Save for the form; a key test, the password and "forget all leads" act at
 * once because they are actions, not settings. */

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Confirm } from "@/components/modal";
import { RecipesSection } from "@/components/recipe/list";
import { Card, Field, Note, PageHead, Seg, Switch, SwitchRow, TagList } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { num } from "@/lib/format";
import { reloadWithNote } from "@/lib/nav";
import type { CampaignsSaved, CampaignsView, Config, ConnectionTest, LedgerView } from "@/lib/types";

type Cfg = Record<string, unknown>;
const KEY_FIELDS = ["millionverifier_api_key", "instantly_api_key", "icypeas_api_key", "anymailfinder_api_key", "openai_api_key"];
const NUMBERS = ["mv_per_verification_usd", "push_delay_seconds", "api_tries", "icypeas_usd_per_credit", "anymailfinder_usd_per_credit",
  "apollo_credit_usd", "api_retry_wait", "verify_delay_ms", "icypeas_throttle_seconds", "max_firms"];

/* Finding emails: three styles that set the ladder below them (§1 of the proposal) */
const FIND_KEYS = ["use_endole", "verify_endole_with_mf", "use_patterns", "pattern_mode", "use_icypeas", "verify_icypeas_with_mf",
  "use_anymailfinder", "verify_anymailfinder_with_mf"] as const;
const PRESETS: Record<string, { label: string; text: string; set: Cfg }> = {
  cheap: { label: "Cheapest", text: "The email in your sheet, then 3 guesses. No paid finders.",
    set: { use_endole: true, verify_endole_with_mf: false, use_patterns: true, pattern_mode: "lean", use_icypeas: false, verify_icypeas_with_mf: false, use_anymailfinder: false, verify_anymailfinder_with_mf: false } },
  bal: { label: "Balanced", text: "Recommended. Re-checks the sheet’s email and asks Icypeas when guessing fails.",
    set: { use_endole: true, verify_endole_with_mf: true, use_patterns: true, pattern_mode: "lean", use_icypeas: true, verify_icypeas_with_mf: false, use_anymailfinder: false, verify_anymailfinder_with_mf: false } },
  max: { label: "Find the most", text: "Every finder, 5 guesses, everything double-checked. Costs the most.",
    set: { use_endole: true, verify_endole_with_mf: true, use_patterns: true, pattern_mode: "plus", use_icypeas: true, verify_icypeas_with_mf: true, use_anymailfinder: true, verify_anymailfinder_with_mf: true } },
};
/* Speed and retries: two named paces, or your own numbers */
const SPEED_KEYS = ["push_delay_seconds", "api_tries", "api_retry_wait", "verify_delay_ms", "icypeas_throttle_seconds"] as const;
const SPEEDS: Record<string, Record<string, string>> = {
  normal: { push_delay_seconds: "3", api_tries: "3", api_retry_wait: "5", verify_delay_ms: "0", icypeas_throttle_seconds: "2" },
  gentle: { push_delay_seconds: "5", api_tries: "4", api_retry_wait: "10", verify_delay_ms: "300", icypeas_throttle_seconds: "4" },
};

function Rung({ n, on, title, desc, children, onToggle, disabled }: {
  n: number; on: boolean; title: string; desc: ReactNode; children?: ReactNode; onToggle: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <div className={on ? "u-rung" : "u-rung off"}>
      <span className="u-num">{n}</span>
      <div><b className="u-ink">{title}</b><div className="u-small u-muted">{desc}</div>{children ? <div className="sub">{children}</div> : null}</div>
      <Switch label={title} checked={on} onChange={onToggle} disabled={disabled} />
    </div>
  );
}

function ConnRow({ title, desc, keyField, cfg, setKey, service, test, onTest }: {
  title: string; desc: string; keyField: string; cfg: Cfg; setKey: (k: string, v: string) => void;
  service?: string; test?: ConnectionTest | "busy"; onTest?: (s: string) => void;
}) {
  const set = (cfg.keys_set as Record<string, boolean> | undefined)?.[keyField];
  const value = String(cfg[keyField] ?? "");
  const typed = value && !value.includes("*");
  return (
    <div className="u-conn">
      <div>
        <b className="u-ink">{title}</b>
        <div className="u-small u-muted">{desc}</div>
        <input className="u-input u-mono" type="password" autoComplete="off" aria-label={`${title} key`} style={{ marginTop: 8, maxWidth: 420 }}
          placeholder={set ? `saved ${value.slice(-4) ? `(…${value.slice(-4)})` : ""} — type to replace` : "paste the key here"}
          value={typed ? value : ""} onChange={(e) => setKey(keyField, e.target.value.trim())} />
        {test && test !== "busy" ? (
          <div className={`u-small ${test.ok ? "u-tick" : test.ok === false ? "u-badmark" : "u-muted"}`} style={{ marginTop: 6, fontWeight: 500 }}>
            {test.ok ? "✓ " : test.ok === false ? "✕ " : ""}{test.detail}
          </div>
        ) : null}
      </div>
      <div className="u-row">
        {set ? <span className="u-tick u-small">✓ saved</span> : <span className="u-small u-muted">not added</span>}
        {service && onTest ? (
          <button type="button" className="u-btn sm" disabled={test === "busy" || !set || !!typed} title={typed ? "Save first, then test" : undefined}
            onClick={() => onTest(service)}>{test === "busy" ? "Checking…" : "Test"}</button>
        ) : null}
      </div>
    </div>
  );
}

export function SettingsPage() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [orig, setOrig] = useState("");
  const [caps, setCaps] = useState({ daily_push_cap: "", daily_spend_cap_usd: "" });
  const [origCaps, setOrigCaps] = useState("");
  const [tabs, setTabs] = useState<{ tab: string; path: string }[]>([]);
  const [ledger, setLedger] = useState<LedgerView | null>(null);
  const [tests, setTests] = useState<Record<string, ConnectionTest | "busy">>({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState("");
  const [forget, setForget] = useState(false);
  const [showLeads, setShowLeads] = useState(false);

  useEffect(() => {
    Promise.all([getJson<Config>("/config"), getJson<CampaignsView>("/campaigns")])
      .then(([c, v]) => {
        const text: Cfg = { ...c };
        for (const k of NUMBERS) text[k] = String(c[k] ?? "");
        setCfg(text);
        setOrig(JSON.stringify(text));
        const lt = Object.entries((c.local_tabs as Record<string, string>) ?? {}).map(([tab, path]) => ({ tab, path }));
        setTabs(lt);
        const cp = { daily_push_cap: String(v.globals?.daily_push_cap ?? 0), daily_spend_cap_usd: String(v.globals?.daily_spend_cap_usd ?? 0) };
        setCaps(cp);
        setOrigCaps(JSON.stringify({ cp, lt }));
      })
      .catch((e: Error) => setError(e.message));
    getJson<LedgerView>("/ledger").then(setLedger).catch(() => {});
  }, []);

  // links such as /settings#s-conn: the section exists only once the settings have loaded
  const loaded = !!cfg;
  useEffect(() => {
    if (!loaded || !window.location.hash) return;
    const el = document.getElementById(window.location.hash.slice(1));
    if (el instanceof HTMLDetailsElement) el.open = true;
    el?.scrollIntoView({ block: "start" });
  }, [loaded]);

  const dirty = useMemo(() => !!cfg && (JSON.stringify(cfg) !== orig || JSON.stringify({ cp: caps, lt: tabs }) !== origCaps), [cfg, orig, caps, tabs, origCaps]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error) return <div className="u-page"><PageHead title="Settings" /><ErrorBox title="Settings could not be loaded" detail={error} /></div>;
  if (!cfg) return <div className="u-page"><PageHead title="Settings" /><div className="u-card"><Loading rows={8} /></div></div>;

  const b = (k: string) => Boolean(cfg[k]);
  const t = (k: string) => String(cfg[k] ?? "");
  const set = (k: string, v: unknown) => setCfg((x) => ({ ...(x ?? {}), [k]: v }));
  const list = (k: string) => (Array.isArray(cfg[k]) ? (cfg[k] as string[]) : []);
  const keysSet = (cfg.keys_set as Record<string, boolean> | undefined) ?? {};
  const preset = Object.entries(PRESETS).find(([, p]) => FIND_KEYS.every((k) => cfg[k] === p.set[k]))?.[0] ?? "";
  const speed = Object.entries(SPEEDS).find(([, s]) => SPEED_KEYS.every((k) => String(Number(cfg[k])) === s[k]))?.[0] ?? "custom";
  const mvRate = Number(cfg.mv_per_verification_usd) || 0;

  const runTest = async (service: string) => {
    setTests((x) => ({ ...x, [service]: "busy" }));
    try {
      const r = await postJson<ConnectionTest>("/connections/test", { service });
      setTests((x) => ({ ...x, [service]: r }));
    } catch (e) {
      setTests((x) => ({ ...x, [service]: { ok: false, detail: e instanceof Error ? e.message : String(e) } }));
    }
  };

  const save = async () => {
    setSaving(true);
    setProblem("");
    try {
      const { keys_set: _k, has_api_key: _h, ...patch } = cfg;
      for (const k of NUMBERS) patch[k] = Number(cfg[k]) || 0;
      for (const k of KEY_FIELDS) if (String(patch[k] ?? "").includes("*") || !String(patch[k] ?? "")) delete patch[k];
      patch.local_tabs = Object.fromEntries(tabs.filter((x) => x.tab && x.path.trim()).map((x) => [x.tab, x.path.trim()]));
      await postJson("/config", patch);
      // the daily limits live in campaigns.json, so they are saved only when they changed
      if (JSON.stringify(caps) !== JSON.stringify(JSON.parse(origCaps).cp)) {
        const g = await postJson<CampaignsSaved>("/campaigns/globals", {
          daily_push_cap: Number(caps.daily_push_cap) || 0, daily_spend_cap_usd: Number(caps.daily_spend_cap_usd) || 0,
        });
        if (!g.ok) throw new Error(`The rest was saved, but not the daily limits: ${(g.issues ?? []).map((i) => `${i.campaign}: ${i.issue}`).join(" · ")}`);
      }
      reloadWithNote("Settings saved.");
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };
  const forgetAll = async () => {
    setForget(false);
    try {
      await postJson("/ledger/clear", {});
      reloadWithNote("Lead history cleared — every lead can be worked on again.");
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  };

  const jump = (id: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (el instanceof HTMLDetailsElement) el.open = true;
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="u-page">
      <PageHead title="Settings" sub="Set once, then left alone. The rare ones are under Advanced."
        actions={<button type="button" className="u-btn primary" onClick={save} disabled={!dirty || saving}>{saving ? "Saving…" : "Save settings"}</button>} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not saved" detail={problem} /></div> : null}

      <div className="u-settings">
        <nav className="u-subnav" aria-label="Settings sections">
          {[["s-conn", "Connections"], ["s-find", "Finding emails"], ["s-recipes", "Finding recipes"], ["s-limits", "Spending limits"], ["s-safety", "Lead safety"], ["s-login", "Login"], ["s-adv", "Advanced"]].map(([id, label]) => (
            <a key={id} href={`#${id}`} onClick={jump(id)}>{label}</a>
          ))}
        </nav>
        <div className="u-stack">

          <Card id="s-conn" title="Connections" sub="Each has a Test button. A test never spends credits. Keys are never shown again after saving.">
            <div className="u-conn">
              <div>
                <b className="u-ink">Google Sheet</b>
                <div className="u-small u-muted">Where your leads are, and where results are written.</div>
                <div className="u-fgrid two" style={{ marginTop: 8 }}>
                  <Field label="Sheet link"><input className="u-input" aria-label="Sheet link" value={t("sheet_url")} onChange={(e) => set("sheet_url", e.target.value)} placeholder="https://docs.google.com/spreadsheets/d/…" /></Field>
                  <Field label="Google key file (on this computer)" hint="Keep it outside the backed-up folders."><input className="u-input u-mono" aria-label="Google key file" value={t("sheet_service_account_file")} onChange={(e) => set("sheet_service_account_file", e.target.value)} /></Field>
                </div>
                {tests.sheet && tests.sheet !== "busy" ? <div className={`u-small ${tests.sheet.ok ? "u-tick" : "u-badmark"}`} style={{ marginTop: 6 }}>{tests.sheet.ok ? "✓ " : "✕ "}{tests.sheet.detail}</div> : null}
              </div>
              <button type="button" className="u-btn sm" onClick={() => runTest("sheet")} disabled={tests.sheet === "busy"}>{tests.sheet === "busy" ? "Checking…" : "Test"}</button>
            </div>
            <SwitchRow title="Let the app write results into the sheet" desc="Needed for “Update my Google Sheet” on a campaign. Off = nothing is ever written, for any campaign."
              checked={b("sheet_writeback")} onChange={(v) => set("sheet_writeback", v)} />
            <ConnRow title="Instantly" desc="Where found leads are sent. Must be an API V2 key." keyField="instantly_api_key" cfg={cfg} setKey={set} service="instantly" test={tests.instantly} onTest={runTest} />
            <ConnRow title="MillionVerifier" desc="Checks every email before it is sent — the one key the app really needs." keyField="millionverifier_api_key" cfg={cfg} setKey={set} service="millionverifier" test={tests.millionverifier} onTest={runTest} />
            <ConnRow title="Icypeas" desc="Finds an email from a name and company. It has no free test; a refused key shows up in Activity." keyField="icypeas_api_key" cfg={cfg} setKey={set} service="icypeas" test={tests.icypeas} onTest={runTest} />
            <ConnRow title="Anymailfinder" desc="A second finder (optional)." keyField="anymailfinder_api_key" cfg={cfg} setKey={set} service="anymailfinder" test={tests.anymailfinder} onTest={runTest} />
          </Card>

          <Card id="s-find" title="Finding emails" sub="Pick a style, or change the steps under it. The app tries the steps in this order and stops at the first email that passes the check. A campaign that uses a finding recipe follows the recipe instead — these steps are what every other campaign does.">
            <div className="u-presets">
              {Object.entries(PRESETS).map(([k, p]) => (
                <button key={k} type="button" className={preset === k ? "u-preset on" : "u-preset"} onClick={() => setCfg((x) => ({ ...(x ?? {}), ...p.set }))}>
                  <b>{p.label}</b><span className="u-small u-muted">{p.text}</span>
                </button>
              ))}
            </div>
            {!preset ? <p className="u-small u-muted" style={{ marginTop: 8 }}>Your own mix of steps.</p> : null}
            <div className="u-ladder">
              <Rung n={1} on={b("use_endole")} onToggle={(v) => set("use_endole", v)} title="Use the email already in my sheet" desc="Free — many rows already have one.">
                <label className="u-check"><input type="checkbox" checked={b("verify_endole_with_mf")} onChange={(e) => set("verify_endole_with_mf", e.target.checked)} />
                  Double-check it first (MillionVerifier, ~${mvRate.toFixed(4)} each) — protects you from old addresses that bounce</label>
              </Rung>
              <div className="u-arrow">if there is none, or it fails the check ↓</div>
              <Rung n={2} on={b("use_patterns")} onToggle={(v) => set("use_patterns", v)} title="Guess the address from the website"
                desc={`Each guess is checked (~$${mvRate.toFixed(4)} per guess). Skipped when there is no website.`}>
                <Seg label="How many guesses" value={t("pattern_mode") === "plus" ? "plus" : "lean"} onChange={(v) => set("pattern_mode", v)}
                  options={[{ value: "lean", label: "Careful — 3 guesses" }, { value: "plus", label: "Thorough — 5 guesses" }]} />
                <span className="u-small u-muted">{t("pattern_mode") === "plus" ? "ian@ · ian.smith@ · i.smith@ · iansmith@ · ismith@" : "ian@ · ian.smith@ · i.smith@"}</span>
              </Rung>
              <div className="u-arrow">if no guess passes ↓</div>
              <Rung n={3} on={b("use_icypeas")} onToggle={(v) => set("use_icypeas", v)} title="Ask Icypeas"
                desc={keysSet.icypeas_api_key ? "Works without a website. 1 credit, only when it finds one." : <>Not connected — <a className="u-link" href="#s-conn" onClick={jump("s-conn")}>add its key</a>.</>}>
                <label className="u-check"><input type="checkbox" checked={b("verify_icypeas_with_mf")} onChange={(e) => set("verify_icypeas_with_mf", e.target.checked)} /> Double-check what it finds (MillionVerifier)</label>
              </Rung>
              <div className="u-arrow">if Icypeas finds nothing ↓</div>
              <Rung n={4} on={b("use_anymailfinder")} onToggle={(v) => set("use_anymailfinder", v)} title="Ask Anymailfinder"
                desc={keysSet.anymailfinder_api_key ? "1 credit, only when it finds one." : <>Not connected — <a className="u-link" href="#s-conn" onClick={jump("s-conn")}>add its key</a>.</>}>
                <label className="u-check"><input type="checkbox" checked={b("verify_anymailfinder_with_mf")} onChange={(e) => set("verify_anymailfinder_with_mf", e.target.checked)} /> Double-check what it finds (MillionVerifier)</label>
              </Rung>
            </div>
            <div style={{ marginTop: 12 }}>
              <SwitchRow title="Accept “catch-all” addresses" desc="Some companies accept mail for any name, so the check cannot prove the person exists. On = more emails, but some may bounce."
                checked={b("accept_catchall")} onChange={(v) => set("accept_catchall", v)} />
            </div>
          </Card>

          <RecipesSection />

          <Card id="s-limits" title="Spending limits" sub="Across all campaigns together. Each campaign also has its own limits.">
            <div className="u-fgrid two">
              <Field label="Most leads sent to Instantly per day" hint="Match it to what your mailboxes can send.">
                <input className="u-input" type="number" min={0} aria-label="Most leads sent per day" value={caps.daily_push_cap} onChange={(e) => setCaps((x) => ({ ...x, daily_push_cap: e.target.value }))} />
              </Field>
              <Field label="Most money spent per day ($)" hint="Scheduled live runs stop when it is reached.">
                <input className="u-input" type="number" min={0} step={0.5} aria-label="Most money spent per day" value={caps.daily_spend_cap_usd} onChange={(e) => setCaps((x) => ({ ...x, daily_spend_cap_usd: e.target.value }))} />
              </Field>
            </div>
          </Card>

          <Card id="s-safety" title="Lead safety" sub="Who is never contacted, and what makes a lead wait.">
            <div className="u-fgrid two">
              <Field label="Never contact these companies" hint="Type a name, press Enter.">
                <TagList label="Companies never contacted" values={list("owned_companies")} onChange={(v) => set("owned_companies", v)} placeholder="e.g. Fabrikam" />
              </Field>
              <Field label="Never contact these websites" hint="Type a website, press Enter.">
                <TagList label="Websites never contacted" values={list("owned_domains")} onChange={(v) => set("owned_domains", v)} placeholder="e.g. fabrikam.example" />
              </Field>
            </div>
            <div style={{ marginTop: 8 }}>
              <SwitchRow title="Send ice breakers" desc="Campaigns send the line Icebreaker Studio wrote in the sheet. Off = leads go out without one."
                checked={b("use_icebreaker")} onChange={(v) => set("use_icebreaker", v)} />
              <SwitchRow title="Hold leads without an ice breaker" desc="They wait until Icebreaker Studio writes one, instead of going out without it."
                checked={b("hold_without_icebreaker")} onChange={(v) => set("hold_without_icebreaker", v)} />
              <SwitchRow title="Hold firms behind Mimecast or Proofpoint" desc="These email filters bounce cold email hard."
                checked={b("block_security_gateways")} onChange={(v) => set("block_security_gateways", v)} />
              <SwitchRow title="Never work on the same lead twice"
                desc={<>The app remembers every lead it handled ({ledger ? num(ledger.total) : "…"} so far{ledger?.pending_push ? `, ${num(ledger.pending_push)} found but not sent yet` : ""}).{" "}
                  <button type="button" className="u-link" onClick={() => setShowLeads(!showLeads)}>{showLeads ? "Hide them" : "See the latest"}</button>{" · "}
                  <button type="button" className="u-link danger" onClick={() => setForget(true)}>Forget all…</button></>}
                checked={b("use_ledger")} onChange={(v) => set("use_ledger", v)} />
              {showLeads && ledger?.recent?.length ? (
                <div className="u-scroll" style={{ marginBottom: 8 }}>
                  <table className="u-table">
                    <thead><tr><th>Company</th><th>Result</th><th>Email</th><th>Sent</th><th>When</th></tr></thead>
                    <tbody>{ledger.recent.map((r, i) => (
                      <tr key={i}><td>{r.company || "—"}</td><td>{r.status.replace(/_/g, " ")}</td><td className="u-mono">{r.email || "—"}</td><td>{r.pushed ? "yes" : "no"}</td><td className="u-small">{r.when}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : null}
              <SwitchRow title="Try again on “no email found” leads" desc="Turn on after adding a new finder or key."
                checked={b("retry_not_found")} onChange={(v) => set("retry_not_found", v)} />
              <SwitchRow title="Skip rows that already have something in “Status”" desc="Blank Status = not done yet. Off = every row is worked on, whatever its Status says."
                checked={b("strict_status")} onChange={(v) => set("strict_status", v)} />
            </div>
          </Card>

          <LoginSection />

          <details className="u-adv" id="s-adv">
            <summary>Advanced <span className="u-small u-muted" style={{ fontWeight: 400 }}>— speed, prices, test copies, the old screens</span></summary>
            <div className="u-stack">
              <Card title="Speed and retries">
                <Seg label="Speed" value={speed} onChange={(v) => { if (v !== "custom") setCfg((x) => ({ ...(x ?? {}), ...SPEEDS[v] })); }}
                  options={[{ value: "normal", label: "Normal" }, { value: "gentle", label: "Gentle (slower, fewer errors)" }, { value: "custom", label: "Your own numbers" }]} />
                <div className="u-fgrid" style={{ marginTop: 12 }}>
                  <Field label="Seconds between sends to Instantly"><input className="u-input" type="number" min={0} value={t("push_delay_seconds")} onChange={(e) => set("push_delay_seconds", e.target.value)} aria-label="Seconds between sends" /></Field>
                  <Field label="Tries when a service fails" hint="A wrong key is never retried."><input className="u-input" type="number" min={1} value={t("api_tries")} onChange={(e) => set("api_tries", e.target.value)} aria-label="Tries" /></Field>
                  <Field label="Seconds between tries"><input className="u-input" type="number" min={0} value={t("api_retry_wait")} onChange={(e) => set("api_retry_wait", e.target.value)} aria-label="Seconds between tries" /></Field>
                  <Field label="Pause between email checks (ms)"><input className="u-input" type="number" min={0} value={t("verify_delay_ms")} onChange={(e) => set("verify_delay_ms", e.target.value)} aria-label="Pause between checks" /></Field>
                  <Field label="Pause before each Icypeas lookup (s)"><input className="u-input" type="number" min={0} value={t("icypeas_throttle_seconds")} onChange={(e) => set("icypeas_throttle_seconds", e.target.value)} aria-label="Pause before Icypeas" /></Field>
                </div>
              </Card>
              <Card title="Prices" sub="Only used to estimate costs on screen — they change nothing that is charged.">
                <div className="u-fgrid">
                  <Field label="MillionVerifier, per check ($)"><input className="u-input" value={t("mv_per_verification_usd")} onChange={(e) => set("mv_per_verification_usd", e.target.value)} aria-label="MillionVerifier price" /></Field>
                  <Field label="Icypeas, per credit ($)"><input className="u-input" value={t("icypeas_usd_per_credit")} onChange={(e) => set("icypeas_usd_per_credit", e.target.value)} aria-label="Icypeas price" /></Field>
                  <Field label="Anymailfinder, per credit ($)"><input className="u-input" value={t("anymailfinder_usd_per_credit")} onChange={(e) => set("anymailfinder_usd_per_credit", e.target.value)} aria-label="Anymailfinder price" /></Field>
                  <Field label="Apollo, per credit ($)" hint="For the savings comparison only."><input className="u-input" value={t("apollo_credit_usd")} onChange={(e) => set("apollo_credit_usd", e.target.value)} aria-label="Apollo price" /></Field>
                </div>
              </Card>
              <Card title="Test with a saved copy instead of the live sheet" sub="For testing without Google access. Every screen warns while one is on. Leave empty for normal use.">
                {tabs.map((x, i) => (
                  <div key={i} className="u-filter">
                    <input className="u-input inline" aria-label="Tab name" placeholder="tab name, e.g. Practices" value={x.tab} onChange={(e) => setTabs(tabs.map((y, k) => (k === i ? { ...y, tab: e.target.value } : y)))} />
                    <input className="u-input inline u-mono" style={{ minWidth: 280, flex: 1 }} aria-label="CSV file" placeholder="C:\…\Practices.csv" value={x.path} onChange={(e) => setTabs(tabs.map((y, k) => (k === i ? { ...y, path: e.target.value } : y)))} />
                    <button type="button" className="u-x" aria-label="Remove" onClick={() => setTabs(tabs.filter((_, k) => k !== i))}>✕</button>
                  </div>
                ))}
                <button type="button" className="u-btn sm" style={{ marginTop: 8 }} onClick={() => setTabs([...tabs, { tab: "", path: "" }])}>+ Add a saved copy</button>
              </Card>
              <Card title="Old screens (V1)" sub="Only the original interface uses these. Its ice-breaker templates are edited there.">
                <div className="u-fgrid">
                  <Field label="Instantly campaign ID"><input className="u-input u-mono" value={t("instantly_campaign_id")} onChange={(e) => set("instantly_campaign_id", e.target.value.trim())} aria-label="V1 Instantly campaign ID" /></Field>
                  <Field label="Sheet tab"><input className="u-input" value={t("sheet_tab")} onChange={(e) => set("sheet_tab", e.target.value)} aria-label="V1 sheet tab" /></Field>
                  <Field label="Leads per run"><input className="u-input" type="number" value={t("max_firms")} onChange={(e) => set("max_firms", e.target.value)} aria-label="V1 leads per run" /></Field>
                </div>
                <SwitchRow title="Send V1 ice breakers through OpenAI" desc="Costs tokens and returns the same text. Needs the OpenAI key below."
                  checked={b("use_openai_echo")} onChange={(v) => set("use_openai_echo", v)} />
                <ConnRow title="OpenAI" desc="Only for the switch above." keyField="openai_api_key" cfg={cfg} setKey={set} service="openai" test={tests.openai} onTest={runTest} />
                <a className="u-btn sm" href="/legacy" style={{ marginTop: 10 }}>Open the old screens</a>
              </Card>
            </div>
          </details>
        </div>
      </div>

      <div className={dirty ? "u-savebar show" : "u-savebar"} role="status" aria-hidden={!dirty}>
        <span>You have unsaved changes</span>
        <button type="button" className="u-btn sm" onClick={() => window.location.reload()} disabled={saving}>Discard</button>
        <button type="button" className="u-btn sm primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
      </div>

      {forget ? (
        <Confirm title="Forget every lead the app has handled?" danger confirmLabel="Forget all" onConfirm={forgetAll} onClose={() => setForget(false)}
          body={<>
            <p>The next runs will work on those {ledger ? num(ledger.total) : ""} leads again — including any already sent to Instantly, unless your sheet’s Status column or Instantly’s own checks stop them.</p>
            <p className="muted">This cannot be undone.</p>
          </>} />
      ) : null}
    </div>
  );
}

/** Settings → Login. Acts at once: the password lives in data/auth.json, never in the form. */
function LoginSection() {
  const [s, setS] = useState<{ password_set: boolean; set_at: string; server_requires: boolean } | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => { getJson<typeof s>("/auth/status").then(setS).catch(() => {}); }, []);
  if (!s) return <Card id="s-login" title="Login"><Loading rows={2} /></Card>;
  const call = async (path: string, body: object, note: string) => {
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string }>(path, body);
      if (!r.ok) throw new Error(r.error || "Not saved.");
      reloadWithNote(note);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <Card id="s-login" title="Login" sub={s.password_set ? `A password is set (${s.set_at}). Every page asks for it.` : "No password: anyone who can open this address can use the app. Fine on your own computer — always set one on a server."}>
      <div className="u-fgrid">
        {s.password_set ? <Field label="Current password"><input className="u-input" type="password" autoComplete="current-password" aria-label="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field> : null}
        <Field label={s.password_set ? "New password" : "Password"} hint="At least 10 characters."><input className="u-input" type="password" autoComplete="new-password" aria-label="New password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <Field label="Same again" bad={!!again && again !== next} hint={again && again !== next ? "Does not match." : undefined}><input className="u-input" type="password" autoComplete="new-password" aria-label="Same again" value={again} onChange={(e) => setAgain(e.target.value)} /></Field>
      </div>
      {problem ? <div style={{ marginTop: 10 }}><Note tone="bad">{problem}</Note></div> : null}
      <div className="u-row" style={{ marginTop: 12 }}>
        <button type="button" className="u-btn" disabled={busy || !next || next !== again || (s.password_set && !current)}
          onClick={() => call("/auth/password", { current, new: next }, s.password_set ? "Password changed." : "Password set. The app now asks for it.")}>
          {s.password_set ? "Change password" : "Set password"}
        </button>
        {s.password_set && !s.server_requires ? (
          <button type="button" className="u-btn" disabled={busy || !current} onClick={() => call("/auth/clear", { current }, "Password removed.")}>Remove password</button>
        ) : null}
        {s.server_requires ? <span className="u-small u-muted">This server requires a login, so it cannot be removed.</span> : null}
      </div>
    </Card>
  );
}
