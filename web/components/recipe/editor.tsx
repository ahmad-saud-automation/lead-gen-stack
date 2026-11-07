"use client";

/* The Finding-recipe editor (docs/RECIPE-BUILDER.md §2, Screen A).
 *
 * A recipe is its OWN page on purpose: one recipe serves several campaigns, so saving it
 * here changes all of them, and that must never be a side effect of pressing "Save
 * campaign" on one lane. The page says out loud which campaigns it changes.
 *
 * Every field is a setting from §1b–1f. The engine already decides which ways a row can
 * use and why (core/recipe.plan_for_row), so this page never re-implements that rule —
 * "Try on 10 rows" asks the engine and shows its answer. */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FieldSelect, ValueInput, fieldOptions, reshape } from "@/components/campaign/who";
import { Confirm } from "@/components/modal";
import { Card, Empty, Field, Note, PageHead, Pill, Switch, SwitchRow } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { usePointerDrag } from "@/lib/drag";
import { money, num } from "@/lib/format";
import { goWithNote, reloadWithNote } from "@/lib/nav";
import type {
  Clause, RecipeDetail, RecipePerson, RecipeRaw, RecipeSaved, RecipeTry, RecipeWay, RuleBlock,
} from "@/lib/types";
import {
  METHOD_ORDER, METHOD_WORDS, OP_ORDER, OP_WORDS, PATTERN_WORDS, STOP_WORDS, VERIFY_WORDS,
  WRITE_WHEN_WORDS, methodWord, personSentence, pickName,
} from "@/lib/words";

type Opts = ReturnType<typeof fieldOptions>;

/** The name columns as an editable list.
 *
 * ⛔ Empty slots are KEPT. Filtering them out made "+ Pick the name column" do nothing at
 * all on a new recipe: the new slot starts blank, so a filter dropped it again before it
 * could ever be rendered. Blanks are dropped when the file is saved, not while editing. */
const asCols = (v: string | string[] | undefined): string[] =>
  Array.isArray(v) ? v : v ? [v] : [];

/** first / last from a full name, the same way core/emailgen.derive_name does. */
function nameParts(full: string) {
  const words = String(full || "").trim().toLowerCase().replace(/[^a-z ]/g, " ").split(/\s+/).filter(Boolean);
  const titles = new Set(["mr", "mrs", "ms", "miss", "dr", "prof", "sir", "md", "mst"]);
  while (words.length && titles.has(words[0])) words.shift();
  return { first: words[0] ?? "", last: words.length > 1 ? words[words.length - 1] : "" };
}

/* ── one condition ("only try this person if …") ─────────────────────── */

function Condition({
  rules, onChange, opts, addLabel, empty,
}: {
  rules: Partial<Record<RuleBlock, Clause[]>> | undefined;
  onChange: (r: Partial<Record<RuleBlock, Clause[]>>) => void;
  opts: Opts;
  addLabel: string;
  empty: string;
}) {
  const list = rules?.all ?? [];
  const first = opts.known[0]?.value ?? opts.cols[0]?.value ?? "";
  const setList = (next: Clause[]) => onChange(next.length ? { all: next } : {});
  return (
    <>
      {list.length === 0 ? <div className="u-small u-muted">{empty}</div> : null}
      {list.map((cl, i) => (
        <div className="u-filter" key={i}>
          <FieldSelect label="Column" value={cl.field ?? ""} opts={opts}
            onChange={(v) => setList(list.map((x, k) => (k === i ? { ...x, field: v } : x)))} />
          <select className="u-input inline" aria-label="Condition" value={cl.op ?? "equals"}
            onChange={(e) => setList(list.map((x, k) => (k === i ? { ...x, op: e.target.value, value: reshape(e.target.value, x.value) } : x)))}>
            {OP_ORDER.map((o) => <option key={o} value={o}>{OP_WORDS[o]}</option>)}
          </select>
          <ValueInput cl={cl} onChange={(v) => setList(list.map((x, k) => (k === i ? { ...x, value: v } : x)))} />
          <button type="button" className="u-x" aria-label="Remove condition" onClick={() => setList(list.filter((_, k) => k !== i))}>✕</button>
        </div>
      ))}
      <button type="button" className="u-btn sm" style={{ marginTop: 8 }}
        onClick={() => setList([...list, { field: first, op: "is_not_blank" }])}>{addLabel}</button>
    </>
  );
}

/* ── one way of finding a person ─────────────────────────────────────── */

function WayRow({
  w, n, onChange, onRemove, canDrop, hasWebsite,
}: {
  w: RecipeWay;
  n: number;
  onChange: (patch: Partial<RecipeWay>) => void;
  onRemove: () => void;
  canDrop: boolean;
  hasWebsite: boolean;
}) {
  const method = String(w.method || "");
  const info = METHOD_WORDS[method];
  // the engine greys a way out per ROW; here we can only warn about the whole source
  const noSite = hasWebsite === false && (method === "guess_patterns" || method === "icypeas_domain");
  return (
    <div className="u-recway">
      <span className="u-recway-n">{n}</span>
      <div className="u-recway-body">
        <div className="u-fgrid two">
          <Field label="Way to find them" hint={info?.hint}>
            <select className="u-input" aria-label={`Way ${n}`} value={method} onChange={(e) => onChange({ method: e.target.value })}>
              {METHOD_ORDER.map((m) => <option key={m} value={m}>{METHOD_WORDS[m].name}</option>)}
            </select>
          </Field>
          <Field label="Check the address" hint={VERIFY_WORDS[String(w.verify || "must_pass")]?.hint}>
            <select className="u-input" aria-label={`Check for way ${n}`} value={String(w.verify || "must_pass")} onChange={(e) => onChange({ verify: e.target.value })}>
              {Object.entries(VERIFY_WORDS).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
            </select>
          </Field>
        </div>
        {method === "guess_patterns" ? (
          <div className="u-fgrid" style={{ marginTop: 8 }}>
            <Field label="How many formats to try" hint="Each format is one check, so “thorough” costs about twice as much.">
              <select className="u-input" aria-label={`Formats for way ${n}`} value={w.patterns || "careful"} onChange={(e) => onChange({ patterns: e.target.value as "careful" | "thorough" })}>
                {Object.entries(PATTERN_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
          </div>
        ) : null}
        {method === "icypeas_company" ? (
          <div style={{ marginTop: 8 }}>
            <SwitchRow title="Mark it “check by hand” if the website does not match the firm"
              desc="Asking by company name can return an address at a different business. On = the address is still written, but it is never sent until you look at it."
              checked={w.note_if_domain_mismatch !== false} onChange={(v) => onChange({ note_if_domain_mismatch: v })} />
          </div>
        ) : null}
        {noSite ? (
          <div className="u-small u-badmark" style={{ marginTop: 6 }}>
            This source has no website column, so this way will be skipped on every row.
          </div>
        ) : null}
      </div>
      {canDrop ? <button type="button" className="u-x" aria-label={`Remove way ${n}`} onClick={onRemove}>✕</button> : null}
    </div>
  );
}

/* ── one person rung ────────────────────────────────────────────────── */

function PersonRow({
  p, i, total, open, onOpen, onChange, onRemove, onCopy, onMove, opts, sample, resolved, drag, written,
}: {
  p: RecipePerson;
  i: number;
  total: number;
  open: boolean;
  onOpen: () => void;
  onChange: (patch: Partial<RecipePerson>) => void;
  onRemove: () => void;
  onCopy: () => void;
  onMove: (to: number) => void;
  opts: Opts;
  sample: Record<string, string>;
  resolved: Record<string, string>;
  drag: ReturnType<typeof usePointerDrag<number>>;
  /** the columns this recipe writes — never useful as a "same person as" comparison */
  written: Set<string>;
}) {
  const cols = asCols(p.name_from);
  const ways = p.how ?? [];
  // Columns offerable as "the same person as". `opts.cols` is only the UNMAPPED headers, so
  // on its own it hides every column the field map claims — `Contact Name` among them, which
  // is exactly the one his "only if it is a director's address" rule has to compare against.
  // `opts.known` carries the mapped ones, valued by engine field name, which `_read_col`
  // resolves the same way. Written columns are never a sensible comparison.
  // ⛔ A mapped option's value is the ENGINE FIELD name (`status`), while `written` holds the
  // real HEADERS the recipe writes (`Status`). So `written.has(o.value)` never matched and the
  // result columns were offered as a "same person as" comparison. Resolve through `resolved`.
  const personCols = [...opts.known.filter((o) => !o.written), ...opts.cols]
    .filter((o) => !written.has(o.value) && !written.has(resolved[o.value] ?? ""));
  const siteHeader = resolved.website || "";
  // whether the SOURCE has a website column at all. Whether a given ROW has one is the
  // engine's answer, and "Try on 10 rows" shows it. Unknown (no sheet read yet) = no warning.
  const hasWebsite = Object.keys(resolved).length === 0 ? true : !!siteHeader;

  // a real example from his own sheet, as the design asks for
  const example = useMemo(() => {
    const nameCol = cols.find((c) => pickName(sample[c], p.name_pick));
    const who = nameCol ? pickName(sample[nameCol], p.name_pick) : "";
    if (p.address_from && sample[p.address_from]) return `${sample[p.address_from]} — straight from ${p.address_from}`;
    if (!who) return "";
    const dom = String(sample[siteHeader] || "").replace(/^https?:\/\//i, "").replace(/^www\./i, "").split("/")[0];
    const { first, last } = nameParts(who);
    if (!dom) return `${who} — no website on this row, so Icypeas would be asked by company name`;
    if (!first) return who;
    return `${who} → ${last ? `${first}.${last}` : first}@${dom}`;
  }, [cols, p.address_from, p.name_pick, sample, siteHeader]);

  return (
    <div className={open ? "u-recpers open" : "u-recpers"} data-drop="rung" data-index={i}>
      <div className="u-recpers-head">
        <button type="button" className="u-recgrip" aria-label={`Move ${p.label || `person ${i + 1}`}`}
          onPointerDown={(e) => drag.start(e, i, p.label || `Person ${i + 1}`)}>⋮⋮</button>
        <span className="u-num sm">{i + 1}</span>
        <button type="button" className="u-recpers-open" aria-expanded={open}
          onClick={() => { if (!drag.wasDrag()) onOpen(); }}>
          <b className="u-ink">{p.label || `Person ${i + 1}`}</b>
          <span className="u-small u-muted">{personSentence(p)}</span>
        </button>
        <div className="u-row" style={{ gap: 6 }}>
          <button type="button" className="u-btn sm" onClick={onCopy}>Copy</button>
          <button type="button" className="u-btn sm" disabled={i === 0} onClick={() => onMove(i - 1)} aria-label="Move up">↑</button>
          <button type="button" className="u-btn sm" disabled={i === total - 1} onClick={() => onMove(i + 1)} aria-label="Move down">↓</button>
          <button type="button" className="u-x" aria-label={`Remove ${p.label || `person ${i + 1}`}`} onClick={onRemove}>✕</button>
        </div>
      </div>

      {open ? (
        <div className="u-recpers-body">
          <div className="u-fgrid two">
            <Field label="What do you call this step?" hint="Shown in Activity and written into your “Found For” column.">
              <input className="u-input" aria-label="Label" value={p.label ?? ""} placeholder="1st director"
                onChange={(e) => onChange({ label: e.target.value })} />
            </Field>
          </div>

          <div style={{ marginTop: 12 }}>
            <b className="u-ink">Which column holds this person’s name?</b>
            <div className="u-small u-muted">Pick more than one and the app uses the first that is filled in.</div>
            {cols.map((c, k) => (
              <div className="u-filter" key={k}>
                <span className="u-small u-muted">{k === 0 ? "name from" : "or, if empty,"}</span>
                <FieldSelect label={`Name column ${k + 1}`} value={c} opts={opts}
                  onChange={(v) => onChange({ name_from: cols.map((x, j) => (j === k ? v : x)) })} />
                <button type="button" className="u-x" aria-label="Remove column" onClick={() => onChange({ name_from: cols.filter((_, j) => j !== k) })}>✕</button>
              </div>
            ))}
            <button type="button" className="u-btn sm" style={{ marginTop: 8 }}
              onClick={() => onChange({ name_from: [...cols, opts.cols[0]?.value ?? ""] })}>
              {cols.length ? "+ Then try another column" : "+ Pick the name column"}
            </button>
            {cols.length ? (
              <div style={{ marginTop: 12 }}>
                <div className="u-small u-muted">
                  Some columns hold several names in one cell, separated by commas
                  (“Jane Smith, John Brown”). Say which one this step is.
                </div>
                <div className="u-filter">
                  <span className="u-small u-muted">take</span>
                  <select className="u-input" aria-label="Which name in the cell"
                    value={p.name_pick ?? "whole"}
                    onChange={(e) => onChange({ name_pick: e.target.value })}>
                    <option value="whole">the whole cell</option>
                    <option value="1st">the 1st name in the cell</option>
                    <option value="2nd">the 2nd name in the cell</option>
                    <option value="3rd">the 3rd name in the cell</option>
                  </select>
                </div>
                {p.name_pick && p.name_pick !== "whole" ? (
                  <div className="u-small u-muted">
                    A row whose cell does not go that far offers nobody for this step, and the
                    app moves on to the next one.
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="u-fgrid two" style={{ marginTop: 14 }}>
            <Field label="…or use the address already in this column" hint="Leave empty to search for them. With a column picked, nothing is searched — that address is used as it is.">
              <select className="u-input" aria-label="Address column" value={p.address_from ?? ""}
                onChange={(e) => onChange({ address_from: e.target.value })}>
                <option value="">— search for them —</option>
                {opts.cols.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                {opts.known.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
          </div>

          {example ? (
            <div className="u-example" aria-live="polite">
              <span className="lbl">From your sheet’s first row</span>
              <code>{example}</code>
            </div>
          ) : null}

          <div style={{ marginTop: 14 }}>
            <b className="u-ink">Only try this person if…</b>
            <div className="u-small u-muted">Leave empty to always try them.</div>
            <Condition rules={p.only_if} onChange={(r) => onChange({ only_if: r })} opts={opts}
              addLabel="+ Add a condition" empty="No condition — this person is always tried." />
          </div>

          <div style={{ marginTop: 14 }}>
            <b className="u-ink">Only try them if they ARE the same person as…</b>
            <div className="u-small u-muted">
              Leave empty for anybody. Use it when the row already holds an address and it is
              only worth using if it belongs to a director — tick the director columns here,
              and someone else’s address is left alone.
            </div>
            <div className="u-row" style={{ marginTop: 6, gap: 16, flexWrap: "wrap" }}>
              {personCols.filter((o) => !(p.never_if_same_as ?? []).includes(o.value)).map((o) => {
                const on = (p.only_if_same_as ?? []).includes(o.value);
                return (
                  <label key={o.value} className="u-check">
                    <input type="checkbox" checked={on}
                      onChange={(e) => onChange({
                        only_if_same_as: e.target.checked
                          ? [...(p.only_if_same_as ?? []), o.value]
                          : (p.only_if_same_as ?? []).filter((x) => x !== o.value),
                      })} />
                    {o.label}
                  </label>
                );
              })}
            </div>
            {(p.only_if_same_as ?? []).length && !asCols(p.name_from).length ? (
              <div className="u-small u-bad">
                Pick the column holding this person’s name above, or there is nobody to compare
                and every row would be skipped.
              </div>
            ) : null}
          </div>

          <div style={{ marginTop: 14 }}>
            <b className="u-ink">Skip them if they are the same person as…</b>
            <div className="u-small u-muted">Stops you emailing the director who left, or someone you have already written to.</div>
            <div className="u-row" style={{ marginTop: 6, gap: 16, flexWrap: "wrap" }}>
              {personCols.filter((o) => !(p.only_if_same_as ?? []).includes(o.value)).map((o) => {
                const on = (p.never_if_same_as ?? []).includes(o.value);
                return (
                  <label key={o.value} className="u-check">
                    <input type="checkbox" checked={on}
                      onChange={(e) => onChange({
                        never_if_same_as: e.target.checked
                          ? [...(p.never_if_same_as ?? []), o.value]
                          : (p.never_if_same_as ?? []).filter((x) => x !== o.value),
                      })} />
                    {o.label}
                  </label>
                );
              })}
            </div>
          </div>

          <div style={{ marginTop: 18 }}>
            <b className="u-ink">Ways to find them, in order</b>
            <div className="u-small u-muted">The app tries these from the top and stops as soon as one works.</div>
            {ways.length === 0 ? <div className="u-small u-badmark" style={{ marginTop: 6 }}>Pick at least one way, or this person can never be found.</div> : null}
            {ways.map((w, k) => (
              <WayRow key={k} w={w} n={k + 1} canDrop={ways.length > 1} hasWebsite={hasWebsite}
                onChange={(patch) => onChange({ how: ways.map((x, j) => (j === k ? { ...x, ...patch } : x)) })}
                onRemove={() => onChange({ how: ways.filter((_, j) => j !== k) })} />
            ))}
            <button type="button" className="u-btn sm" style={{ marginTop: 8 }}
              onClick={() => onChange({ how: [...ways, { method: "icypeas_domain", verify: "must_pass" }] })}>
              + Then try another way
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ── the page ───────────────────────────────────────────────────────── */

export function RecipeEditor({ id }: { id: string }) {
  const [d, setD] = useState<RecipeDetail | null>(null);
  const [r, setR] = useState<RecipeRaw | null>(null);
  const savedJson = useRef("");
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [tryout, setTryout] = useState<RecipeTry | null>(null);
  const [trying, setTrying] = useState(false);
  const [confirm, setConfirm] = useState("");

  useEffect(() => {
    getJson<RecipeDetail>("/recipes/detail", { id })
      .then((v) => {
        if (v.error) throw new Error(v.error);
        setD(v);
        setR(structuredClone(v.recipe));
        savedJson.current = JSON.stringify(v.recipe);
        if ((v.recipe.people ?? []).length === 1) setOpen(0);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const dirty = useMemo(() => !!r && JSON.stringify(r) !== savedJson.current, [r]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const people = r?.people ?? [];
  const setPeople = useCallback((next: RecipePerson[]) => setR((x) => (x ? { ...x, people: next } : x)), []);

  const drag = usePointerDrag<number>((from, t) => {
    if (t.kind !== "rung" || t.index < 0 || t.index === from) return;
    const next = [...people];
    const [moved] = next.splice(from, 1);
    next.splice(t.index, 0, moved);
    setPeople(next);
    setOpen(null);
  });

  if (error || !r || !d) {
    return (
      <div className="u-page">
        <PageHead title="Finding recipe" back={{ href: "/settings#s-recipes", label: "Settings" }} />
        {error ? <ErrorBox title="This recipe could not be loaded" detail={error} /> : <div className="u-card"><Loading rows={8} /></div>}
      </div>
    );
  }

  const set = (patch: Partial<RecipeRaw>) => setR((x) => (x ? { ...x, ...patch } : x));
  const setIn = <K extends "stop" | "write" | "limits">(key: K, patch: NonNullable<RecipeRaw[K]>) =>
    setR((x) => (x ? { ...x, [key]: { ...(x[key] ?? {}), ...patch } } : x));

  const opts = fieldOptions(d.headers, d.resolved);
  const write = r.write ?? {};
  const limits = r.limits ?? {};
  const stop = r.stop ?? {};
  const users = d.used_by ?? [];

  const movePerson = (from: number, to: number) => {
    if (to < 0 || to >= people.length) return;
    const next = [...people];
    const [m] = next.splice(from, 1);
    next.splice(to, 0, m);
    setPeople(next);
    setOpen(to);
  };

  const save = async () => {
    setSaving(true);
    setIssues([]);
    try {
      const res = await postJson<RecipeSaved>("/recipes/save", { recipe: r });
      if (!res.ok) {
        setIssues(res.issues ?? ["The engine did not save it."]);
        setSaving(false);
        return;
      }
      reloadWithNote(users.length
        ? `${r.name} saved. ${users.length} campaign${users.length > 1 ? "s" : ""} now use${users.length > 1 ? "" : "s"} it.`
        : `${r.name} saved.`);
    } catch (e) {
      setIssues([e instanceof Error ? e.message : String(e)]);
      setSaving(false);
    }
  };

  const tryIt = async () => {
    setTrying(true);
    setTryout(null);
    try {
      const res = await postJson<RecipeTry>("/recipes/preview", { recipe: r, tab: d.tab, limit: 10 });
      setTryout(res);
    } catch (e) {
      setTryout({ error: e instanceof Error ? e.message : String(e) } as RecipeTry);
    } finally {
      setTrying(false);
    }
  };

  const remove = async () => {
    setConfirm("");
    try {
      const res = await postJson<RecipeSaved>("/recipes/delete", { id });
      if (!res.ok) throw new Error((res.issues ?? []).join(" · "));
      goWithNote("/settings#s-recipes", `${r.name} deleted.`);
    } catch (e) {
      setIssues([e instanceof Error ? e.message : String(e)]);
    }
  };

  const WRITE_FIELDS: [keyof typeof write, string, string][] = [
    ["email_to", "The address it found", "The one that passed the check."],
    ["person_to", "Who it belongs to", "Their name and which step found them."],
    ["method_to", "How it was found", "Guessed, Icypeas, or your own column — plus the check result."],
    ["status_to", "What happened", "Found · not found · skipped · check by hand."],
  ];

  return (
    <div className="u-page">
      <PageHead
        back={{ href: "/settings#s-recipes", label: "Settings" }}
        title={<span className="u-row" style={{ gap: 12 }}>{r.name || id}
          {users.length ? <Pill tone="live">used by {users.length}</Pill> : <Pill>not used yet</Pill>}</span>}
        sub={<>Who this app emails, and in what order. {r.updated ? `Last changed ${r.updated}. ` : ""}
          {users.length
            ? <>Saving changes <b className="u-ink">{users.map((u) => u.name || u.id).join(", ")}</b>.</>
            : <>No campaign uses it yet — pick it on a campaign’s <Link className="u-link" href="/campaigns">Campaigns</Link> page.</>}</>}
        actions={<button type="button" className="u-btn primary" onClick={save} disabled={!dirty || saving}>{saving ? "Saving…" : "Save recipe"}</button>}
      />

      {issues.length ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not saved" detail={issues.join(" · ")} /></div> : null}
      {!d.sheet_check.ok ? (
        <div style={{ marginBottom: 14 }}>
          <Note tone="bad">{d.sheet_check.blocking.join(" · ")}</Note>
        </div>
      ) : null}
      {d.sheet_check.warnings.length ? (
        <div style={{ marginBottom: 14 }}><Note tone="warn">{d.sheet_check.warnings.join(" · ")}</Note></div>
      ) : null}

      <div className="u-stack">
        <Card title="Who to email, in order"
          sub="The app tries the first person. If no address passes the check, it moves to the next.">
          {d.headers.length === 0 ? (
            <div style={{ marginBottom: 12 }}>
              <Note tone="warn">
                No campaign uses this recipe yet, so the app does not know your column names and the
                dropdowns below are empty. Open a campaign, pick this recipe under
                <b> How it finds emails</b>, save, then come back — the columns of its lead source
                will be here.
              </Note>
            </div>
          ) : null}
          {people.length === 0 ? (
            <Empty title="Nobody to try yet">
              <p>Add the first person — usually the 1st director — and pick the column that holds their name.</p>
              <button type="button" className="u-btn primary" style={{ marginTop: 10 }}
                onClick={() => { setPeople([{ label: "1st director", name_from: "", how: [{ method: "guess_patterns", patterns: "careful", verify: "must_pass" }] }]); setOpen(0); }}>
                Add the first person
              </button>
            </Empty>
          ) : (
            <div className="u-recladder">
              {people.map((p, i) => (
                <PersonRow key={i} p={p} i={i} total={people.length} open={open === i}
                  onOpen={() => setOpen(open === i ? null : i)}
                  onChange={(patch) => setPeople(people.map((x, k) => (k === i ? { ...x, ...patch } : x)))}
                  onRemove={() => { setPeople(people.filter((_, k) => k !== i)); setOpen(null); }}
                  onCopy={() => { const next = [...people]; next.splice(i + 1, 0, structuredClone(p)); setPeople(next); setOpen(i + 1); }}
                  onMove={(to) => movePerson(i, to)}
                  opts={opts} sample={d.sample ?? {}} resolved={d.resolved ?? {}} drag={drag}
                  written={new Set([write.email_to, write.person_to, write.method_to, write.status_to].filter(Boolean) as string[])} />
              ))}
            </div>
          )}
          {people.length ? (
            <button type="button" className="u-btn" style={{ marginTop: 12 }}
              onClick={() => { setPeople([...people, { label: `Person ${people.length + 1}`, name_from: "", how: [{ method: "guess_patterns", patterns: "careful", verify: "must_pass" }] }]); setOpen(people.length); }}>
              + Add person
            </button>
          ) : null}
        </Card>

        <Card title="When to stop" sub="How hard the app works on one row before it gives up.">
          <div className="u-fgrid two">
            <Field label="Stop when" hint="“Keep the best” costs more: it tries everyone even after one works.">
              <select className="u-input" aria-label="Stop when" value={stop.stop_when || "first_pass"}
                onChange={(e) => setIn("stop", { stop_when: e.target.value })}>
                {Object.entries(STOP_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ marginTop: 12 }}>
            <b className="u-ink">Skip the whole row if…</b>
            <div className="u-small u-muted">The row is left completely alone — nothing is searched, nothing is written.</div>
            <Condition rules={stop.skip_row_if} onChange={(v) => setIn("stop", { skip_row_if: v })} opts={opts}
              addLabel="+ Add a skip rule" empty="No skip rule — every row this campaign takes is worked on." />
          </div>
          <div style={{ marginTop: 12 }}>
            <SwitchRow title="Fill as many leads as possible"
              desc="If nothing passed the check, the best real address found is still written, marked “failed the check”. It can never be sent — it is there so you can look at it by hand. A guess that failed is never written."
              checked={!!stop.last_resort} onChange={(v) => setIn("stop", { last_resort: v })} />
          </div>
        </Card>

        <Card title="Write the result to" sub="These are the only columns this app may ever write. Everything else on your sheet is read-only to it.">
          <div className="u-fgrid two">
            {WRITE_FIELDS.map(([key, label, hint]) => (
              <Field key={key} label={label} hint={hint}
                bad={d.sheet_check.missing_write.includes(String(write[key] ?? ""))}>
                <select className="u-input" aria-label={label} value={String(write[key] ?? "")}
                  onChange={(e) => setIn("write", { [key]: e.target.value })}>
                  <option value="">— choose a column —</option>
                  {d.headers.map((h) => <option key={h} value={h}>{h.trim() || h}</option>)}
                  {write[key] && !d.headers.includes(String(write[key])) ? <option value={String(write[key])}>{String(write[key])} (not in this sheet)</option> : null}
                </select>
              </Field>
            ))}
            <Field label="When to write" hint="“Straight away” marks a row the moment it is done, so nobody is worked on twice.">
              <select className="u-input" aria-label="When to write" value={write.write_when || "always"}
                onChange={(e) => setIn("write", { write_when: e.target.value })}>
                {Object.entries(WRITE_WHEN_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ marginTop: 12 }}>
            <Note>Your other columns are safe: this recipe can only write <b>{[write.email_to, write.person_to, write.method_to, write.status_to].filter(Boolean).join(", ")}</b>.</Note>
          </div>
        </Card>

        <Card title="Limits" sub="This recipe’s own ceilings. A campaign’s limits still apply too — whichever is smaller wins.">
          <div className="u-fgrid">
            <Field label="Rows per run" hint="How many rows one run of this recipe works on.">
              <input className="u-input" type="number" min={1} aria-label="Rows per run" value={limits.per_run ?? 30}
                onChange={(e) => setIn("limits", { per_run: Number(e.target.value) || 0 })} />
            </Field>
            <Field label="Rows per day" hint="0 = use the campaign’s own daily limit.">
              <input className="u-input" type="number" min={0} aria-label="Rows per day" value={limits.per_day ?? 0}
                onChange={(e) => setIn("limits", { per_day: Number(e.target.value) || 0 })} />
            </Field>
            <Field label="Stop after spending ($)" hint="0 = use the limit in Settings.">
              <input className="u-input" type="number" min={0} step={0.5} aria-label="Stop after spending" value={limits.daily_spend_cap_usd ?? 0}
                onChange={(e) => setIn("limits", { daily_spend_cap_usd: Number(e.target.value) || 0 })} />
            </Field>
          </div>
          <div style={{ marginTop: 10 }}>
            <SwitchRow title="Search the same person only once"
              desc="A person at a firm is searched once, even if that firm appears on two different tabs. Saves paying twice for the same answer."
              checked={limits.search_same_person_once !== false} onChange={(v) => setIn("limits", { search_same_person_once: v })} />
          </div>
        </Card>

        {/* ── Try on 10 rows: the free preview ── */}
        <Card title="Try it on 10 rows" sub="Free. No key is used, no credit is spent, nothing is written to your sheet.">
          {!d.tab ? (
            <Note tone="warn">No campaign uses this recipe yet, so there are no real rows to try it on. Pick it on a campaign first.</Note>
          ) : (
            <>
              <div className="u-row">
                <button type="button" className="u-btn primary" onClick={tryIt} disabled={trying}>
                  {trying ? "Reading your sheet…" : "Try on 10 rows"}
                </button>
                <span className="u-small u-muted">Uses the next 10 rows of <b className="u-ink">{d.tab.trim()}</b>{dirty ? " — your unsaved changes included" : ""}.</span>
              </div>

              {tryout?.error ? <div style={{ marginTop: 12 }}><ErrorBox title="Could not try it" detail={tryout.error} /></div> : null}

              {tryout && !tryout.error ? (
                <div style={{ marginTop: 14 }}>
                  <div className="u-countbox" aria-live="polite">
                    <span><b>{num(tryout.with_someone)}</b> of {num(tryout.tried)} rows have somebody to try</span>
                    <span><b>{num(tryout.with_nobody)}</b> have nobody</span>
                    <span>at most <b>{num(tryout.max_checks)}</b> email checks</span>
                    <span>at most <b>{num(tryout.max_credits)}</b> Icypeas credits</span>
                    <span>about <b>{money(tryout.max_cost_usd)}</b> at most</span>
                  </div>
                  <p className="u-small u-muted" style={{ marginTop: 6 }}>{tryout.note}</p>

                  <div className="u-tryrows">
                    {tryout.rows.map((row, i) => (
                      <div className={row.people.length ? "u-tryrow" : "u-tryrow none"} key={i}>
                        <div className="u-tryrow-head">
                          <b className="u-ink">{row.company || row.lead_id || `row ${i + 1}`}</b>
                          <span className="u-small u-muted">{row.website || "no website"}</span>
                          <span className="u-small u-muted">
                            {row.max_checks} check{row.max_checks === 1 ? "" : "s"}
                            {row.max_credits ? ` · ${row.max_credits} credit${row.max_credits === 1 ? "" : "s"}` : ""}
                          </span>
                        </div>
                        {row.skip ? (
                          <div className="u-small u-muted">Skipped — {row.why}</div>
                        ) : row.people.length === 0 ? (
                          <div className="u-small u-badmark">{row.why}</div>
                        ) : (
                          <ol className="u-trypeople">
                            {row.people.map((p, k) => (
                              <li key={k}>
                                <b className="u-ink">{p.label}</b>: {p.name || p.address || "—"}
                                {p.from ? <span className="u-small u-muted"> (from {p.from})</span> : null}
                                <div className="u-waychips">
                                  {p.ways.map((w, j) => (
                                    <span key={j} className={w.ok ? "u-recchip" : "u-recchip off"} title={w.ok ? VERIFY_WORDS[w.verify]?.name : w.why}>
                                      {methodWord(w.method)}{w.ok ? "" : " — skipped"}
                                    </span>
                                  ))}
                                </div>
                              </li>
                            ))}
                          </ol>
                        )}
                        {row.dropped.length ? (
                          <details className="u-small u-muted" style={{ marginTop: 4 }}>
                            <summary>{row.dropped.length} not tried</summary>
                            <ul>{row.dropped.map((x, k) => <li key={k}>{x.label}: {x.why}</li>)}</ul>
                          </details>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </Card>

        <details className="u-adv">
          <summary>Advanced <span className="u-small u-muted" style={{ fontWeight: 400 }}>— name, note, delete</span></summary>
          <div className="u-stack">
            <Card title="Name and note">
              <div className="u-fgrid two">
                <Field label="Recipe name">
                  <input className="u-input" aria-label="Recipe name" value={r.name ?? ""} onChange={(e) => set({ name: e.target.value })} />
                </Field>
                <Field label="Why this recipe exists" hint="One line, for when you come back to it in six months.">
                  <input className="u-input" aria-label="Note" value={r.note ?? ""} onChange={(e) => set({ note: e.target.value })} />
                </Field>
                <Field label="Internal ID" hint="Fixed. Campaigns point at this.">
                  <div className="u-mono" style={{ paddingTop: 8 }}>{r.id}</div>
                </Field>
              </div>
              <div className="u-row" style={{ marginTop: 16 }}>
                <button type="button" className="u-btn danger" onClick={() => setConfirm("delete")}
                  disabled={users.length > 0} title={users.length ? "Point those campaigns at another recipe first" : undefined}>
                  Delete recipe…
                </button>
                {users.length ? <span className="u-small u-muted">Used by {users.map((u) => u.name || u.id).join(", ")}.</span> : null}
              </div>
            </Card>
          </div>
        </details>
      </div>

      <div className={dirty ? "u-savebar show" : "u-savebar"} role="status" aria-hidden={!dirty}>
        <span>You have unsaved changes{users.length ? ` — saving changes ${users.length} campaign${users.length > 1 ? "s" : ""}` : ""}</span>
        <button type="button" className="u-btn sm" onClick={() => { setR(JSON.parse(savedJson.current)); setIssues([]); }} disabled={saving}>Discard</button>
        <button type="button" className="u-btn sm primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save recipe"}</button>
      </div>

      {confirm === "delete" ? (
        <Confirm title={`Delete “${r.name}”?`} danger confirmLabel="Delete it" onConfirm={remove} onClose={() => setConfirm("")}
          body={<p>The recipe file is removed. No campaign uses it, so nothing stops working. Leads already found are not affected.</p>} />
      ) : null}
    </div>
  );
}
