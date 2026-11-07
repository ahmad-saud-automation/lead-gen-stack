"use client";

/* Campaigns: one row each, in the order that decides who gets a shared lead. Drag ⋮⋮ to change
 * that order (saved at once). The counts come from the free plan, which applies the order: a
 * lead two campaigns both want is counted for the higher one only. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Empty, Note, PageHead, Pill } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { usePointerDrag } from "@/lib/drag";
import { getJson, postJson } from "@/lib/client-api";
import { num } from "@/lib/format";
import { flashNote } from "@/lib/nav";
import { campaignStatus, runHref } from "@/lib/status";
import type { CampaignsSaved, CampaignsView, CampaignSummary, HistoryRow, PlanReport } from "@/lib/types";
import { whenWords } from "@/lib/words";

const sourceWord = (tab: string) => (tab.startsWith("import:") ? `Uploaded file ${tab.slice(7)}` : `${tab.trim()} tab`);

export function CampaignList() {
  const [data, setData] = useState<CampaignsView | null>(null);
  const [order, setOrder] = useState<CampaignSummary[]>([]);
  const [plan, setPlan] = useState<Record<string, { available: number; matched: number }> | null>(null);
  const [planNote, setPlanNote] = useState("");
  const [last, setLast] = useState<Record<string, HistoryRow>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    getJson<CampaignsView>("/campaigns")
      .then((v) => {
        setData(v);
        setOrder([...(v.campaigns ?? [])].sort((a, b) => a.priority - b.priority));
      })
      .catch((e: Error) => setError(e.message));
    getJson<{ runs: HistoryRow[] }>("/history")
      .then((h) => {
        const m: Record<string, HistoryRow> = {};
        for (const r of h.runs ?? []) if (r.campaign && (r.kind ?? "run") === "run" && !m[r.campaign]) m[r.campaign] = r;
        setLast(m);
      })
      .catch(() => {});
    getJson<PlanReport>("/plan", { all: "true" })
      .then((p) => {
        setPlan(Object.fromEntries((p.campaigns ?? []).map((l) => [l.campaign, { available: l.available, matched: l.matched }])));
        if (p.warnings?.length) setPlanNote(p.warnings.join(" · "));
      })
      .catch((e: Error) => setPlanNote(`Counts unavailable: ${e.message}`));
  }, []);

  const { start, dragging } = usePointerDrag<number>(async (from, t) => {
    if (t.kind !== "camp" || t.index === from) return;
    const next = [...order];
    const [moved] = next.splice(from, 1);
    next.splice(t.index, 0, moved);
    setOrder(next);
    try {
      const r = await postJson<CampaignsSaved>("/campaigns/reorder", { ids: next.map((c) => c.id) });
      if (!r.ok) throw new Error((r.issues ?? []).map((i) => i.issue).join(" · "));
      const below = next[t.index + 1];
      flashNote(below ? `Order saved — “${moved.name}” now gets shared leads before “${below.name}”.` : `Order saved — “${moved.name}” is now last.`);
    } catch (e) {
      setOrder(order);
      flashNote({ text: `The order was not saved: ${e instanceof Error ? e.message : e}`, tone: "warn" });
    }
  });

  if (error) return <div className="u-page"><ErrorBox title="Campaigns could not be loaded" detail={error} /></div>;

  const issues = (id: string) => (data?.issues ?? []).filter((i) => i.campaign === id).length;

  return (
    <div className="u-page">
      <PageHead
        title="Campaigns"
        sub="Each campaign takes the leads that fit its filters, finds their emails, and sends them to one Instantly campaign."
        actions={<Link className="u-btn primary" href="/campaigns/new">+ New campaign</Link>}
      />
      {!data ? (
        <div className="u-card"><Loading rows={6} /></div>
      ) : order.length === 0 ? (
        <Empty title="No campaigns yet">
          A campaign decides which leads to work on and where to send them.
          <div style={{ marginTop: 12 }}><Link className="u-btn primary" href="/campaigns/new">Create your first campaign</Link></div>
        </Empty>
      ) : (
        <>
          <div style={{ marginBottom: 12 }}>
            <Note>If a lead fits two campaigns, the one <b>higher in this list</b> gets it. Drag <span className="u-handle">⋮⋮</span> to change the order.</Note>
          </div>
          <div className="u-listhead u-camp-li u-hide-m">
            <span /><span>Campaign</span><span>Status</span><span>Leads left</span><span>Next run</span><span>Last run</span><span />
          </div>
          <div className="u-list">
            {order.map((c, i) => {
              const st = campaignStatus(c, issues(c.id));
              const lr = last[c.id];
              const pl = plan?.[c.id];
              return (
                <div key={c.id} className={dragging === i ? "u-li u-camp-li hover dragging" : "u-li u-camp-li hover"} data-drop="camp" data-index={i}>
                  <span className="u-handle" title="Drag to change the order" onPointerDown={(e) => start(e, i, c.name)}>⋮⋮</span>
                  <div className="t">
                    <Link href={`/campaigns/${encodeURIComponent(c.id)}`} className="u-ink" style={{ textDecoration: "none" }}><b>{c.name}</b></Link>
                    <div>{sourceWord(c.tab)} · {c.rule_count ? `${c.rule_count} filter${c.rule_count > 1 ? "s" : ""}` : "no filters"} · {num(c.per_run)} per run</div>
                  </div>
                  <span title={st.why}><Pill tone={st.tone}>{st.label}</Pill></span>
                  <div className="t u-hide-m">
                    <b>{pl ? num(pl.available) : plan ? "—" : "…"}</b>
                    <div>{pl ? `of ${num(pl.matched)} that fit` : ""}</div>
                  </div>
                  <div className="t u-hide-m">
                    <b>{c.schedule?.active && c.schedule.next_run ? whenWords(c.schedule.next_run) : "—"}</b>
                    <div>{c.schedule?.active ? c.schedule.summary : "when you press Run"}</div>
                  </div>
                  <div className="t u-hide-m">
                    {lr ? (
                      <Link href={runHref(lr.run_id)} style={{ textDecoration: "none", color: "inherit" }}>
                        <b>{num(lr.found)} of {num(lr.leads)} found</b>
                        <div>{whenWords(lr.when)}{lr.test_mode ? " · test" : ""}</div>
                      </Link>
                    ) : <><b>never</b><div /></>}
                  </div>
                  <Link className="u-btn sm" href={`/campaigns/${encodeURIComponent(c.id)}`}>Open</Link>
                </div>
              );
            })}
          </div>
          {planNote ? <p className="u-small u-muted" style={{ marginTop: 10 }}>{planNote}</p> : null}
        </>
      )}
    </div>
  );
}
