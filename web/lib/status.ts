/* One campaign's status in one word, the same on every screen. */

import type { CampaignSummary } from "@/lib/types";

export type Status = { label: string; tone: "live" | "test" | "attn" | "good" | undefined; why?: string };

export function campaignStatus(l: Pick<CampaignSummary, "enabled" | "instantly_campaign_id" | "schedule">, issues = 0): Status {
  if (!l.enabled) return { label: "Off", tone: undefined };
  if (issues) return { label: "Needs you", tone: "attn", why: "its settings have a problem" };
  if (l.schedule?.problems?.length) return { label: "Needs you", tone: "attn", why: l.schedule.problems[0] };
  if (!l.instantly_campaign_id) return { label: "Needs you", tone: "attn", why: "no Instantly campaign chosen" };
  if (l.schedule?.active) {
    return l.schedule.test_mode ? { label: "Free tests", tone: "test", why: "runs by itself, spending nothing" }
      : { label: "Live", tone: "live", why: "runs by itself and spends credits" };
  }
  return { label: "On", tone: "good", why: "runs when you press Run" };
}

/** Where a run or push opens. One place, so the address can move without hunting for links. */
export const runHref = (id: string, tab?: string) => `/activity/${encodeURIComponent(id)}${tab ? `?tab=${tab}` : ""}`;
