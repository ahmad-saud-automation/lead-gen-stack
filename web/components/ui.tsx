/* Shared display pieces, taken from the Fabrikam View shell (via Icebreaker Studio) so all three
 * apps look the same.
 *
 * One card shape, one table, one chip, used on every page, so the eye learns the shape once.
 *
 * The colour rule is carried over: RED AND GREEN ONLY EVER APPEAR ON A JUDGEMENT — a lane too
 * small to read, a field map that will be refused. A plain count is shown in ink however small
 * it is.
 */

import type { ReactNode } from "react";

export function Band({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <>
      <div className="bandhead">
        <span className="lbl">{title}</span>
        <span className="rule" />
      </div>
      {children}
    </>
  );
}

export function Card({
  title,
  label,
  children,
  foot,
  className,
}: {
  title?: string;
  label?: ReactNode;
  children: ReactNode;
  foot?: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ? `card ${className}` : "card"}>
      {title ? (
        <header>
          <h3>{title}</h3>
          {label ? <span className="lbl">{label}</span> : null}
        </header>
      ) : null}
      <div className="body">{children}</div>
      {foot ? <div className="foot">{foot}</div> : null}
    </div>
  );
}

export function Tile({
  label,
  title,
  value,
  unit,
  chips,
  foot,
}: {
  label: string;
  title: string;
  value: ReactNode;
  unit?: ReactNode;
  chips?: ReactNode;
  foot?: ReactNode;
}) {
  return (
    <div className="card">
      <div className="tile">
        <div className="top">
          <span className="lbl">{label}</span>
        </div>
        <h3>{title}</h3>
        <div className="big">
          {value}
          {unit ? <small> {unit}</small> : null}
        </div>
        {chips ? <div className="chiprow">{chips}</div> : null}
      </div>
      {foot ? <div className="foot">{foot}</div> : null}
    </div>
  );
}

export function Chip({ tone, children }: { tone?: "up" | "down" | "warn"; children: ReactNode }) {
  return <span className={tone ? `chip ${tone}` : "chip"}>{children}</span>;
}

/** A yes/no light. `on` green, off grey — never red, because "off" is usually a choice. */
export function Dot({ on, title }: { on: boolean; title?: string }) {
  return <span className={on ? "dot y" : "dot n"} title={title} />;
}

export type Col<T> = {
  key: string;
  head: ReactNode;
  align?: "l" | "r";
  render: (row: T) => ReactNode;
};

export function StatTable<T>({
  cols,
  rows,
  rowKey,
  compact,
  empty = "Nothing to show yet.",
}: {
  cols: Col<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  compact?: boolean;
  empty?: string;
}) {
  if (rows.length === 0) return <div className="empty">{empty}</div>;
  return (
    <div className="scroll-x">
      <table className={compact ? "stat compact" : "stat"}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={c.align === "l" ? "l" : undefined}>
                {c.head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {cols.map((c) => (
                <td key={c.key} className={c.align === "l" ? "l" : undefined}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One labelled control inside a `.form-grid`. The caption is the theme's small mono label;
 *  the hint underneath says what the setting does, in the words of the person who set it. */
export function Field({
  label,
  hint,
  wide,
  children,
}: {
  label: string;
  hint?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <label className={wide ? "span-all" : undefined}>
      <span>{label}</span>
      {children}
      {hint ? <small className="hint">{hint}</small> : null}
    </label>
  );
}

export type CheckTone = "ok" | "warn" | "fail";
export type CheckItem = { tone: CheckTone; text: ReactNode };

const MARK: Record<CheckTone, string> = { ok: "✓", warn: "!", fail: "✕" };

/** A list of findings, each marked. `fail` is something that WILL stop a run; `warn` is worth
 *  reading but does not. Never mark a note `fail` to make it louder. */
export function Checks({ items }: { items: CheckItem[] }) {
  return (
    <ul className="checks">
      {items.map((c, i) => (
        <li key={i} className={c.tone}>
          <span className="mk" aria-hidden="true">{MARK[c.tone]}</span>
          <span className="t">{c.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** A segmented choice: two or three options, one of them on. */
export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === value ? "on" : undefined}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div style={{ display: "grid", gap: 10 }} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: i === 0 ? 34 : 18 }} />
      ))}
    </div>
  );
}

/** A tab read from a local file (`local_tabs` in Settings) rather than the live sheet. Every
 *  count on the screen is that snapshot's, so it is said up front, never discovered later. */
export function SnapshotNote({ tab, path }: { tab: string; path?: string }) {
  return (
    <ErrorBox
      soft
      title={`Tab ${tab} is being read from a local file, not the live sheet`}
      detail={
        <>
          <code>{path}</code>. What this screen shows is that snapshot. Clear <code>local_tabs</code>{" "}
          in Settings to go back to the sheet.
        </>
      }
    />
  );
}

/** An error says what failed and what to do about it. "Something went wrong" tells nobody
 *  anything at 11pm when the engine is simply not running. */
export function ErrorBox({ title, detail, soft }: { title: string; detail?: ReactNode; soft?: boolean }) {
  return (
    <div className={soft ? "errorbox soft" : "errorbox"} role="alert">
      <b>{title}</b>
      {detail}
    </div>
  );
}
