/* The plain words the V5 screens use (docs/UX-REDESIGN.md §5). Engine names stay in the engine;
 * every screen translates through here, so a word is changed in one place. */

/* ── filter operators (core/rules.py OPS) ── */
export const OP_WORDS: Record<string, string> = {
  equals: "is",
  not_equals: "is not",
  contains: "contains",
  not_contains: "does not contain",
  starts_with: "starts with",
  ends_with: "ends with",
  gt: "is more than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  between: "is between",
  in: "is one of",
  not_in: "is not one of",
  is_blank: "is empty",
  is_not_blank: "is not empty",
  older_than_days: "is older than (days)",
  matches: "matches a pattern (advanced)",
};
/** Most-used first, the advanced one last. */
export const OP_ORDER = [
  "equals", "not_equals", "between", "gte", "lte", "gt", "lt", "in", "not_in", "contains",
  "not_contains", "starts_with", "ends_with", "is_blank", "is_not_blank", "older_than_days", "matches",
];
export const LIST_OPS = new Set(["in", "not_in"]);
export const NUM_OPS = new Set(["gt", "gte", "lt", "lte", "older_than_days"]);

/* ── the engine's 31 fields (core/fieldmap.py FIELDS), in plain words and groups ── */
export type FieldWord = { name: string; hint: string; group: string };
export const FIELD_GROUPS = ["About the company", "About the person", "About the email", "Keeping track"] as const;
export const WRITTEN_GROUP = "Results the app writes";

export const FIELD_WORDS: Record<string, FieldWord> = {
  company_name: { name: "Company name", hint: "Needed", group: "About the company" },
  website: { name: "Website", hint: "Without it the app cannot guess addresses", group: "About the company" },
  reg_number: { name: "Company number", hint: "Optional · spots the same firm twice", group: "About the company" },
  employees: { name: "Staff count", hint: "Optional · for filters", group: "About the company" },
  industry: { name: "Industry", hint: "Optional · for filters", group: "About the company" },
  trading_years: { name: "Years trading", hint: "Optional · for filters", group: "About the company" },
  phone: { name: "Phone", hint: "Optional", group: "About the company" },
  address: { name: "Address", hint: "Optional · the town is taken from it", group: "About the company" },
  region: { name: "Region", hint: "Optional · for filters", group: "About the company" },
  contact_name: { name: "Person to email", hint: "Their full name", group: "About the person" },
  contact_first: { name: "First name", hint: "Worked out from the full name if missing", group: "About the person" },
  contact_last: { name: "Last name", hint: "Worked out from the full name if missing", group: "About the person" },
  job_title: { name: "Job title", hint: "Also sent to Instantly", group: "About the person" },
  seniority_rank: { name: "Seniority", hint: "If set, the app trusts it to pick the best person", group: "About the person" },
  contact_age: { name: "Age", hint: "Breaks ties: the oldest director first", group: "About the person" },
  found_email: { name: "Email already found", hint: "Used first — the cheapest source", group: "About the email" },
  send_gate: { name: "OK to send?", hint: "Must say “yes” before anything is sent", group: "About the email" },
  icebreaker: { name: "Ice breaker", hint: "The line Icebreaker Studio wrote", group: "About the email" },
  reference_email: { name: "Reference email", hint: "Kept for reference, never emailed", group: "About the email" },
  gateway_provider: { name: "Email filter (Mimecast…)", hint: "Lets the app hold firms behind strict filters", group: "About the email" },
  row_key: { name: "Unique ID", hint: "One per row, never repeats", group: "Keeping track" },
  status: { name: "Done / not done", hint: "Blank = not done yet", group: "Keeping track" },
  campaign_tag: { name: "Campaign tag", hint: "Optional · for filters", group: "Keeping track" },
  final_status: { name: "Final result", hint: "", group: WRITTEN_GROUP },
  email_source: { name: "Where the email came from", hint: "", group: WRITTEN_GROUP },
  email_type: { name: "Email type", hint: "", group: WRITTEN_GROUP },
  verification_status: { name: "Check result", hint: "", group: WRITTEN_GROUP },
  mv_date: { name: "Date checked", hint: "", group: WRITTEN_GROUP },
  alternate_emails: { name: "Other addresses found", hint: "", group: WRITTEN_GROUP },
  campaign_type: { name: "Campaign Type", hint: "", group: WRITTEN_GROUP },
  contact_2_email: { name: "Second person's email", hint: "", group: WRITTEN_GROUP },
};

export const fieldName = (f: string): string => FIELD_WORDS[f]?.name ?? f;

/* ── a campaign's filters as one sentence (the wizard's Review) ── */
type RuleLike = { field?: string; op?: string; value?: unknown };
function clauseWords(c: RuleLike): string {
  const f = fieldName(c.field ?? "").trim() || "?";
  const op = OP_WORDS[c.op ?? "equals"] ?? c.op ?? "";
  if (c.op === "is_blank" || c.op === "is_not_blank") return `${f} ${op}`;
  if (c.op === "between" && Array.isArray(c.value)) return `${f} is between ${c.value[0]} and ${c.value[1]}`;
  const v = Array.isArray(c.value) ? c.value.join(", ") : String(c.value ?? "");
  return `${f} ${op} ${v || "…"}`;
}
export function rulesSentence(rules: { all?: RuleLike[]; any?: RuleLike[]; none?: RuleLike[] } | undefined): string {
  const parts: string[] = [];
  if (rules?.all?.length) parts.push(rules.all.map(clauseWords).join(", and "));
  if (rules?.any?.length) parts.push(`at least one of: ${rules.any.map(clauseWords).join(" / ")}`);
  if (rules?.none?.length) parts.push(`never where ${rules.none.map(clauseWords).join(" or ")}`);
  return parts.join("; ");
}

/* ── what happened to a lead (core/pipeline.py statuses) ── */
export const RESULT_WORDS: Record<string, { text: string; tone: "good" | "warn" | "bad" | undefined }> = {
  email_found: { text: "Email found", tone: "good" },
  email_not_found: { text: "No email found", tone: undefined },
  no_website: { text: "No website to guess from", tone: undefined },
  hold_security_gateway: { text: "Held — strict email filter", tone: "warn" },
  pushed: { text: "Sent to Instantly", tone: "good" },
  /* a Finding Recipe's outcomes (core/recipe.py). None of these can be sent. */
  check_by_hand: { text: "Found — please check by hand", tone: "warn" },
  email_failed_check: { text: "Found, but failed the check — never sent", tone: "warn" },
  skipped_no_person: { text: "Skipped — nobody on this row to try", tone: undefined },
  skipped_by_rule: { text: "Skipped — your rule said to leave it", tone: undefined },
};
export const resultWord = (s: string) => RESULT_WORDS[s] ?? { text: s.replace(/_/g, " "), tone: undefined };

/* ── a Finding Recipe, in plain words (core/recipe.py) ──
 * The engine's names stay in the engine. A recipe is "how it finds emails": an ordered
 * list of PEOPLE to try, each with ordered WAYS to find them. */

export const RECIPE_WORDS = {
  one: "finding recipe",
  many: "finding recipes",
  person: "person",
  people: "who to email, in order",
  way: "way to find them",
  ways: "ways to find them",
  check: "check",
  stop: "when to stop",
  write: "write the result to",
  limits: "limits",
} as const;

/** The four ways of finding one person. */
export const METHOD_WORDS: Record<string, { name: string; hint: string }> = {
  guess_patterns: {
    name: "Guess from the website",
    hint: "Builds first@, first.last@, f.last@ from this person’s name and checks each one. Free until a check.",
  },
  icypeas_domain: {
    name: "Ask Icypeas (by website)",
    hint: "Sends the name and the website to Icypeas. 1 credit, charged only if it finds somebody.",
  },
  icypeas_company: {
    name: "Ask Icypeas (by company name)",
    hint: "For firms with no website. It can answer with an address at a different business, so a domain that does not look right is marked “check by hand”.",
  },
  use_as_is: {
    name: "Use the address already in a column",
    hint: "No searching. Takes the address that is already on the row and checks it.",
  },
};
export const METHOD_ORDER = ["guess_patterns", "icypeas_domain", "icypeas_company", "use_as_is"];
export const methodWord = (m: string) => METHOD_WORDS[m]?.name ?? m.replace(/_/g, " ");

/** What MillionVerifier’s answer means for one address. */
export const VERIFY_WORDS: Record<string, { name: string; hint: string }> = {
  must_pass: { name: "Only keep it if the check passes", hint: "The safe choice. Anything that fails is thrown away." },
  write_failed: { name: "Write it even if the check fails", hint: "Marked “failed the check”. It is written to the sheet so you can see it, and can never be sent." },
  no_check: { name: "Do not check it", hint: "Saves the check, but an unchecked address can never be sent either." },
};
export const verifyWord = (v: string) => VERIFY_WORDS[v]?.name ?? v.replace(/_/g, " ");

export const PATTERN_WORDS: Record<string, string> = {
  careful: "Careful — 3 formats (first@, first.last@, f.last@)",
  thorough: "Thorough — 6 formats (more checks, more cost)",
};

export const STOP_WORDS: Record<string, string> = {
  first_pass: "Stop at the first email that passes",
  try_all_keep_best: "Try everyone, then keep the best",
};

export const WRITE_WHEN_WORDS: Record<string, string> = {
  always: "Every row, straight away",
  on_find: "Only when something is found",
};

/** Which name to take out of a cell that holds several, comma separated. Mirrors
 *  `core/recipe.py: pick_name` — "whole" is the default and returns the cell untouched. */
export const NAME_PICK_WORD: Record<string, string> = {
  whole: "the whole cell",
  "1st": "the 1st name in the cell",
  "2nd": "the 2nd name in the cell",
  "3rd": "the 3rd name in the cell",
};

export function pickName(cell: string | undefined, which?: string): string {
  const s = String(cell ?? "").trim();
  if (!s || !which || which === "whole") return s;
  const i: number | undefined = { "1st": 0, "2nd": 1, "3rd": 2 }[which];
  if (i === undefined) return s;
  const parts = s.split(",").map((x) => x.trim()).filter(Boolean);
  return parts[i] ?? "";
}

/** One person rung as a sentence, for the collapsed ladder.
 *  `how` arrives either as the saved ways ({method, …}) or, from the recipe LIST endpoint,
 *  as the method names alone — both are accepted so one sentence serves every screen. */
export function personSentence(p: {
  label?: string;
  name_from?: string | string[];
  name_pick?: string;
  address_from?: string;
  only_if_same_as?: string[];
  how?: ({ method: string } | string)[];
}): string {
  const cols = Array.isArray(p.name_from) ? p.name_from.filter(Boolean) : (p.name_from ? [p.name_from] : []);
  const which = p.name_pick && p.name_pick !== "whole" ? `${NAME_PICK_WORD[p.name_pick] ?? p.name_pick} of ` : "";
  const only = (p.only_if_same_as ?? []).filter(Boolean);
  const onlyIf = only.length ? `, only if they are in ${only.join(" / ")}` : "";
  const where = cols.length
    ? `name from ${which}${cols.join(", then ")}${onlyIf}`
    : p.address_from
      ? `the address in ${p.address_from}${onlyIf}`
      : "no column picked yet";
  const ways = (p.how ?? []).map((w) => methodWord(typeof w === "string" ? w : w.method)).join(" → ");
  return ways ? `${where} · ${ways}` : where;
}

/* ── where an email came from (core/pipeline.py: "endole", "pattern_<shape>", a finder name) ── */
export function sourceWord(s: string | undefined): string {
  const v = String(s || "");
  if (!v) return "";
  if (v === "endole") return "already in your sheet";
  if (v.startsWith("pattern_")) return `guessed from the website (${v.slice(8).replace(/_/g, ".")}@)`;
  if (v.includes("icypeas")) return "found by Icypeas";
  if (v.includes("anymail")) return "found by Anymailfinder";
  return v.replace(/_/g, " ");
}

/* ── dates ── */
export function whenWords(ts: string): string {
  // "2026-10-04 17:32:14" -> "Today 17:32" / "Yesterday 17:32" / "Sat 4 Oct 17:32"
  if (!ts) return "";
  const d = new Date(ts.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return ts;
  const hm = ts.slice(11, 16);
  const today = new Date();
  // local calendar days: the engine writes local time, and toISOString() would shift to UTC
  const day = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  if (day(d) === day(today)) return `Today ${hm}`;
  if (day(d) === day(y)) return `Yesterday ${hm}`;
  return `${d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })} ${hm}`;
}
