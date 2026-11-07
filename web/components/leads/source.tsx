"use client";

/* One lead source: is it healthy, which of its columns hold what (column matching), and what
 * its first rows look like. Column matching saves the source's map file exactly as the old
 * Field-map page did ({field: header}); a field left on "Automatic" uses the built-in guesses. */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { matchedCount } from "@/components/leads/list";
import { Confirm } from "@/components/modal";
import { Card, Checklist, PageHead, Tile } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { num } from "@/lib/format";
import { goWithNote, reloadWithNote } from "@/lib/nav";
import type { CampaignsView, FieldmapDetail, FieldmapSaved, ImportPreview } from "@/lib/types";
import { FIELD_GROUPS, FIELD_WORDS, WRITTEN_GROUP } from "@/lib/words";

type Mapping = Record<string, string>;

export function SourcePage({ tab }: { tab: string }) {
  const [p, setP] = useState<ImportPreview | null>(null);
  const [d, setD] = useState<FieldmapDetail | null>(null);
  const [map, setMap] = useState<Mapping>({});
  const [saved, setSaved] = useState<Mapping>({});
  const [users, setUsers] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const upload = tab.startsWith("import:");

  useEffect(() => {
    getJson<ImportPreview>("/imports/preview", { tab })
      .then((r) => { if (r.error) throw new Error(r.error); setP(r); })
      .catch((e: Error) => setError(e.message));
    getJson<FieldmapDetail>("/fieldmap/detail", { tab })
      .then((r) => {
        if (r.error) return setProblem(r.error);
        setD(r);
        const m = Object.fromEntries(r.fields.filter((f) => f.mapped).map((f) => [f.field, f.mapped]));
        setMap(m);
        setSaved(m);
      })
      .catch((e: Error) => setProblem(e.message));
    getJson<CampaignsView>("/campaigns").then((v) => setUsers((v.campaigns ?? []).filter((c) => c.tab === tab).map((c) => ({ id: c.id, name: c.name })))).catch(() => {});
  }, [tab]);

  const dirty = useMemo(() => JSON.stringify(map) !== JSON.stringify(saved), [map, saved]);
  if (error) return <div className="u-page"><PageHead title={tab} back={{ href: "/sources", label: "Lead sources" }} /><ErrorBox title="This source could not be read" detail={error} /></div>;
  if (!p) return <div className="u-page"><PageHead title={tab.replace(/^import:/, "")} back={{ href: "/sources", label: "Lead sources" }} /><div className="u-card"><Loading rows={8} /></div></div>;

  const s = p.stats;
  const left = s.duplicates + s.suppressed + s.in_ledger + s.no_company;
  const usable = Math.max(0, s.rows - left);
  const title = upload ? p.import?.name ?? tab.slice(7) : tab.trim();
  const headers = d?.headers ?? [];
  const fillOf = new Map(headers.map((h) => [h.name, h.fill]));
  const firstRow = d?.preview?.[0] ?? p.sample?.[0] ?? {};
  const fieldRow = (f: FieldmapDetail["fields"][number]) => {
    const words = FIELD_WORDS[f.field] ?? { name: f.field, hint: f.note, group: "" };
    const chosen = map[f.field] ?? "";
    const effective = chosen || f.resolved;
    const fill = effective ? fillOf.get(effective) : undefined;
    const reads = f.direction !== "write";
    const mark = !effective
      ? (f.required ? <span className="u-badmark" title="Needed — choose its column">✕</span> : <span className="u-muted" title="Not in this source">–</span>)
      : reads && fill === 0 ? <span className="u-warnmark" title="That column is empty in the first 500 rows">!</span>
      : <span className="u-tick">✓</span>;
    const eg = effective ? String(firstRow[effective] ?? "").trim() : "";
    return (
      <div className="u-maprow" key={f.field}>
        <div><b>{words.name}</b><div className="d">{f.required ? "Needed" : words.hint}</div></div>
        <span className="arr u-muted">→</span>
        <select className="u-input" aria-label={`Column for ${words.name}`} value={chosen}
          onChange={(e) => setMap((m) => { const n = { ...m }; if (e.target.value) n[f.field] = e.target.value; else delete n[f.field]; return n; })}>
          <option value="">{f.resolved ? `Automatic — ${f.resolved.trim()}` : "Automatic — not found"}</option>
          {headers.map((h) => <option key={h.name} value={h.name}>{h.name.trim() || h.name} ({h.fill}% filled)</option>)}
        </select>
        <span className="eg" title={eg}>{eg ? `e.g. ${eg}` : effective && reads && fill === 0 ? "empty in the first rows" : ""}</span>
        {mark}
      </div>
    );
  };
  const groups = d ? [...FIELD_GROUPS].map((g) => ({ g, fields: d.fields.filter((f) => FIELD_WORDS[f.field]?.group === g) })) : [];
  const written = d ? d.fields.filter((f) => !FIELD_WORDS[f.field] || FIELD_WORDS[f.field].group === WRITTEN_GROUP) : [];
  const m = matchedCount(d ? Object.fromEntries(d.fields.map((f) => [f.field, map[f.field] || f.resolved])) : p.check?.resolved);

  const save = async () => {
    if (!d) return;
    setSaving(true);
    setProblem("");
    try {
      const r = await postJson<FieldmapSaved>("/fieldmap/save", { file: d.file, mapping: map });
      if (!r.ok) throw new Error(r.error || "Not saved.");
      reloadWithNote(`Column matching saved for ${title}.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };
  const remove = async () => {
    setConfirmRemove(false);
    try {
      const r = await postJson<{ ok: boolean; error?: string }>("/imports/delete", { slug: tab.slice(7), delete_file: true });
      if (!r.ok) throw new Error(r.error || "Not removed.");
      goWithNote("/sources", `${title} removed.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    }
  };

  const checks = [
    ...(p.check.blocking ?? []).map((b) => ({ ok: false, text: b })),
    ...(p.check.blocking?.length ? [] : [{ ok: true, text: "The app can read every column it needs." }]),
    ...(upload ? [{ ok: true as const, text: "This is an uploaded file: runs and sends never write anything back to it." }] : []),
    ...(p.import?.status_added ? [{ ok: true as const, text: "The file had no Status column, so an empty one was added — every row starts as not done." }] : []),
    ...(p.hold_without_icebreaker && s.with_icebreaker < s.rows
      ? [{ ok: false as const, text: <>{s.has_icebreaker_column ? `${num(s.rows - s.with_icebreaker)} rows have no ice breaker yet` : "There is no Ice Breaker column"} — those leads wait instead of being sent. Write them in Icebreaker Studio, or change <Link className="u-link" href="/settings#s-safety">Lead safety</Link>.</> }]
      : []),
  ];

  return (
    <div className="u-page">
      <PageHead back={{ href: "/sources", label: "Lead sources" }} title={title}
        sub={upload ? `Uploaded ${p.import?.uploaded ?? ""} · ${num(p.headers.length)} columns · never written back to` : "Google Sheet tab · read fresh every time a campaign runs"}
        actions={upload ? <Link className="u-btn primary" href={`/campaigns/new?tab=${encodeURIComponent(tab)}`}>+ Create a campaign from it</Link> : undefined} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="That did not work" detail={problem} /></div> : null}

      <div className="u-grid4">
        <Tile label="Rows" value={num(s.rows)} sub={`${num(p.headers.length)} columns`} />
        <Tile label="A campaign could use" value={num(usable)} sub="before its own filters" />
        <Tile label="Left out" value={num(left)} sub={`${num(s.duplicates)} repeats · ${num(s.suppressed)} do-not-contact · ${num(s.in_ledger)} done before · ${num(s.no_company)} no company`} />
        <Tile label="Ice breakers written" value={num(s.with_icebreaker)} sub={s.has_icebreaker_column ? "from the Ice Breaker column" : "no Ice Breaker column"} />
      </div>

      <div className="u-stack" style={{ marginTop: 14 }}>
        <Card title="Health">
          <Checklist items={checks} />
          <p className="u-small u-muted" style={{ marginTop: 10 }}>
            {users.length ? <>Used by {users.map((u, i) => <span key={u.id}>{i ? ", " : ""}<Link className="u-link" href={`/campaigns/${encodeURIComponent(u.id)}`}>{u.name}</Link></span>)}.</> : "No campaign uses this source yet."}
          </p>
        </Card>

        <Card title="Column matching" sub="Which of your columns holds what. Matched automatically — change one only if it is wrong."
          right={d ? <span className={m.matched ? "u-note good" : "u-note"}>{m.matched} of {m.needed} matched</span> : undefined}>
          {!d ? <Loading rows={6} /> : (
            <>
              {groups.map(({ g, fields }) => (
                <div className="u-mapgroup" key={g}><h3>{g}</h3>{fields.map(fieldRow)}</div>
              ))}
              <details className="u-adv small" style={{ marginTop: 16 }}>
                <summary>{written.length} columns the app writes results into — matched automatically</summary>
                <div className="u-mapgroup">{written.map(fieldRow)}</div>
              </details>
              <div className="u-row" style={{ marginTop: 16 }}>
                <button type="button" className="u-btn primary" onClick={save} disabled={!dirty || saving}>{saving ? "Saving…" : "Save column matching"}</button>
                {dirty ? <button type="button" className="u-btn" onClick={() => setMap(saved)}>Undo changes</button> : null}
                <span className="u-small u-muted">Saved to <span className="u-mono">{d.file}</span>{users.length > 1 ? ` — used by all ${users.length} campaigns on this source` : ""}.</span>
              </div>
            </>
          )}
        </Card>

        <Card title="First rows" sub={p.headers.length > 6 ? `First ${Math.min(5, p.sample.length)} rows, first 6 of ${p.headers.length} columns` : undefined}>
          <div className="u-scroll">
            <table className="u-table">
              <thead><tr>{p.headers.slice(0, 6).map((h) => <th key={h}>{h.trim() || h}</th>)}</tr></thead>
              <tbody>
                {p.sample.slice(0, 5).map((r, i) => (
                  <tr key={i}>{p.headers.slice(0, 6).map((h) => <td key={h} className="clip">{r[h]}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {upload ? (
          <Card title="Remove this file">
            <p className="u-muted u-small">{users.length ? "A campaign still reads it — delete or move that campaign first." : "Deletes the uploaded copy. Runs already made from it keep their results."}</p>
            <button type="button" className="u-btn danger" disabled={!!users.length} onClick={() => setConfirmRemove(true)}>Remove file…</button>
          </Card>
        ) : null}
      </div>

      {confirmRemove ? (
        <Confirm title={`Remove ${title}?`} danger confirmLabel="Remove it" onConfirm={remove} onClose={() => setConfirmRemove(false)}
          body={<p>The uploaded copy is deleted. Past runs keep their results, and the lead history still remembers every lead it handled.</p>} />
      ) : null}
    </div>
  );
}
