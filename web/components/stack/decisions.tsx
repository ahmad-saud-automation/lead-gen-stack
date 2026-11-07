"use client";

/* Home's "Needs your decision" and "System health, today" cards (build session 3), from
 * /api/stack/decisions: interested replies, templates waiting for approval, and any issue
 * the health agent escalated. Each item has the button that opens it. */

import Link from "next/link";

import { Card } from "@/components/u";
import type { DecisionsView } from "@/lib/stack-types";

export function NeedsDecision({ d }: { d: DecisionsView }) {
  return (
    <Card title="Needs your decision" sub={d.decisions.length ? "Each item opens where you decide." : undefined}>
      {d.decisions.length ? (
        <ul className="u-checks" data-testid="decisions" style={{ display: "grid" }}>
          {d.decisions.map((x, i) => (
            <li key={i} className="no">
              <span className="mk" aria-hidden="true">!</span>
              <span className="grow" style={{ minWidth: 180 }}>{x.text}</span>
              <Link className="u-btn sm" href={x.href}>{x.button}</Link>
            </li>
          ))}
        </ul>
      ) : <p className="u-muted">Nothing is waiting for you.</p>}
    </Card>
  );
}

export function HealthToday({ d }: { d: DecisionsView }) {
  const h = d.health;
  return (
    <Card title="System health, today" right={<Link className="u-btn sm" href="/health">Open Health</Link>}>
      <ul className="u-checks" style={{ display: "grid" }}>
        <li className="todo"><span className="mk">{h.issues}</span><span className="grow">Issues detected</span></li>
        <li className="ok"><span className="mk">{h.resolved}</span><span className="grow">Resolved automatically</span></li>
        <li className={h.waiting ? "no" : "ok"}><span className="mk">{h.waiting}</span><span className="grow">Waiting for you</span></li>
      </ul>
    </Card>
  );
}

const CHAIN: { href: string; label: string; key: keyof DecisionsView["counts"]; sub: string }[] = [
  { href: "/find", label: "1 · Find email", key: "emails", sub: "emails found" },
  { href: "/research", label: "2 · Website research", key: "websites", sub: "websites found" },
  { href: "/ice", label: "3 · Ice breakers", key: "icebreakers", sub: "written" },
  { href: "/email", label: "4 · Email template", key: "icebreakers", sub: "ready to send" },
  { href: "/send", label: "5 · Sending", key: "sent", sub: "sent (test mode)" },
  { href: "/replies", label: "6 · Replies", key: "replies", sub: "replies" },
];

/** Home's Pipeline card: Demo firms that have completed each step. */
export function PipelineCard({ d }: { d: DecisionsView }) {
  return (
    <Card title="Pipeline" sub={`${d.name ?? "Demo firms"}: leads that have completed each step, out of ${d.counts.leads}.`}>
      <div className="u-chain">
        {CHAIN.map((c) => (
          <Link key={c.href} className={d.counts[c.key] ? "u-cst done" : "u-cst"} href={c.href}>
            <div className="h">{c.label}</div>
            <div className="v">{d.counts[c.key]}</div>
            <div className="s">{c.key === "replies" && d.counts.replies ? `${d.counts.interested} interested`
              : c.key === "sent" && d.demo === false ? "pushed to Draft" : c.sub}</div>
          </Link>
        ))}
      </div>
    </Card>
  );
}
