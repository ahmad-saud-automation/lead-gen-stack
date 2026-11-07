"use client";

/* Section 4 — When. Edits the lane's `schedule` (core/schedules.py shape). The next runs come
 * from the engine's own maths (/api/schedules/preview), so what the screen promises is what
 * the clock does. Saved with the rest of the campaign; the page sends it to
 * /api/campaigns/schedule, which also creates or removes a Windows task. */

import { useEffect, useState } from "react";

import { Field, Note, Seg, Step, SwitchRow } from "@/components/u";
import { postJson } from "@/lib/client-api";
import type { LaneSchedule, SchedulePreview } from "@/lib/types";
import { whenWords } from "@/lib/words";

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const DAY_WORD: Record<string, string> = { MON: "Mon", TUE: "Tue", WED: "Wed", THU: "Thu", FRI: "Fri", SAT: "Sat", SUN: "Sun" };

export const DEFAULT_SCHEDULE: LaneSchedule = {
  enabled: false, via: "app", kind: "weekly", every: 1, start: "09:00", end: "",
  days: ["MON", "TUE", "WED", "THU", "FRI"], test_mode: true, anchor: "",
};

export function WhenSection({
  s,
  set,
  n = 4,
  pipeline = false,
}: {
  s: LaneSchedule;
  set: (patch: Partial<LaneSchedule>) => void;
  /** a 6-step campaign: every scheduled run is the full pipeline (Draft-only push), no test mode */
  pipeline?: boolean;
  /** the campaign page numbers this 5 (it has a Finding-recipe step); the wizard keeps 4 */
  n?: number;
}) {
  const [pv, setPv] = useState<SchedulePreview | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      postJson<SchedulePreview>("/schedules/preview", s).then(setPv).catch(() => setPv(null));
    }, 300);
    return () => clearTimeout(t);
  }, [s]);

  const ranged = s.kind === "minute" || s.kind === "hourly";
  const unit = { minute: "minutes", hourly: "hours", daily: "days", weekly: "weeks" }[s.kind];
  const toggleDay = (d: string) => set({ days: s.days.includes(d) ? s.days.filter((x) => x !== d) : DAYS.filter((x) => x === d || s.days.includes(x)) });

  return (
    <Step n={n} id="sec-when" title="When" question="Should it run by itself?">
      <SwitchRow title="Run by itself" desc={pipeline ? "Off = it only runs when you press Run now. On = the 6 steps run on this schedule (the campaign must be on)." : "Off = it only runs when you press Run."}
        checked={s.enabled} onChange={(v) => set(pipeline ? { enabled: v, test_mode: false } : { enabled: v })} />
      {s.enabled ? (
        <>
          <div className="u-fgrid two" style={{ marginTop: 6 }}>
            <Field label="How often">
              <span>
                <Seg label="How often" value={s.kind} onChange={(k) => set({
                  kind: k,
                  end: k === "minute" ? s.end || "17:30" : k === "hourly" ? s.end : "",
                  days: k === "weekly" && !s.days.length ? ["MON", "TUE", "WED", "THU", "FRI"] : s.days,
                })} options={[
                  { value: "daily", label: "Every day" },
                  { value: "weekly", label: "On chosen days" },
                  { value: "hourly", label: "Every few hours" },
                  { value: "minute", label: "Every few minutes" },
                ]} />
              </span>
            </Field>
            {pipeline ? (
              <Field label="Each scheduled run" hint="Spends email-check credits, up to “Most it may spend per run”.">
                <span className="u-ink">Runs all 6 steps on the next new leads, then adds them to the Draft Instantly campaign.</span>
              </Field>
            ) : (
              <Field label="Scheduled runs are" hint={s.test_mode ? "Nothing is spent or sent." : "Spends credits, up to the daily limit in Settings."}>
                <span>
                  <Seg label="Test or live" value={s.test_mode ? "test" : "live"} onChange={(v) => set({ test_mode: v === "test" })}
                    options={[{ value: "test", label: "Free tests" }, { value: "live", label: "Live (spends credits)" }]} />
                </span>
              </Field>
            )}
          </div>

          <div className="u-row" style={{ marginTop: 16, fontSize: 15, color: "var(--ink)" }}>
            {s.kind === "weekly" ? "At" : "Every"}
            {s.kind === "weekly" ? null : (
              <input className="u-input num" type="number" min={1} aria-label={`Every how many ${unit}`} value={s.every}
                onChange={(e) => set({ every: Math.max(1, Number(e.target.value) || 1) })} />
            )}
            {s.kind === "weekly" ? null : unit}
            {s.kind === "weekly" ? null : ranged ? " from " : " at "}
            <input className="u-input num" type="time" style={{ width: 120 }} aria-label="Start time" value={s.start} onChange={(e) => set({ start: e.target.value })} />
            {ranged ? (
              <>
                until
                <input className="u-input num" type="time" style={{ width: 120 }} aria-label="End time" value={s.end} onChange={(e) => set({ end: e.target.value })} />
              </>
            ) : null}
            {s.kind === "weekly" ? (
              <>
                , every
                <input className="u-input num" type="number" min={1} aria-label="Every how many weeks" value={s.every}
                  onChange={(e) => set({ every: Math.max(1, Number(e.target.value) || 1) })} />
                {s.every === 1 ? "week" : "weeks"}
              </>
            ) : null}
          </div>

          {s.kind !== "daily" ? (
            <div style={{ marginTop: 12 }}>
              <span className="u-small u-muted">{s.kind === "weekly" ? "On" : "Only on (none ticked = every day)"}</span>
              <div className="u-row" style={{ marginTop: 6 }}>
                {DAYS.map((d) => (
                  <label key={d} className="u-check">
                    <input type="checkbox" checked={s.days.includes(d)} onChange={() => toggleDay(d)} />
                    {DAY_WORD[d]}
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          <div className="u-fgrid two" style={{ marginTop: 16 }}>
            <Field label="Run it from" hint={pv?.windows_available === false
              ? "This engine is not on Windows, so only the app can run it."
              : "The app works on any server. Windows works even when the app is closed."}>
              <span>
                <Seg label="Run it from" value={s.via} onChange={(v) => set({ via: v })} options={[
                  { value: "app", label: "The app (recommended)" },
                  { value: "windows", label: "Windows", disabled: pv?.windows_available === false },
                ]} />
              </span>
            </Field>
          </div>

          <div style={{ marginTop: 14 }}>
            {pv?.problems.length ? (
              <Note tone="bad">{pv.problems.join(" · ")}</Note>
            ) : pv ? (
              <Note>
                <b className="u-ink">{pv.summary}</b>
                {pv.next.length ? <> · next runs: {pv.next.map((n) => whenWords(n)).join(" · ")}</> : null}
              </Note>
            ) : null}
          </div>
        </>
      ) : null}
    </Step>
  );
}
