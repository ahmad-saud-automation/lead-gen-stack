"use client";

/* A 6-step campaign's "The 6 steps" card (2026-11-07): what one run does, in order, the setting
 * each step uses and where to change it. A lead whose sheet row already has an email and an
 * ice breaker is not searched or researched: it goes straight to Sending. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, Note } from "@/components/u";
import { getJson } from "@/lib/client-api";
import type { PipelineSteps } from "@/lib/types";

export function PipelineStepsCard({ id }: { id: string }) {
  const [v, setV] = useState<PipelineSteps | null>(null);
  useEffect(() => {
    getJson<PipelineSteps>("/campaigns/pipeline_steps", { id }).then(setV).catch((e: Error) =>
      setV({ error: e.message, campaign: id, source: "", when: "", steps: [] }));
  }, [id]);

  return (
    <Card id="sec-steps" title="The 6 steps for this campaign"
      sub="One run does these in order, using the settings on this page and on each step's page.">
      {!v ? <p className="u-muted">Loading…</p> : v.error ? <Note tone="bad">{v.error}</Note> : (
        <>
          <ol className="u-stack" style={{ margin: 0, paddingLeft: 22, gap: 10 }}>
            {v.steps.map((s) => (
              <li key={s.key}>
                <b className="u-ink">{s.title}</b>
                <span className="u-muted"> · {s.setting}</span>{" "}
                <Link className="u-link" href={s.href}>Open</Link>
              </li>
            ))}
          </ol>
          <div style={{ marginTop: 12 }}>
            <Note>
              <b className="u-ink">A lead that already has an email and an ice breaker in the sheet</b> is not searched or
              researched: it goes straight to Sending. <b className="u-ink">When:</b> {v.when}.
            </Note>
          </div>
        </>
      )}
    </Card>
  );
}
