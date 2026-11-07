"use client";

/* Sections 2 and 3 of a campaign — How many, Send to — shared by the campaign page and the
 * New-campaign wizard, so both look and behave the same. */

import Link from "next/link";
import { useState } from "react";

import { Field, Note, Step, SwitchRow } from "@/components/u";
import { money, num } from "@/lib/format";
import type { CampaignCounts, CampaignRaw, InstantlyOptions } from "@/lib/types";

type SetIn = <K extends "limits" | "writeback" | "instantly">(key: K, patch: NonNullable<CampaignRaw[K]>) => void;

export function ManySection({ c, setIn, counts, n = 2 }: { c: CampaignRaw; setIn: SetIn; counts: CampaignCounts | null; n?: number }) {
  return (
    <Step n={n} id="sec-many" title="How many" question="How fast should it work?">
      <div className="u-fgrid">
        <Field label="Leads per run" hint={c.pipeline ? "How many NEW leads one run takes from the sheet." : "How many leads one run works on."}>
          <input className="u-input" type="number" min={1} aria-label="Leads per run" value={c.limits?.per_run ?? 50}
            onChange={(e) => setIn("limits", { per_run: Number(e.target.value) || 0 })} />
        </Field>
        <Field label="Leads per day" hint="Stops after this many in a day. 0 = no limit.">
          <input className="u-input" type="number" min={0} aria-label="Leads per day" value={c.limits?.per_day ?? 100}
            onChange={(e) => setIn("limits", { per_day: Number(e.target.value) || 0 })} />
        </Field>
        <Field label="Most it may spend per run ($)" hint="The run stops before it costs more.">
          <input className="u-input" type="number" min={0} step={0.5} aria-label="Most it may spend per run" value={c.limits?.max_spend_usd ?? 2}
            onChange={(e) => setIn("limits", { max_spend_usd: Number(e.target.value) || 0 })} />
        </Field>
      </div>
      {counts && !counts.error ? (
        <div style={{ marginTop: 14 }}>
          <Note>
            At {num(counts.per_run)} per run, a live run costs about <b>{money(counts.est_cost_per_run)}</b> (email checks)
            {c.limits?.per_day ? <>, and a full day about <b>{money(counts.est_cost_per_day)}</b></> : null}.
          </Note>
        </div>
      ) : null}
    </Step>
  );
}

export function SendSection({
  c,
  setIn,
  inst,
  reload,
  onAutoPush,
  onPipeline,
  n = 3,
}: {
  c: CampaignRaw;
  setIn: SetIn;
  inst: InstantlyOptions | null;
  reload: () => void;
  /** turning auto-send ON asks first; off goes straight through */
  onAutoPush: (on: boolean) => void;
  /** the "Run in the 6-step pipeline" switch; hidden when not given */
  onPipeline?: (on: boolean) => void;
  n?: number;
}) {
  const [paste, setPaste] = useState(false);
  const instId = c.instantly?.campaign_id ?? "";
  const known = inst?.campaigns.some((x) => x.id === instId);
  const upload = (c.tab ?? "").startsWith("import:");
  const usePaste = paste || (!!inst && !inst.ok);
  return (
    <Step n={n} id="sec-send" title="Send to" question="Where do the found leads go?">
      <div className="u-fgrid two">
        <Field label="Instantly campaign" bad={!!inst && !inst.ok} hint={inst && !inst.ok
          ? <>{inst.detail}. <Link className="u-link" href="/settings">Settings</Link> · or paste an ID</>
          : <>The list comes from your Instantly account. <button type="button" className="u-link" onClick={reload}>Refresh</button> · <button type="button" className="u-link" onClick={() => setPaste(!paste)}>{paste ? "pick from the list" : "paste an ID instead"}</button></>}>
          {usePaste ? (
            <input id="inst-pick" className="u-input u-mono" aria-label="Instantly campaign ID" placeholder="00000000-0000-0000-0000-000000000000"
              value={instId} onChange={(e) => setIn("instantly", { campaign_id: e.target.value.trim() })} />
          ) : (
            <select id="inst-pick" className="u-input" aria-label="Instantly campaign" value={instId} disabled={!inst}
              onChange={(e) => setIn("instantly", { campaign_id: e.target.value })}>
              <option value="">{inst ? "— choose one —" : "Loading your Instantly campaigns…"}</option>
              {instId && inst && !known ? <option value={instId}>{instId} (not found in your Instantly)</option> : null}
              {(inst?.campaigns ?? []).map((x) => <option key={x.id} value={x.id}>{x.name} — {x.status}</option>)}
            </select>
          )}
        </Field>
      </div>
      <div style={{ marginTop: 10 }}>
        {c.pipeline ? (
          <div style={{ marginBottom: 6 }}>
            <Note>
              In the 6-step pipeline, every run ends with <b className="u-ink">Sending</b>: each ready lead is added to
              this Instantly campaign, only while it is a Draft or Paused, so nothing is sent by itself.
            </Note>
            <SwitchRow title="Update my Google Sheet with the results"
              desc={upload
                ? "This campaign reads an uploaded file, so there is no sheet to update."
                : "After each run: Found Email, Ice Breaker and Status columns. Only empty cells are filled; nothing you typed is changed and no row is deleted."}
              checked={c.writeback?.enabled !== false} disabled={upload}
              onChange={(v) => setIn("writeback", { enabled: v })} />
          </div>
        ) : (
          <>
            <SwitchRow title="Send to Instantly automatically"
              desc="Off = you review each batch first, on the run's page. Turn on only when you trust this campaign."
              checked={!!c.auto_push} onChange={onAutoPush} />
            <SwitchRow title="Update my Google Sheet with the results"
              desc={upload
                ? "This campaign reads an uploaded file, so there is no sheet to update."
                : "Writes the email found, its check result and “sent” onto each row, so nobody is contacted twice."}
              checked={c.writeback?.enabled !== false} disabled={upload}
              onChange={(v) => setIn("writeback", { enabled: v })} />
          </>
        )}
        {onPipeline ? (
          <SwitchRow title="Run in the 6-step pipeline"
            desc="Find email, Website research, Ice breakers, Email template, Sending and Replies. Leads are added to the Instantly campaign only while it is a Draft or Paused."
            checked={!!c.pipeline} onChange={onPipeline} />
        ) : null}
      </div>
    </Step>
  );
}
