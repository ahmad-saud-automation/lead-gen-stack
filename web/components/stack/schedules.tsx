"use client";

/* Schedules (build session 3, as the approved sample): one row per step, plus the health
 * check and the daily summary. Each starts at a set time, or after the previous step.
 * "Change" opens the row's trigger below it; the switch turns a row on or off. The approval
 * rules card holds the three switches; two are locked off in test mode. */

import { Fragment, useEffect, useState } from "react";

import { LaterTile } from "@/components/stack/common";
import { Card, PageHead, Seg, Switch } from "@/components/u";
import { ErrorBox, Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { flashNote } from "@/lib/nav";
import type { RawSchedule, ScheduleRow, SchedulesView } from "@/lib/stack-types";

type Kind = "weekdays" | "daily" | "minutes";
type Draft = { trigger: "time" | "after"; kind: Kind; start: string; every: number };

const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI"];

function draftOf(r: ScheduleRow): Draft {
  const s = r.raw;
  const kind: Kind = !s ? "daily" : s.kind === "minute" ? "minutes" : s.kind === "weekly" ? "weekdays" : "daily";
  return { trigger: r.trigger, kind, start: s?.start ?? "07:00", every: s?.kind === "minute" ? s.every : 30 };
}

function scheduleOf(d: Draft): Partial<RawSchedule> {
  if (d.kind === "minutes") return { kind: "minute", every: d.every, start: "00:00", end: "23:59", days: [] };
  if (d.kind === "weekdays") return { kind: "weekly", every: 1, start: d.start, days: WEEKDAYS };
  return { kind: "daily", every: 1, start: d.start };
}

export function SchedulesPage() {
  const [v, setV] = useState<SchedulesView | null>(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [problem, setProblem] = useState("");

  const load = () => getJson<SchedulesView>("/stack/schedules").then(setV).catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
    const t = window.setInterval(load, 5000);          // "Next run" and a demo countdown stay current
    return () => window.clearInterval(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (r: ScheduleRow, body: Record<string, unknown>, note: string) => {
    setProblem("");
    const res = await postJson<SchedulesView & { ok: boolean; error?: string }>("/stack/schedules/save", { job: r.job, ...body });
    if (!res.ok) return setProblem(res.error || "Not saved.");
    setV(res);
    setEdit("");
    flashNote(note);
  };
  const toggle = (r: ScheduleRow, on: boolean) =>
    save(r, { trigger: r.trigger, enabled: on, schedule: r.raw ?? undefined }, `${r.step}: ${on ? "on" : "off"}.`);
  const open = (r: ScheduleRow) => { setProblem(""); setEdit(edit === r.job ? "" : r.job); setDraft(draftOf(r)); };
  const saveDraft = (r: ScheduleRow) => {
    if (!draft) return;
    save(r, { trigger: draft.trigger, enabled: r.enabled, schedule: draft.trigger === "time" ? scheduleOf(draft) : undefined },
      `${r.step}: trigger saved.`);
  };
  const approve = async (on: boolean) => {
    const res = await postJson<{ ok: boolean; error?: string }>("/stack/approvals", { auto_approve: on });
    if (!res.ok) return setProblem(res.error || "Not saved.");
    flashNote(on ? "New templates scoring 90 or more go live by themselves." : "Every new template now waits for your approval.");
    load();
  };

  const real = v ? (v.campaigns.some((c) => !c.demo) ? v.campaigns.filter((c) => !c.demo) : v.campaigns) : [];
  const pickCampaign = async (source: string) => {
    setProblem("");
    const res = await postJson<SchedulesView & { ok: boolean; error?: string }>("/stack/schedules/source", { source });
    if (!res.ok) return setProblem(res.error || "Not saved.");
    setV(res);
    flashNote(`Schedules now run on ${res.campaigns.find((c) => c.id === source)?.name ?? "this campaign"}.`);
  };

  return (
    <div className="u-page" style={{ maxWidth: 1240 }}>
      <PageHead title="Schedules" sub="Each step starts at a set time, or when the previous step completes."
        actions={v ? (
          <select className="u-input u-sel" aria-label="Campaign" value={v.source} onChange={(e) => pickCampaign(e.target.value)}>
            {real.some((c) => c.id === v.source) ? null : <option value={v.source}>— choose a campaign —</option>}
            {real.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        ) : null} />
      {problem ? <div style={{ marginBottom: 14 }}><ErrorBox title="Not saved" detail={problem} /></div> : null}
      {error ? <ErrorBox title="Schedules could not be loaded" detail={error} /> : !v ? <div className="u-card"><Loading rows={8} /></div> : (
        <div className="u-stack">
          {v.clock_text ? <div className="u-note warn" data-testid="clock-off">{v.clock_text}</div> : null}
          <div className="u-card">
            <div className="u-scroll">
              <table className="u-table" data-testid="schedule-table">
                <thead><tr><th>Step</th><th>Trigger</th><th>Schedule</th><th>Next run</th><th>Enabled</th><th aria-label="Change" /></tr></thead>
                <tbody>
                  {v.rows.map((r) => (
                    <Fragment key={r.job}>
                      <tr className={r.demo ? "sel" : undefined}>
                        <td><b className="u-ink">{r.step}</b></td>
                        <td>{r.trigger === "after" ? "After previous step" : "Time"}</td>
                        <td>{r.schedule}</td>
                        <td className="u-small u-muted">{r.next}</td>
                        <td>{r.demo ? <span className="u-pill accent">One time</span>
                          : <Switch label={`${r.step} on or off`} checked={r.enabled} onChange={(on) => toggle(r, on)} />}</td>
                        <td>{r.demo ? null : <button type="button" className="u-btn sm" aria-expanded={edit === r.job} onClick={() => open(r)}>Change</button>}</td>
                      </tr>
                      {edit === r.job && draft ? (
                        <tr className="u-sched-edit">
                          <td colSpan={6}>
                            <div className="u-sched-form">
                              {/* a div, not a label: a label would rename the first button inside it */}
                              <div className="grp"><span aria-hidden="true">Trigger</span>
                                <Seg label="Trigger" value={draft.trigger} onChange={(t) => setDraft({ ...draft, trigger: t })}
                                  options={[{ value: "time", label: "Time" },
                                    { value: "after", label: "After previous step", disabled: !r.can_follow }]} />
                              </div>
                              {draft.trigger === "time" ? (
                                <>
                                  <label>When
                                    <select className="u-input" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as Kind })}>
                                      <option value="weekdays">Weekdays at</option>
                                      <option value="daily">Every day at</option>
                                      <option value="minutes">Every few minutes</option>
                                    </select>
                                  </label>
                                  {draft.kind === "minutes" ? (
                                    <label>Minutes
                                      <input className="u-input" type="number" min={1} max={1439} value={draft.every}
                                        onChange={(e) => setDraft({ ...draft, every: Number(e.target.value) || 1 })} style={{ width: 90 }} />
                                    </label>
                                  ) : (
                                    <label>Time
                                      <input className="u-input" type="time" value={draft.start} onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
                                    </label>
                                  )}
                                </>
                              ) : <span className="u-small u-muted" style={{ alignSelf: "center" }}>Starts as soon as the step before it completes.</span>}
                              <div className="u-row">
                                <button type="button" className="u-btn primary sm" onClick={() => saveDraft(r)}>Save</button>
                                <button type="button" className="u-btn sm" onClick={() => setEdit("")}>Cancel</button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="u-grid2">
            <Card title="Trigger types">
              <ul className="u-checks" style={{ display: "grid" }}>
                <li className="todo"><span className="mk" aria-hidden="true">⏱</span><span className="grow"><b className="u-ink">Time</b>
                  <div className="u-small u-muted">A fixed time or interval, for example weekdays at 07:00</div></span></li>
                <li className="todo"><span className="mk" aria-hidden="true">→</span><span className="grow"><b className="u-ink">After previous step</b>
                  <div className="u-small u-muted">Starts as soon as the previous step completes</div></span></li>
              </ul>
            </Card>
            <Card title="Approval rules">
              <div className="u-rkv" style={{ marginTop: 6 }}>
                <span>New template from Claude</span>
                <span className="u-row" style={{ gap: 8 }}>
                  <Switch label="Auto-approve at score 90 or above" checked={v.approvals.auto_approve} onChange={approve} />Auto-approve at score 90 or above
                </span>
                <span>Interested reply</span>
                <span className="u-row" style={{ gap: 8 }} title={v.approvals.locked_why}>
                  <Switch label="Auto-reply" checked={false} disabled onChange={() => {}} />Auto-reply (off: sent to you)
                </span>
                <span>Spend above limit</span>
                <span className="u-row" style={{ gap: 8 }} title={v.approvals.locked_why}>
                  <Switch label="Allow spend above limit" checked={false} disabled onChange={() => {}} />Allow (off: pause and ask)
                </span>
              </div>
              <div className="u-small u-muted" style={{ marginTop: 10 }}>{v.approvals.locked_why}</div>
            </Card>
          </div>
          {v.later.count ? <div className="u-grid3"><LaterTile count={v.later.count} why={v.later.why} /></div> : null}
        </div>
      )}
    </div>
  );
}
