"use client";

/* Section 1 — Who: which leads a campaign takes. Filters read as sentences
 * ("Include leads where [Staff count] [is between] [2] and [10]"), but they save exactly the
 * shape core/rules.py expects: all / any / none blocks of {field, op, value}. */

import { Field, Step } from "@/components/u";
import { num } from "@/lib/format";
import type { CampaignCounts, CampaignRaw, Clause, RuleBlock, SortKey } from "@/lib/types";
import { FIELD_WORDS, LIST_OPS, NUM_OPS, OP_ORDER, OP_WORDS, WRITTEN_GROUP } from "@/lib/words";

export type SourceOption = { tab: string; label: string };

/** What a filter or a sort can look at: the fields the app knows (in plain words) and every
 *  other column of the source. Values are what is saved: an engine name or the column itself. */
export function fieldOptions(headers: string[], resolved: Record<string, string>) {
  // every field this source really has — the result columns too: a filter such as
  // "Final result is empty" is a normal thing to want
  const known = Object.entries(resolved)
    .filter(([f, h]) => FIELD_WORDS[f] && f !== "row_key" && headers.includes(h))
    .map(([f, h]) => ({ value: f, label: `${FIELD_WORDS[f].name} (${h.trim()})`, written: FIELD_WORDS[f].group === WRITTEN_GROUP }))
    .sort((a, b) => Number(a.written) - Number(b.written) || a.label.localeCompare(b.label));
  const used = new Set(Object.values(resolved));
  const cols = headers.filter((h) => !used.has(h)).map((h) => ({ value: h, label: h.trim() || h }));
  return { known, cols, all: new Set([...known.map((o) => o.value), ...cols.map((o) => o.value)]) };
}

/** Exported so the Finding-recipe editor builds its conditions from the SAME 17 operators
 *  and the same column dropdown — one filter UI, two places that need it. */
export function FieldSelect({ value, onChange, opts, label }: {
  value: string;
  onChange: (v: string) => void;
  opts: ReturnType<typeof fieldOptions>;
  label: string;
}) {
  // only THIS filter's own value, when the source does not have it (another source's column)
  const stray = value && !opts.all.has(value) && opts.all.size ? `${FIELD_WORDS[value]?.name ?? value} (not in this source)` : "";
  return (
    <select className="u-input inline" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {!value ? <option value="">choose…</option> : null}
      {stray ? <option value={value}>{stray}</option> : null}
      {value && !opts.all.size ? <option value={value}>{FIELD_WORDS[value]?.name ?? value}</option> : null}
      {opts.known.length ? (
        <optgroup label="Fields the app knows">
          {opts.known.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </optgroup>
      ) : null}
      {opts.cols.length ? (
        <optgroup label="Other columns">
          {opts.cols.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </optgroup>
      ) : null}
    </select>
  );
}

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : String(v ?? "").split(",").map((s) => s.trim()).filter(Boolean));

export function ValueInput({ cl, onChange }: { cl: Clause; onChange: (v: unknown) => void }) {
  const op = cl.op ?? "equals";
  if (op === "is_blank" || op === "is_not_blank") return null;
  if (op === "between") {
    const [a = 0, b = 0] = Array.isArray(cl.value) ? (cl.value as number[]) : [];
    return (
      <>
        <input className="u-input num" type="number" aria-label="From" value={a} onChange={(e) => onChange([Number(e.target.value) || 0, b])} />
        and
        <input className="u-input num" type="number" aria-label="To" value={b} onChange={(e) => onChange([a, Number(e.target.value) || 0])} />
      </>
    );
  }
  if (LIST_OPS.has(op)) {
    return (
      <input className="u-input inline" style={{ minWidth: 200 }} aria-label="Values" placeholder="a, b, c" value={asList(cl.value).join(", ")}
        onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
    );
  }
  if (NUM_OPS.has(op)) {
    return (
      <input className="u-input num" type="number" aria-label="Value" value={cl.value === undefined ? "" : String(cl.value)}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />
    );
  }
  return (
    <input className="u-input inline" aria-label="Value" placeholder={op === "matches" ? "a pattern, e.g. ^(owner|director)" : "value"}
      value={String(cl.value ?? "")} onChange={(e) => onChange(e.target.value)} />
  );
}

/** Turn an operator change into a value of the right shape, keeping what can be kept. */
export function reshape(op: string, value: unknown): unknown {
  if (op === "is_blank" || op === "is_not_blank") return undefined;
  if (op === "between") return Array.isArray(value) && value.length === 2 ? value : [0, 0];
  if (LIST_OPS.has(op)) return asList(value);
  if (NUM_OPS.has(op)) return Array.isArray(value) ? 0 : Number(value) || 0;
  return Array.isArray(value) ? value.join(", ") : value ?? "";
}

const BLOCK_WORDS: Record<RuleBlock, { title: string; add: string }> = {
  all: { title: "Include leads where all of these are true", add: "+ Add a filter" },
  any: { title: "…and at least one of these is true", add: "+ Add an “at least one of” filter" },
  none: { title: "Never include leads where", add: "+ Never include leads where…" },
};

export function WhoSection({
  c,
  set,
  sources,
  headers,
  resolved,
  counts,
  counting,
}: {
  c: CampaignRaw;
  set: (patch: Partial<CampaignRaw>) => void;
  sources: SourceOption[];
  headers: string[];
  resolved: Record<string, string>;
  counts: CampaignCounts | null;
  counting: boolean;
}) {
  const rules = c.rules ?? {};
  const order = c.order ?? [];
  const opts = fieldOptions(headers, resolved);
  const firstField = opts.known[0]?.value ?? opts.cols[0]?.value ?? "";

  const setBlock = (b: RuleBlock, list: Clause[]) => {
    const next = { ...rules };
    if (list.length) next[b] = list;
    else delete next[b];
    set({ rules: next });
  };
  const setClause = (b: RuleBlock, i: number, patch: Clause) =>
    setBlock(b, (rules[b] ?? []).map((cl, k) => (k === i ? { ...cl, ...patch } : cl)));
  const setSort = (i: number, patch: Partial<SortKey>) => set({ order: order.map((s, k) => (k === i ? { ...s, ...patch } : s)) });

  const sourceKnown = sources.some((s) => s.tab === c.tab);

  return (
    <Step n={1} id="sec-who" title="Who" question="Which leads does this campaign take?">
      <div className="u-fgrid two">
        <Field label="Lead source" hint={<>Where the leads come from. Add more on the <a className="u-link" href="/sources">Lead sources</a> page.</>}>
          <select className="u-input" aria-label="Lead source" value={c.tab ?? ""} onChange={(e) => set({ tab: e.target.value })}>
            {!sourceKnown && c.tab ? <option value={c.tab}>{c.tab}</option> : null}
            {sources.map((s) => <option key={s.tab} value={s.tab}>{s.label}</option>)}
          </select>
        </Field>
      </div>

      {(["all", "any", "none"] as RuleBlock[]).map((b) => {
        const list = rules[b] ?? [];
        if (b !== "all" && !list.length) return null;
        return (
          <div key={b} style={{ marginTop: 16 }}>
            <b className="u-ink">{BLOCK_WORDS[b].title}</b>
            {list.length === 0 ? <div className="u-small u-muted" style={{ marginTop: 6 }}>No filters yet — every lead in the source fits.</div> : null}
            {list.map((cl, i) => (
              <div className="u-filter" key={i}>
                <FieldSelect label="Field" value={cl.field ?? ""} opts={opts} onChange={(v) => setClause(b, i, { field: v })} />
                <select className="u-input inline" aria-label="Condition" value={cl.op ?? "equals"}
                  onChange={(e) => setClause(b, i, { op: e.target.value, value: reshape(e.target.value, cl.value) })}>
                  {OP_ORDER.map((o) => <option key={o} value={o}>{OP_WORDS[o]}</option>)}
                </select>
                <ValueInput cl={cl} onChange={(v) => setClause(b, i, { value: v })} />
                <button type="button" className="u-x" aria-label="Remove filter" onClick={() => setBlock(b, list.filter((_, k) => k !== i))}>✕</button>
              </div>
            ))}
          </div>
        );
      })}
      <div className="u-row" style={{ marginTop: 10 }}>
        {(["all", "any", "none"] as RuleBlock[]).map((b) => (
          <button key={b} type="button" className="u-btn sm"
            onClick={() => setBlock(b, [...(rules[b] ?? []), { field: firstField, op: "equals", value: "" }])}>
            {BLOCK_WORDS[b].add}
          </button>
        ))}
      </div>

      <div style={{ marginTop: 18 }}>
        <b className="u-ink">Best leads first</b>
        <div className="u-small u-muted">Each run takes the best leads first. The first line counts most.</div>
        {order.map((s, i) => (
          <div className="u-filter" key={i}>
            <span className="u-small u-muted">{i === 0 ? "Sort by" : "then by"}</span>
            <FieldSelect label="Sort by" value={s.field ?? ""} opts={opts} onChange={(v) => setSort(i, { field: v })} />
            {s.order?.length ? (
              <>
                <span className="u-small u-muted">in this order:</span>
                <input className="u-input inline" style={{ minWidth: 200 }} aria-label="Best first" value={s.order.join(", ")}
                  onChange={(e) => setSort(i, { order: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })} />
                <button type="button" className="u-link u-small" onClick={() => { const { order: _o, ...rest } = s; set({ order: order.map((x, k) => (k === i ? rest : x)) }); }}>
                  sort by value instead
                </button>
              </>
            ) : (
              <>
                <select className="u-input inline" aria-label="Direction" value={s.dir ?? "asc"} onChange={(e) => setSort(i, { dir: e.target.value as "asc" | "desc" })}>
                  <option value="desc">highest / Z first</option>
                  <option value="asc">lowest / A first</option>
                </select>
                <button type="button" className="u-link u-small" onClick={() => setSort(i, { order: ["best", "next"] })}>use my own order</button>
              </>
            )}
            <button type="button" className="u-x" aria-label="Remove sort" onClick={() => set({ order: order.filter((_, k) => k !== i) })}>✕</button>
          </div>
        ))}
        <button type="button" className="u-btn sm" style={{ marginTop: 8 }} onClick={() => set({ order: [...order, { field: firstField, dir: "desc" }] })}>
          {order.length ? "+ Then sort by…" : "+ Sort the leads"}
        </button>
      </div>

      <div className="u-countbox" aria-live="polite">
        {counts?.error ? (
          <span className="u-muted">{counts.error}</span>
        ) : counts ? (
          <>
            <span><b>{num(counts.matched)}</b> leads fit</span>
            <span><b>{num(counts.not_contacted)}</b> never contacted</span>
            <span className="u-muted">Each run takes the best {num(counts.per_run)}.{counting ? " Updating…" : ""}</span>
          </>
        ) : (
          <span className="u-muted">{counting ? "Counting the leads…" : "Counts appear here."}</span>
        )}
      </div>
    </Step>
  );
}
