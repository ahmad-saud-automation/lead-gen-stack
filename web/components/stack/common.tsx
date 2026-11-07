"use client";

/* Pieces shared by the stack screens (Leads, Website research, Find email): the lead-source
 * picker, the demo bar and a step-value pill. The chosen source lives in ?source=, so a page
 * can be linked and reloaded; changing it is a real navigation (lib/nav.ts explains why). */

import { useEffect, useState } from "react";

import { getJson } from "@/lib/client-api";
import { goWithParams } from "@/lib/nav";
import type { Picker, StepPill } from "@/lib/stack-types";

/** The campaign a page shows: ?source= when given, else the first real campaign that runs
 * the pipeline. The built-in sample firms are only a fallback when there is none. */
export function useSource(): string {
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("source");
    if (q) {
      setSource(q);
      return;
    }
    getJson<{ pickers: Picker[] }>("/stack/pickers")
      .then((r) => setSource((r.pickers ?? []).find((p) => !p.demo && p.runnable)?.id ?? "demo"))
      .catch(() => setSource("demo"));
  }, []);
  return source ?? "";
}

/** Real campaigns only; the sample firms show only when nothing else exists. */
export function realPickers(all: Picker[]): Picker[] {
  const real = all.filter((p) => !p.demo);
  return real.length ? real : all;
}

/** Same rule for any list of campaign tiles or rows: hide the sample set when a real one exists. */
export function onlyReal<T>(xs: T[], isSample: (x: T) => boolean): T[] {
  const real = xs.filter((x) => !isSample(x));
  return real.length ? real : xs;
}

export function SourcePicker({ path, source }: { path: string; source: string }) {
  const [pickers, setPickers] = useState<Picker[]>([]);
  useEffect(() => {
    getJson<{ pickers: Picker[] }>("/stack/pickers").then((r) => setPickers(realPickers(r.pickers ?? []))).catch(() => {});
  }, []);
  return (
    <select className="u-input u-sel" aria-label="Campaign" value={source}
      onChange={(e) => goWithParams(path, { source: e.target.value, lead: null })}>
      {pickers.length ? pickers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>) : <option value={source}>Loading…</option>}
    </select>
  );
}

export function DemoBar() {
  return (
    <div className="u-banner" role="note">
      <span className="u-pill warn">Demo workspace</span>Sample data only. No real company is contacted and nothing is charged.
    </div>
  );
}

export function StepValue({ p }: { p?: StepPill }) {
  if (!p?.value) return <span className="u-muted">—</span>;
  return <span className={p.tone ? `u-pill ${p.tone}` : "u-pill"}>{p.label}</span>;
}

/** One query-string value, read after the first paint (like useSource). */
export function useParam(name: string): string | null {
  const [v, setV] = useState<string | null>(null);
  useEffect(() => {
    setV(new URLSearchParams(window.location.search).get(name) || "");
  }, [name]);
  return v;
}

/** The grey tile that stands for every campaign not yet switched into the pipeline. */
export function LaterTile({ count, why }: { count: number; why: string }) {
  if (!count) return null;
  return (
    <div className="u-tile" data-testid="later-tile">
      <div className="u-row sb"><b className="u-ink">Other campaigns</b><span className="u-pill">Pipeline off</span></div>
      <div className="u-small u-muted" style={{ margin: "4px 0 10px" }}>{count} campaign{count === 1 ? "" : "s"}</div>
      <div className="u-small">{why}</div>
    </div>
  );
}

/** "Planned for a later update" for a source that cannot run yet. */
export function NotYet({ why }: { why: string }) {
  return <div className="u-note warn" style={{ marginBottom: 14 }}>{why}</div>;
}
