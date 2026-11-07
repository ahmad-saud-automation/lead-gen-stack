"use client";

/* Advanced → Extra info sent to Instantly. Each row is one {{variable}} for Instantly emails.
 * Saved exactly as the engine's label table (core/instantly.py): {send_as, type, source,
 * value, fallback, omit_if_blank}. A column source may be a LIST of columns (first one with a
 * value wins) — that is kept intact and shown as such, never flattened. */

import { usePointerDrag } from "@/lib/drag";
import type { LabelSpec } from "@/lib/types";

const DERIVED_WORDS: Record<string, string> = { seniority_tier: "Seniority tier", size_band: "Company size band" };
const derivedWord = (d: string) => DERIVED_WORDS[d] ?? d.replace(/_/g, " ");

/** The value a row sends, as one select value: "col:<header>", "list:<json>", "derived:<name>", "fixed". */
function fromValue(l: LabelSpec): string {
  if (l.type === "fixed") return "fixed";
  if (l.type === "derived") return `derived:${String(l.source ?? "")}`;
  if (Array.isArray(l.source)) return `list:${JSON.stringify(l.source)}`;
  return `col:${String(l.source ?? "")}`;
}

function applyFrom(l: LabelSpec, v: string): LabelSpec {
  if (v === "fixed") return { ...l, type: "fixed", source: undefined, value: l.value ?? "" };
  if (v.startsWith("derived:")) return { ...l, type: "derived", source: v.slice(8), value: undefined };
  if (v.startsWith("list:")) return { ...l, type: "column", source: JSON.parse(v.slice(5)), value: undefined };
  return { ...l, type: "column", source: v.slice(4), value: undefined };
}

type Empty = "blank" | "skip" | "text";
const emptyOf = (l: LabelSpec): Empty => (l.omit_if_blank ? "skip" : l.fallback ? "text" : "blank");

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "info";

export function ExtraInfo({
  labels,
  onChange,
  headers,
  derived,
  sample,
  sampleName,
  issues,
}: {
  labels: LabelSpec[];
  onChange: (l: LabelSpec[]) => void;
  headers: string[];
  derived: string[];
  sample: Record<string, string> | undefined;
  /** the sample row's company, for the preview's title */
  sampleName?: string;
  issues: string[];
}) {
  const setRow = (i: number, l: LabelSpec) => onChange(labels.map((x, k) => (k === i ? l : x)));
  const insert = (l: LabelSpec, at?: number) => {
    const next = [...labels];
    next.splice(at ?? next.length, 0, l);
    onChange(next);
  };
  const fromCol = (h: string): LabelSpec => ({ send_as: slug(h), type: "column", source: h, fallback: "" });
  const fromDerived = (d: string): LabelSpec => ({ send_as: d, type: "derived", source: d, fallback: "unknown" });
  const fixed: LabelSpec = { send_as: "tag", type: "fixed", value: "" };

  // a drag carries either an existing row (to move it) or a new line (from a chip)
  const { start, wasDrag } = usePointerDrag<{ row?: number; add?: LabelSpec }>((p, t) => {
    const to = t.kind === "row" ? t.index : labels.length;
    if (p.row !== undefined) {
      if (t.kind !== "row" || p.row === to) return;
      const next = [...labels];
      const [moved] = next.splice(p.row, 1);
      next.splice(to, 0, moved);
      onChange(next);
    } else if (p.add) {
      insert(p.add, to);
    }
  });

  const sampleValue = (l: LabelSpec): string => {
    let v = "";
    if (l.type === "fixed") v = String(l.value ?? "");
    else if (l.type === "derived") return "(worked out when sent)";
    else for (const s of Array.isArray(l.source) ? l.source : [l.source ?? ""]) { v = String(sample?.[String(s)] ?? "").trim(); if (v) break; }
    if (v) return v;
    if (l.omit_if_blank) return "(not sent — empty)";
    return l.fallback ? l.fallback : "(blank)";
  };

  const chip = (label: string, make: () => LabelSpec, calc = false) => (
    <span key={label} className={calc ? "u-chip calc" : "u-chip"} role="button" tabIndex={0}
      title="Drag onto the list, or click to add"
      onPointerDown={(e) => start(e, { add: make() }, label)}
      onClick={() => { if (!wasDrag()) insert(make()); }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); insert(make()); } }}>
      {label}
    </span>
  );
  const colLabel = (h: string) => h.trim() || h;

  return (
    <div className="u-card">
      <div className="u-card-head">
        <div>
          <h3 className="u-h3">Extra info sent to Instantly</h3>
          <p>
            Each line becomes a <code>{"{{variable}}"}</code> you can write in your Instantly emails. Drag a column
            from the left onto the list (or click it), and drag ⋮⋮ to change the order.
          </p>
        </div>
      </div>
      {issues.length ? <div className="u-note bad" style={{ marginBottom: 12 }}>{issues.join(" · ")}</div> : null}
      <div className="u-builder">
        <div>
          <div className="u-small u-muted" style={{ marginBottom: 6 }}>Columns in this source</div>
          <div className="u-chips">{headers.map((h) => chip(colLabel(h), () => fromCol(h)))}</div>
          <div className="u-small u-muted" style={{ margin: "12px 0 6px" }}>Worked out by the app</div>
          <div className="u-chips">{derived.map((d) => chip(derivedWord(d), () => fromDerived(d), true))}</div>
          <div className="u-small u-muted" style={{ margin: "12px 0 6px" }}>Same text for everyone</div>
          <div className="u-chips">{chip("Fixed text…", () => ({ ...fixed }), true)}</div>
        </div>
        <div>
          <div className="u-labrow head"><span /><span>Name in Instantly</span><span>Value comes from</span><span>If it is empty</span><span /></div>
          {labels.map((l, i) => {
            const fv = fromValue(l);
            const empty = emptyOf(l);
            return (
              <div key={i} className="u-labrow" data-drop="row" data-index={i}>
                <span className="u-handle" title="Drag to reorder" onPointerDown={(e) => start(e, { row: i }, `{{${l.send_as ?? ""}}}`)}>⋮⋮</span>
                <input className="u-input" aria-label="Name in Instantly" value={l.send_as ?? ""}
                  title={`Write it in Instantly as {{${l.send_as ?? ""}}}`} onChange={(e) => setRow(i, { ...l, send_as: e.target.value })} />
                {l.type === "fixed" ? (
                  <span className="u-row" style={{ gap: 6, flexWrap: "nowrap" }}>
                    <select className="u-input" aria-label="Value comes from" value={fv} onChange={(e) => setRow(i, applyFrom(l, e.target.value))} style={{ width: 110 }}>
                      <option value="fixed">Text:</option>
                      {headers.map((h) => <option key={h} value={`col:${h}`}>{colLabel(h)}</option>)}
                    </select>
                    <input className="u-input" aria-label="Fixed text" placeholder="the same text for every lead" value={String(l.value ?? "")}
                      onChange={(e) => setRow(i, { ...l, value: e.target.value })} />
                  </span>
                ) : (
                  <select className="u-input" aria-label="Value comes from" value={fv} onChange={(e) => setRow(i, applyFrom(l, e.target.value))}>
                    {fv.startsWith("list:") ? <option value={fv}>{(l.source as string[]).join(" or ")} (first with a value)</option> : null}
                    {fv.startsWith("col:") && !headers.includes(String(l.source)) ? <option value={fv}>{String(l.source)} (not in this source)</option> : null}
                    <optgroup label="Columns">{headers.map((h) => <option key={h} value={`col:${h}`}>{colLabel(h)}</option>)}</optgroup>
                    <optgroup label="Worked out by the app">{derived.map((d) => <option key={d} value={`derived:${d}`}>{derivedWord(d)}</option>)}</optgroup>
                    <option value="fixed">Same text for everyone</option>
                  </select>
                )}
                {l.type === "fixed" ? <span className="u-small u-muted">always has a value</span> : (
                  <span className="u-row" style={{ gap: 6, flexWrap: "nowrap" }}>
                    <select className="u-input" aria-label="If it is empty" value={empty} style={empty === "text" ? { width: 110 } : undefined}
                      onChange={(e) => {
                        const v = e.target.value as Empty;
                        setRow(i, { ...l, omit_if_blank: v === "skip", fallback: v === "text" ? l.fallback || "unknown" : "" });
                      }}>
                      <option value="blank">send it blank</option>
                      <option value="skip">don’t send it</option>
                      <option value="text">send this text:</option>
                    </select>
                    {empty === "text" ? (
                      <input className="u-input" aria-label="Text when empty" value={l.fallback ?? ""} onChange={(e) => setRow(i, { ...l, fallback: e.target.value })} />
                    ) : null}
                  </span>
                )}
                <button type="button" className="u-x" aria-label="Remove" onClick={() => onChange(labels.filter((_, k) => k !== i))}>✕</button>
              </div>
            );
          })}
          <div className="u-drop" data-drop="end">
            {labels.length ? "Drop a column here to send it to Instantly" : "Nothing extra is sent yet. Drop a column here, or click one on the left."}
          </div>
          {labels.length ? (
            <div className="u-preview">
              <b className="u-ink">Preview — what Instantly gets for {sampleName || "the first lead"} (first row of the source)</b>
              <div className="u-kv">
                {labels.map((l, i) => [
                  <span key={`k${i}`}>{`{{${l.send_as ?? ""}}}`}</span>,
                  <span key={`v${i}`}>{sampleValue(l)}</span>,
                ])}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
