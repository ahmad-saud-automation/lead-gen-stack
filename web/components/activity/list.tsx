"use client";

/* Activity: every run and every send, newest first, each in one sentence. Searching looks
 * inside the step-by-step events of every run (what the old Log page did). */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Empty, PageHead, Seg } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson } from "@/lib/client-api";
import { money, num } from "@/lib/format";
import { runHref } from "@/lib/status";
import type { HistoryRow, LogView } from "@/lib/types";
import { whenWords } from "@/lib/words";

type Show = "all" | "run" | "push" | "problems";

export function describe(r: HistoryRow): { title: string; detail: string; icon: string; tone: "ok" | "bad" | "n" } {
  // runs before 29 Sep 2026 did not record their campaign: say nothing rather than guess
  const who = r.campaign_name || r.campaign || "";
  const when = whenWords(r.when);
  if ((r.kind ?? "run") === "push") {
    const failed = r.push_failed ? ` · ${num(r.push_failed)} failed` : "";
    return {
      title: r.test_mode ? `Dry run of a send — nothing was sent` : `Sent ${num(r.pushed)} lead${r.pushed === 1 ? "" : "s"} to Instantly`,
      detail: `${when}${who ? ` · from ${who}` : ""}${failed}`,
      icon: r.push_failed ? "!" : "↗", tone: r.push_failed ? "bad" : "ok",
    };
  }
  const noEmail = (r.not_found ?? 0) + (r.no_website ?? 0);
  const stopped = r.status === "cancelled";
  return {
    title: `${who ? `${who} — ` : ""}${who ? (r.test_mode ? "free test" : "live run") : (r.test_mode ? "Free test" : "Live run")}${stopped ? " (stopped)" : ""}`,
    detail: `${when} · ${num(r.leads)} leads → ${num(r.found)} email${r.found === 1 ? "" : "s"} found${noEmail ? `, ${num(noEmail)} without` : ""}${r.held ? `, ${num(r.held)} held` : ""} · ${money(r.test_mode ? 0 : r.spent_usd)}`,
    icon: stopped ? "–" : "✓", tone: stopped ? "n" : "ok",
  };
}

export function ActivityList() {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<LogView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJson<{ runs: HistoryRow[] }>("/history").then((h) => setRows(h.runs ?? [])).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) return setHits(null);
    const t = setTimeout(() => {
      getJson<LogView>("/log", { search: q.trim(), limit: "200" }).then(setHits).catch(() => setHits(null));
    }, 350);
    return () => clearTimeout(t);
  }, [q]);

  if (error) return <div className="u-page"><ErrorBox title="Activity could not be loaded" detail={error} /></div>;

  const shown = (rows ?? []).filter((r) =>
    show === "all" ? true
      : show === "problems" ? r.status !== "finished" || !!r.push_failed
      : (r.kind ?? "run") === show);

  return (
    <div className="u-page">
      <PageHead title="Activity" sub="Every run and every send, newest first. Open one to see each lead."
        actions={<a className="u-btn" href="/api/log/download">Download as CSV</a>} />
      <div className="u-row" style={{ marginBottom: 12 }}>
        <Seg label="Show" value={show} onChange={setShow} options={[
          { value: "all", label: "All" }, { value: "run", label: "Runs" }, { value: "push", label: "Sends to Instantly" }, { value: "problems", label: "Problems" },
        ]} />
        <input className="u-input" style={{ maxWidth: 300 }} aria-label="Search" placeholder="Search a company or email…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {q.trim().length >= 2 ? (
        !hits ? <div className="u-card"><Loading rows={4} /></div>
          : hits.events.length === 0 ? <Empty title={`Nothing found for “${q.trim()}”`}>It searches every step of every run kept.</Empty>
          : (
            <div className="u-list">
              {hits.events.map((e, i) => (
                <Link key={`${e.run_id}-${e.seq}-${i}`} className="u-li" href={runHref(e.run_id ?? "", "log")} style={{ gridTemplateColumns: "28px minmax(0,1fr) auto" }}>
                  <span className={e.status === "fail" ? "u-dot bad" : e.status === "success" ? "u-dot ok" : "u-dot n"}>{e.status === "fail" ? "!" : e.status === "success" ? "✓" : "–"}</span>
                  <div className="t"><b>{e.company || "—"}</b><div>{whenWords(e.when ?? "")} · {e.detail}{e.email ? ` · ${e.email}` : ""}</div></div>
                  <span className="u-small u-muted">Open</span>
                </Link>
              ))}
            </div>
          )
      ) : !rows ? (
        <div className="u-card"><Loading rows={6} /></div>
      ) : shown.length === 0 ? (
        <Empty title={show === "problems" ? "No problems" : "Nothing here yet"}>
          {show === "all" ? <>Runs appear here once you start one from <Link className="u-link" href="/campaigns">Campaigns</Link>.</> : "Nothing of this kind is kept."}
        </Empty>
      ) : (
        <div className="u-list">
          {shown.map((r) => {
            const d = describe(r);
            return (
              <Link key={r.run_id} className="u-li" href={runHref(r.run_id)} style={{ gridTemplateColumns: "28px minmax(0,1fr) auto" }}>
                <span className={`u-dot ${d.tone}`}>{d.icon}</span>
                <div className="t"><b>{d.title}</b><div>{d.detail}</div></div>
                <span className="u-small u-muted">Open</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
