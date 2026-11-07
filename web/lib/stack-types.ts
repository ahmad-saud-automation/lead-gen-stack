/* Shapes of the /api/stack/* answers (webapp/server.py + core/stack_view.py), build session 1. */

export type StepPill = { value: string; label: string; tone: "good" | "warn" | "bad" | "accent" | "" };

export type Picker = { id: string; name: string; demo: boolean; runnable: boolean; why: string };

type Wrapped = { error?: string; name: string; demo: boolean; runnable: boolean; why: string };

export type LeadRow = {
  key: string; company: string; person: string; title: string; website: string; email: string;
  steps: Record<string, StepPill>; filters: string[];
};
export type LeadsView = Wrapped & { rows: LeadRow[]; filters: { id: string; label: string; count: number }[]; total: number; show: number };

export type FactLine = { kind: string; text: string; url: string };
export type Page = { url: string; kind: string; title: string };

export type LeadRecord = {
  error?: string;
  key: string; company: string; person: string; title: string; email: string; website: string; next: string;
  steps: (StepPill & { n: number; name: string; column: string })[];
  research: null | { status: StepPill; detail: string; checked: string; facts: FactLine[]; pages: Page[] };
  find: null | { status: StepPill; email: string; contact: string; rung: string; method: string; checks: number;
    finder_calls: number; steps: { kind: string; detail: string }[] };
  history: string[];
};

export type ResearchRow = { key: string; company: string; host: string; status: StepPill; chips: string[]; detail: string;
  facts: FactLine[]; pages: Page[]; checked: string };
export type ResearchView = Wrapped & { rows: ResearchRow[]; to_research: number; tally: Record<string, number>; values: StepPill[] };

export type Rung = { n: number; name: string; hint: string; found: number };
export type FindView = Wrapped & {
  recipe: { id: string; name: string };
  processed: number; ready: number; no_website: number; found: number; from_sheet: number; found_new: number;
  company_address: number; not_found: number; checks: number; finder_calls: number; would_cost: number;
  values: StepPill[]; rungs: Rung[];
};

export type RunResult = { ok: boolean; error?: string; processed?: number; found?: number; would_cost?: number; skipped_recent?: number };

/* ── build session 2: steps 3–6 ── */

export type Later = { count: number; why: string };
export type ModeBox = { test_mode: boolean; title: string; text: string; can_change: boolean };

export type IceRung = { id: string; name: string; source: string; on: boolean; fact: string; implication: string;
  needs?: string; used?: number };
export type RuleSet = { id: string; name: string; template: string; shared_ground: string[]; rungs: IceRung[];
  default: { fact: string; implication: string }[]; default_used?: number };
export type IceLead = { key: string; company: string; rung: string; line: string; status: StepPill; sent: boolean };
export type IceCounts = Record<"written" | "waiting" | "no_facts" | "failed" | "no_email" | "not_researched", number>;
export type IceOverview = {
  campaigns: { id: string; name: string; demo: boolean; runnable: boolean; why: string; ruleset: string; counts: IceCounts }[];
  later: Later;
  rulesets: { id: string; name: string; rungs: number; on: number; used_by: string[]; written: number }[];
};
export type IceCamp = { error?: string; name: string; demo: boolean; ruleset: RuleSet; sources: { id: string; label: string }[];
  leads: IceLead[]; counts: IceCounts; preview: { key: string; company: string }[] };
export type IcePreview = { error?: string; key: string; company: string; rung: string; fact: string; line: string; saved: boolean; note?: string };
export type IceRunResult = { ok: boolean; error?: string; processed?: number; written?: number; default?: number; no_facts?: number; failed?: number; skipped_sent?: number };

export type ScoreCheck = { key: string; name: string; points: number; ok: boolean };
export type ScoreMistake = { name: string; why: string; cost: number };
export type Template = { id: number; name: string; subject: string; body: string; state: StepPill; share: number; score: number;
  sent: number; replies: number; request: string; approved_by: string; blocked: boolean; unapproved: string[];
  checks: ScoreCheck[]; mistakes: ScoreMistake[]; passed: number; of: number };
export type TemplateRequest = { id: number; kind: string; instructions: string; state: StepPill; created: string };
export type EmailOverview = {
  campaigns: { id: string; name: string; demo: boolean; runnable: boolean; why: string; live: number; drafts: number; top_score: number }[];
  later: Later;
};
export type EmailCamp = { error?: string; name: string; demo: boolean; templates: Template[]; requests: TemplateRequest[];
  kinds: { id: string; label: string }[]; live: number; drafts: number; top_score: number;
  preview: { key: string; company: string }[]; auto_approve_at: number; approved_figures: string[] };
export type EmailPreview = { error?: string; to: string; contact: string; subject: string; body: string; note: string };
export type ScoreResult = { score: number; blocked: boolean; unapproved: string[]; checks: ScoreCheck[]; mistakes: ScoreMistake[];
  passed: number; of: number; words: number };

export type SendRow = { source?: string; campaign: string; sending_campaign: string; queued: number; held: number; sent: number;
  sent_today: number; daily_limit: number; runnable: boolean; demo?: boolean };
export type SendLead = { key: string; company: string; email: string; status: StepPill; reason: string; template: string };
export type SendView = { error?: string; rows: SendRow[]; leads: SendLead[]; can_send: number; live_templates: number;
  later: Later; test_mode: boolean; demo: boolean; name: string };
export type SendResult = { ok: boolean; error?: string; pushed?: number; held?: number; failed?: number; over_limit?: number };

export type Reply = { id: number; key: string; sender: string; company: string; email: string; message: string; received: string;
  category: StepPill; action: string; handled: boolean; campaign: string; changed: boolean };
export type RepliesView = { error?: string; name: string; demo: boolean; replies: Reply[]; counts: Record<string, number>;
  pushed: number; categories: StepPill[] };

export type SourceItem = {
  id: string; kind: "demo" | "upload" | "local" | "sheet"; name: string; sub: string; campaigns: number;
  access: { label: string; tone: string }; href: string; action: string; detail?: string;
  tabs?: { tab: string; campaigns: number; href: string }[];
};
export type SourcesView = { sources: SourceItem[]; columns: string[]; hidden?: number };

/* build session 3: Schedules, Health, Live demo, Home decisions */
export type RawSchedule = { kind: "minute" | "hourly" | "daily" | "weekly"; every: number; start: string; end: string; days: string[] };
export type ScheduleRow = { job: string; step: string; trigger: "time" | "after"; schedule: string; next: string; enabled: boolean;
  demo: boolean; raw: RawSchedule | null; can_follow: boolean };
export type Approvals = { auto_approve: boolean; auto_reply: boolean; allow_spend: boolean; locked: string[]; locked_why: string };
export type SchedulesView = { rows: ScheduleRow[]; campaigns: { id: string; name: string; demo?: boolean }[]; source: string; later: Later; approvals: Approvals;
  clock_on: boolean; clock_text: string };

export type Summary = { title: string; lines: string[]; issues: number; resolved: number; waiting: number; made?: string };
export type HealthTiles = { issues: number; resolved: number; waiting: number };
export type Incident = { id: number; time: string; day: string; step: string; issue: string; action: string; result: "resolved" | "escalated" | "open" };
export type HealthView = { source?: string; tiles: HealthTiles; log: Incident[]; allowed: string[]; escalated: string[]; summary: Summary | null;
  last_check: string; clock_on: boolean; clock_text: string };

export type DemoEvent = { t: string; text: string; tone: "" | "good" | "bad" };
/** `text`: what the step PRODUCED ("12 in → 8 websites read · 4 no site"), empty while pending. */
export type DemoStep = { key: string; label: string; n: number; state: "pending" | "run" | "done" | "waiting"; text?: string };
export type DemoLead = { key: string; company: string; website: StepPill; email: StepPill; ice: StepPill; template: string;
  sent: StepPill; reply: StepPill };
export type DemoRun = { id: string; state: "scheduled" | "running" | "done" | "waiting" | "stopped" | "failed" | "interrupted";
  step: number; due: string; seconds_left: number; message: string; events: DemoEvent[]; started: string; finished: string };
export type DemoStatus = { run: DemoRun | null; chain: DemoStep[]; leads: DemoLead[]; total: number; progress: number;
  source?: string; name?: string; demo?: boolean; error?: string;
  result: null | { seconds: number; leads: number; websites: number; emails: number; sent: number; interested: number;
    would_cost: number; summary: Summary | null } };

export type Decision = { kind: "reply" | "template" | "health"; text: string; href: string; button: string };
export type DecisionsView = { decisions: Decision[]; health: HealthTiles; presenting: boolean;
  source?: string; name?: string; demo?: boolean;
  counts: { leads: number; websites: number; emails: number; icebreakers: number; sent: number; replies: number; interested: number } };

export type SheetCheck = { ok: boolean; error?: string; title?: string; tab_count?: number; robot?: string;
  tabs?: { tab: string; columns: number; missing: string[]; matched: string[]; of: number }[] };
export type LocalCheck = { ok: boolean; error?: string; path?: string; name?: string; rows?: number; columns?: number;
  basics?: { matched: string[]; of: number }; missing?: string[]; clash?: string };
