"use client";

/* Every lead one campaign found that never reached Instantly, across all of its live runs, sent
 * in one go. Before this (2026-10-15) the only way was a run's own Send tab, one run at a time,
 * and leads found while sending was off were never picked up again. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Confirm } from "@/components/modal";
import { Card, Note, PageHead } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { num } from "@/lib/format";
import { goWithNote } from "@/lib/nav";
import { runHref } from "@/lib/status";
import type { PushPreview, RunStarted } from "@/lib/types";

export function BacklogSend({ id }: { id: string }) {
  const [p, setP] = useState<PushPreview | null>(null);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getJson<PushPreview>("/push/backlog/preview", { campaign: id })
      .then((r) => (r.error ? setError(r.error) : setP(r)))
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const send = async (test: boolean) => {
    setConfirm(false);
    setBusy(true);
    setError("");
    try {
      const r = await postJson<RunStarted>("/push/backlog/start", { campaign: id, test_mode: test, confirm: true });
      if (r.error || !r.run_id) throw new Error(r.error || "The send did not start.");
      goWithNote(runHref(r.run_id), test ? "Dry run started — nothing is being sent." : "Sending to Instantly…");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const back = { href: `/campaigns/${encodeURIComponent(id)}`, label: "Campaign" };
  if (!p) {
    return (
      <div className="u-page">
        <PageHead back={back} title="Send waiting leads" />
        {error ? <ErrorBox title="Could not prepare the send" detail={error} /> : <div className="u-card"><Loading rows={5} /></div>}
      </div>
    );
  }

  const blocked = busy || !p.ready || !p.has_key || !p.campaign_id || !!p.push_running;
  return (
    <div className="u-page">
      <PageHead back={back} title="Send waiting leads"
        sub={<>Everything <b className="u-ink">{p.campaign_name || id}</b> found that is not in Instantly yet, from all its live runs.</>} />
      <Card>
        <div className="u-stack">
          {!p.found ? (
            <Note tone="good">Nothing is waiting — every lead this campaign found is already in Instantly.</Note>
          ) : (
            <Note tone={p.ready ? "good" : undefined}>
              <b>{num(p.ready)}</b> lead{p.ready === 1 ? " is" : "s are"} ready to send, from {num(p.runs ?? 0)} run{p.runs === 1 ? "" : "s"}.
              {p.unchecked ? <> {num(p.unchecked)} of them use the email already in your sheet, sent without a check.</> : null}
              {p.held_not_send_ready ? <> {num(p.held_not_send_ready)} found an address that did not pass the check, so they stay back.</> : null}
              {p.waiting_icebreaker ? <> {num(p.waiting_icebreaker)} are waiting for an ice breaker from Icebreaker Studio{p.waiting_companies?.length ? ` (${p.waiting_companies.slice(0, 5).join(", ")}${p.waiting_companies.length > 5 ? "…" : ""})` : ""}.</> : null}
            </Note>
          )}
          {p.icebreaker_note ? <Note tone="warn">{p.icebreaker_note}</Note> : null}
          {p.push_running ? <Note tone="warn">A send for this campaign is running now. Wait for it to finish, then come back.</Note> : null}
          {!p.has_key ? <Note tone="bad">No Instantly key yet — add it in <Link className="u-link" href="/settings">Settings</Link>.</Note> : null}
          {!p.campaign_id ? <Note tone="bad">This campaign has no Instantly campaign chosen.</Note> : null}
          {(p.leads ?? []).length ? (
            <div>
              <b className="u-ink">What Instantly gets</b> <span className="u-small u-muted">(first {Math.min(25, p.leads?.length ?? 0)})</span>
              {(p.leads ?? []).slice(0, 25).map((l, i) => (
                <details key={i} className="u-adv small" style={{ marginTop: 6 }}>
                  <summary>{String(l.company_name ?? "")} <span className="u-muted u-small">· {String(l.email ?? "")}</span></summary>
                  <div className="u-kv">
                    {Object.entries(l).flatMap(([k, v]) => (k === "custom_variables" && v && typeof v === "object"
                      ? Object.entries(v as Record<string, unknown>).map(([ck, cv]) => [`{{${ck}}}`, cv] as const)
                      : [[k, v] as const])).map(([k, v]) => [
                      <span key={`k${k}`}>{k}</span>, <span key={`v${k}`}>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</span>,
                    ])}
                  </div>
                </details>
              ))}
            </div>
          ) : null}
          {error ? <ErrorBox title="Not sent" detail={error} /> : null}
          {p.found ? <div className="u-row">
            <button type="button" className="u-btn" onClick={() => send(true)} disabled={busy || !p.ready || !!p.push_running}>Dry run (sends nothing)</button>
            <button type="button" className="u-btn primary" onClick={() => setConfirm(true)} disabled={blocked}>
              Send all {num(p.ready)} to Instantly
            </button>
            {p.delay && p.ready ? <span className="u-small u-muted">One every {p.delay} seconds — about {Math.ceil((p.ready * p.delay) / 60)} min.</span> : null}
          </div> : null}
        </div>
      </Card>

      {confirm ? (
        <Confirm title="Send these leads to Instantly?" danger confirmLabel={`Yes, send ${num(p.ready)}`} onConfirm={() => send(false)} onClose={() => setConfirm(false)}
          body={<>
            <p>This <b>leaves your computer</b>: {num(p.ready)} lead{p.ready === 1 ? "" : "s"} will be added to <b>{p.campaign_name || id}</b>&apos;s Instantly campaign.</p>
            {p.unchecked ? <p>{num(p.unchecked)} of them are the sheet&apos;s own email, never checked — some may bounce.</p> : null}
            <p className="muted">The daily send limit still applies; anything over it stays waiting for next time.</p>
          </>} />
      ) : null}
    </div>
  );
}
