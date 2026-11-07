"use client";

/* V5 building blocks (styles in app/ux.css). One shape per job, so every page reads the same
 * way: a PageHead that says what the page is and holds its ONE main button, cards with a plain
 * title and a one-line explanation, switches with the consequence written under them. */

import Link from "next/link";
import { useState, type KeyboardEvent, type ReactNode } from "react";

export function PageHead({
  title,
  sub,
  back,
  actions,
}: {
  title: ReactNode;
  sub?: ReactNode;
  back?: { href: string; label: string };
  actions?: ReactNode;
}) {
  return (
    <>
      {back ? <Link className="u-back" href={back.href}>← {back.label}</Link> : null}
      <div className="u-head">
        <div>
          <h1>{title}</h1>
          {sub ? <p>{sub}</p> : null}
        </div>
        {actions ? <div className="u-row">{actions}</div> : null}
      </div>
    </>
  );
}

export function Card({
  title,
  sub,
  right,
  id,
  className,
  children,
}: {
  title?: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  id?: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={className ? `u-card ${className}` : "u-card"} id={id}>
      {title || right ? (
        <div className="u-card-head">
          <div>
            {title ? <h2 className="u-h2">{title}</h2> : null}
            {sub ? <p>{sub}</p> : null}
          </div>
          {right}
        </div>
      ) : null}
      {children}
    </div>
  );
}

export function Tile({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="u-tile">
      <div className="lbl">{label}</div>
      <div className="big">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  );
}

export type Tone = "good" | "warn" | "bad" | "live" | "test" | "attn" | undefined;

export function Pill({ tone, children }: { tone?: Tone; children: ReactNode }) {
  return <span className={tone ? `u-pill ${tone}` : "u-pill"}>{children}</span>;
}

export function Note({ tone, children }: { tone?: "good" | "warn" | "bad"; children: ReactNode }) {
  return <div className={tone ? `u-note ${tone}` : "u-note"}>{children}</div>;
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <input
      type="checkbox"
      role="switch"
      className="u-sw"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

/** A setting that is on or off, with what it does underneath in plain words. */
export function SwitchRow({
  title,
  desc,
  checked,
  onChange,
  disabled,
}: {
  title: string;
  desc?: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="u-sw-row">
      <div>
        <b>{title}</b>
        {desc ? <span className="d">{desc}</span> : null}
      </div>
      <Switch label={title} checked={checked} onChange={onChange} disabled={disabled} />
    </div>
  );
}

export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="u-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === value ? "on" : undefined}
          aria-pressed={o.value === value}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A labelled control. The label is a plain sentence-case caption, the hint one short line. */
export function Field({
  label,
  hint,
  bad,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  bad?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="u-f">
      <span className="lab">{label}</span>
      {children}
      {hint ? <span className={bad ? "hint bad" : "hint"}>{hint}</span> : null}
    </div>
  );
}

export type CheckRow = { ok: boolean | null; text: ReactNode; action?: ReactNode };

/** ✓ done · ✕ needs you · a number for a step not reached yet. */
export function Checklist({ items, numbered }: { items: CheckRow[]; numbered?: boolean }) {
  return (
    <ul className="u-checks">
      {items.map((it, i) => (
        <li key={i} className={it.ok === true ? "ok" : it.ok === false ? "no" : "todo"}>
          <span className="mk" aria-hidden="true">{it.ok === true ? "✓" : it.ok === false && !numbered ? "✕" : i + 1}</span>
          <span className="grow">{it.text}</span>
          {it.action}
        </li>
      ))}
    </ul>
  );
}

export function Progress({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="u-progress" role="progressbar" aria-valuenow={done} aria-valuemax={total}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="u-empty">
      <b>{title}</b>
      {children}
    </div>
  );
}

/** One numbered section of the campaign page: a number, a heading, the question it answers. */
export function Step({
  n,
  id,
  title,
  question,
  children,
}: {
  n: number;
  id: string;
  title: string;
  question: string;
  children: ReactNode;
}) {
  return (
    <div className="u-card u-step" id={id}>
      <span className="u-num">{n}</span>
      <div>
        <h2 className="u-h2">{title}</h2>
        <p className="q">{question}</p>
        {children}
      </div>
    </div>
  );
}

/** A list of short values (company names, websites): type and press Enter, ✕ to remove. */
export function TagList({
  values,
  onChange,
  placeholder,
  label,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
  label: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...values, ...parts.filter((p) => !values.includes(p))]);
    setDraft("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div className="u-taglist">
      {values.map((v) => (
        <span key={v}>
          {v}
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>✕</button>
        </span>
      ))}
      <input
        aria-label={label}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
      />
    </div>
  );
}
