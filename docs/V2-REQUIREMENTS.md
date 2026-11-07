# V2 Requirements — Lead Gen Automation Engine

**Status: PROPOSAL. Nothing is built. Awaiting approval.**
Written 2026-09-04. V1 backed up to
`_archive\lead gen automation engine - V1 BACKUP 2026-09-04` (174 files, 6,003,146 bytes, verified).

---

## PART 0 — Why V2 exists

V1 is a faithful port of the n8n **V7** workflow. V7 was built for **one Endole sheet, one
campaign, one fixed set of column names**. The Northwind campaign is the opposite: **one sheet, five
tabs, 42 columns, six campaigns, different column names**.

The engine is not broken. It is **hard-wired to the wrong shape**.

Four things are hard-coded that must become configuration:

| # | Hard-coded today | Where | Must become |
|---|---|---|---|
| 1 | One Instantly campaign | `config.json` → `instantly_campaign_id` | A Campaigns table, many campaigns, each with its own rules |
| 2 | 12 Instantly fields, 7 fixed labels | `core/instantly.py` → `build_payload`, `LABEL_COLUMNS` | Any field, any label, added from the UI |
| 3 | ~30 English column names guessed in code | `core/organize.py` → every `_get(...)` call | A Field Map per sheet, editable in the UI |
| 4 | 10 flat tabs, vanilla HTML | `webapp/` (1,110 lines) | A proper app shell with a campaign list |

---

## PART 1 — What the research confirmed

### 1.1 Instantly's API is far less restrictive than the engine assumes

`POST /api/v2/leads` accepts **19 fields**. The engine sends **12**.

| Field | Type | Engine sends it? |
|---|---|---|
| `campaign` | uuid | ✅ |
| `list_id` | uuid | ❌ |
| `email` | string | ✅ (required with `campaign`) |
| `first_name` | string | ✅ |
| `last_name` | string | ✅ |
| `company_name` | string | ✅ |
| **`job_title`** | string | ❌ **← Northwind has this column** |
| `phone` | string | ✅ |
| `website` | string | ✅ |
| `personalization` | string | ✅ (the icebreaker) |
| `lt_interest_status` | number | ❌ |
| `pl_value_lead` | string | ❌ |
| `assigned_to` | uuid | ❌ |
| `skip_if_in_workspace` | bool | ✅ |
| `skip_if_in_campaign` | bool | ✅ |
| `skip_if_in_list` | bool | ✅ |
| **`blocklist_id`** | uuid | ❌ **← the suppression gate** |
| `verify_leads_on_import` | bool | ❌ |
| `verify_leads_for_lead_finder` | bool | ❌ |
| `custom_variables` | object | ✅ (but only 7 fixed keys) |

**`custom_variables` rules, from the official docs:**
- Any key name is allowed.
- Values must be **string, number, boolean or null**.
- **No nested objects and no arrays.**
- Adding a new custom variable to one lead **updates the campaign schema**, so every other
  lead in that campaign can carry the same variable.

**Conclusion: the 7-label limit is self-imposed by our code, not by Instantly.**
Making labels dynamic is a config change, not an integration problem.

### 1.2 The declarative-node pattern (how n8n does it)

An n8n node is not code-per-form. It is a **JSON description**:

- `displayName`, `name`, `icon`, `description`
- a `properties[]` array — each entry has a `type` (`string`, `number`, `boolean`,
  `options`, `collection`) which decides **which input control the UI renders**
- `displayOptions.show` — conditionally reveals a field based on another field's value
- `credentials[]` — which secrets the step needs

The UI renders the form **from that JSON**. Adding a field means editing JSON, never HTML.

**This is exactly the pattern V2 should copy.** Our pipeline steps (Gateway, Endole, Pattern,
Icypeas, Anymailfinder, MillionVerifier, Icebreaker, Push, Write-back) become JSON-described
steps, and the settings UI is generated, not hand-written.

### 1.3 The import/mapping pattern every serious SaaS uses

**File → Map → Validate → Submit.**

- **Map** = auto-suggest a match for each of our internal fields, let the user override from a
  dropdown of the sheet's real headers, and show a live preview of 5 mapped rows.
- **Validate** = type checks, required-field checks, normalisation, with the error shown next
  to the field.

That "Map" screen is precisely what solves problem 3.

### 1.4 Background work

| Option | Fits |
|---|---|
| **APScheduler** | time-based triggers; can build triggers dynamically from database values, and persists jobs across restarts with a SQLAlchemy job store |
| **ARQ / RQ** | reliable queued work; ARQ runs hundreds of concurrent I/O-bound jobs in one worker with no process forking |
| **Celery** | most powerful, most complex — overkill here |
| FastAPI `BackgroundTasks` | trivial fire-and-forget only — what V1 uses today (raw `threading.Thread`) |

**Recommendation: APScheduler for the per-campaign schedule + a small in-process worker pool.**
No Redis, no extra service, keeps the "one `.bat` file" promise. Revisit only if we ever need
multiple machines.

---

## PART 2 — Problems in V1, in priority order

### P1 — One campaign only ⛔ blocks Northwind
`start_push()` reads a single `instantly_campaign_id` from `config.json`. Running a second
campaign means editing settings and re-running by hand.

### P2 — Labels are frozen ⛔ blocks the decision agent
`LABEL_COLUMNS` is a 5-item Python tuple. Adding an 8th label is a code edit plus a release.

### P3 — Column names are guessed in code ⛔ blocks the Northwind sheet
`organize.py` guesses ~30 English header names. The Northwind sheet does not use them.
**Concrete failure: STATE.md says `Director Names` was deliberately removed from the Northwind
sheet.** The engine's director path finds nothing and silently falls through to a single-name
fallback. It appears to work; it is working by accident.

### P4 — `seniority_label` is ignored ⚠️ throws away finished work
Northwind spent a whole session building a two-ladder seniority ranking, stored in `seniority_label`
at **100% fill**. The engine ignores it and re-ranks with its own hard-coded `SENIORITY` list
against `Job Title`, which is only **23% filled**. The engine will pick worse contacts than the
sheet already picked.

### P5 — The ledger key is unsafe ⚠️ will corrupt rows
`ledger.py` keys on lowercased company name. The Northwind sheet has **132 duplicate company names
over 264 rows**. Two different firms with the same name block each other permanently.
**Must become `lead_id`** — the same fix n8n v8 already made for write-back.

### P6 — `email_found` is terminal ⚠️ silently loses leads
`TERMINAL` includes `email_found`. Harmless today. The moment a campaign has a daily quota, a
lead enriched on Monday but not pushed is never retried. Enriched and pushed must be two
separate states.

### P7 — `job_title` and `blocklist_id` are never sent ⚠️ free wins missed
Instantly accepts both. Northwind has a `Job Title` column, and STATE.md records that **the Instantly
blocklist is empty**, so nothing is protecting the account.

### P8 — Two writers on `Status` ⛔ decide before first run
Northwind rule #1: only n8n/V7 writes `Status`. If the engine writes it too and both point at the
Practices tab, they will fight. **Decision required: the engine becomes the single runner and
v8 stays as the fallback, or they are pointed at different tabs. They must never share a tab.**

### P9 — The UI does not scale
10 flat tabs, 1,110 lines of vanilla HTML/JS/CSS, no framework, no build step. It was right for
one campaign. It has nowhere to put a campaign list, a field map, or a rule builder.

---

## PART 3 — The V2 architecture

Three new configuration layers. **The enrichment pipeline itself does not change.**

```
  ┌────────────────────────────────────────────────────────────┐
  │  LAYER 1 · CONNECTIONS   (a sheet + how to read it)        │
  │  sheet id · tab · auth · FIELD MAP                         │
  └────────────────────────────────────────────────────────────┘
                              │
  ┌────────────────────────────────────────────────────────────┐
  │  LAYER 2 · CAMPAIGNS     (many, run independently)          │
  │  which rows · what order · how many · which Instantly id    │
  │  · which labels to send · its own schedule                  │
  └────────────────────────────────────────────────────────────┘
                              │
  ┌────────────────────────────────────────────────────────────┐
  │  LAYER 3 · STEPS         (the pipeline, unchanged logic)    │
  │  gateway → find → verify → icebreaker → push → write back   │
  │  each step described in JSON, form rendered from it         │
  └────────────────────────────────────────────────────────────┘
```

### 3.1 Field Map — solves P3, P4

One map per connection. Left = what the engine calls it. Right = the real header in **your**
sheet. Auto-suggested, always overridable.

| Engine field | Required | Northwind sheet header | Used for |
|---|---|---|---|
| `row_key` | ✅ | `lead_id` | ledger key + write-back key |
| `company_name` | ✅ | `Company Name` | dedupe, payload |
| `website` | ✅ | `Website` | domain, pattern guessing |
| `contact_name` | ✅ | `Contact Name` | the person we email |
| `contact_first` | | `First Name` | payload |
| `contact_last` | | `Last Name` | payload |
| `job_title` | | `Job Title` | payload + ranking |
| `seniority_rank` | | `seniority_label` | **use the sheet's ranking, do not re-rank** |
| `status` | ✅ | `Status` | the "already done" memory |
| `send_gate` | ✅ | `send_ready` | never push unless `yes` |
| `existing_email` | | `Found Email` | source 1 in the cascade |
| `reference_email` | | `Company Email` | reference only, never send |
| `phone` | | `Telephone` | payload |
| `address` | | `Address` | city extraction |
| `employees` | | `Employees` | rules + size band |
| `icebreaker` | | `Ice Breaker` | payload `personalization` |
| `campaign_tag` | | `campaign` | rules |

**Rule: an unmapped optional field is simply absent. An unmapped required field blocks the run
with a clear message — never a silent empty string.**

### 3.2 Campaign record — solves P1

```
campaign
├─ id, name, enabled
├─ connection_id            which sheet + tab
├─ rules{}                  which rows qualify   (all / any / none)
├─ order[]                  which rows go first
├─ limits{ per_run, per_day, max_spend_usd }
├─ instantly{ campaign_id, blocklist_id, skip_if_* }
├─ labels[]                 what rides in custom_variables  ← dynamic
├─ writeback{ enabled, columns[] }
├─ schedule{ enabled, cron }
└─ auto_push                false until trusted
```

**One firm, one campaign** is enforced at selection: campaigns are evaluated in priority order
and the first match claims the row.

### 3.3 Label mapping — solves P2, P7

A table, not a Python tuple. Each row: **Instantly variable name ← sheet column or fixed value
or derived value.**

| Send as | Source | Type | If empty |
|---|---|---|---|
| `trigger_family` | column `trigger_family` | column | `V0_volume` |
| `seniority_tier` | derived `seniority_tier` | derived | `unknown` |
| `size_band` | derived from `Employees` | derived | `unknown` |
| `campaign_tag` | fixed `Northwind-1-practices-2-10` | fixed | — |
| *(add any row you like)* | | | |

**Validation enforced at save time, from the API docs: value must be string, number, boolean or
null. No nested objects, no arrays. A blank is replaced by the fallback, never sent empty** —
a blank label disappears from every GROUP BY without anyone noticing.

---

## PART 4 — UI: reference examples, not my invention

### 4.1 Layout to copy

| Screen | Copy from | Why |
|---|---|---|
| Campaign list | **Smartlead main dashboard** — one row per campaign, sent / opened / replied / bounced / positive replies, quick filters by status and time range | This is the home screen V2 is missing |
| Step config panel | **Instantly Automations** (your screenshots) — canvas, right-hand drawer, `Setup / Configure / Test` tabs, primary action bottom-right | Already the pattern you like |
| Step picker | **Instantly "Add an action"** panel — searchable list, grouped `All / Apps / Built-in tools / Data integrations` | Scales to any number of steps |
| Live run + activity | **Instantly Deliverability Agent** (your screenshots) — Current activity, Queued next, What was checked, Activity feed with Approve buttons | Exactly the right model for a lead run |
| Field mapping | **File → Map → Validate → Submit**, auto-suggested with manual override and a 5-row preview | The standard, and it solves P3 |
| Rule builder | **react-querybuilder** / **react-awesome-query-builder** / **SVAR React Filter** — AND/OR groups, nested, JSON output | Do not hand-roll this |

### 4.2 Node canvas — honest recommendation

You asked for n8n-style nodes. The library is **React Flow (xyflow)** — open source, used by
Stripe and Typeform, and its Pro Platform examples (workflow builder, dagre auto-layout) are now
open sourced.

**But: a canvas is the wrong first move here.** Your pipeline is a fixed straight line —
gateway → find → verify → icebreaker → push. There is nothing for a user to re-wire. A canvas
would be decoration over a pipeline that cannot branch.

**Recommendation:** take the *interaction model* from n8n and Instantly — a step list, a
right-hand config drawer, `Setup / Configure / Test` tabs, and a per-step **Test** button — and
skip the drag-and-drop canvas until the pipeline can actually branch. The declarative JSON step
description (PART 1.2) is what makes a canvas possible later without a rewrite.

### 4.3 Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | **FastAPI, kept** | Already works, tests already cover it |
| Storage | **SQLite** | Campaigns, ledger, runs, events. `data/*.json` cannot do concurrent campaigns |
| Scheduler | **APScheduler** | Per-campaign cron, persists across restarts |
| Frontend | **React + Vite + Tailwind + shadcn/ui** | The Shadcn Admin template is the most popular open-source starter and gives the sidebar, command palette and table for free |
| Tables | **TanStack Table** | 20,000-row lead lists need virtualisation |
| Charts | **Recharts** or **Tremor** | Standard with Tailwind |
| Rules UI | **react-querybuilder** | Outputs the JSON our rules layer already needs |
| Canvas | **React Flow** — *later*, only if branching arrives | Do not pay for it now |

⚠️ **`node_modules` must be relocated to `C:\ClaudeDeps\leadgen-node_modules` after every
`npm install`,** per the workspace rule. `npm install` deletes the junction and rebuilds a real
folder every time.

---

## PART 5 — Build phases

### Phase 1 — ✅ DONE 2026-09-04. See `STATE.md` for the verified numbers.
Goal: the engine reads the real Northwind sheet and pushes to the right campaign without a code edit.

1. Field Map (JSON file + a Settings screen), replacing every hard-coded `_get(...)` guess.
2. Honour `seniority_label` when it is mapped; only fall back to internal ranking when it is not.
3. Ledger key → `row_key` (`lead_id`); split `enriched` from `pushed`.
4. Campaigns file: many campaigns, each with rules, limits and its own Instantly id.
5. Dynamic label table; add `job_title` and `blocklist_id` to the payload.
6. **Plan preview** — free, zero API calls: how many rows each campaign would take.
7. Tests: extend the existing 96 offline checks to cover mapping, rules and label validation.

**Exit test:** plan preview on the real `NORTHWIND Leads` sheet returns sensible counts per campaign,
then one test-mode run of 5 leads completes end to end with no code changes.

### Phase 2 — ✅ DONE 2026-09-04. The app shell.
React + Vite + Tailwind in `ui/`, built into `webapp/dist`. Campaign list home screen ·
plan preview · run detail with live activity and the exact push payload · field-map editor ·
Settings. Campaign drawer follows Instantly's Setup / Rules / Order / Labels / Instantly
tab pattern. V1 interface kept at `/legacy`. Details in `STATE.md`.

### Phase 3 — Independence
Per-campaign schedules · `auto_push` per campaign · global daily spend cap · Slack or email
digest.

### Phase 4 — Optional
React Flow canvas, only if the pipeline gains real branching.

---

## PART 6 — Decisions — ALL SIX APPROVED 2026-09-04

| # | Question | Decision |
|---|---|---|
| 1 | Engine or n8n v8 as the Northwind runner? They cannot share the Practices tab. | ✅ **Engine runs it. v8 becomes the fallback, like v7 is now.** Still needs doing before the first live run. |
| 2 | Which column records which campaign a row went to? | ✅ Reuse **`campaign`**; write back `Campaign Type` = campaign id. Built. |
| 3 | Field map + campaigns in JSON files, or a Config tab in the Google Sheet? | ✅ **JSON files** — `config/fieldmap.northwind.json`, `config/campaigns.json`. Built. |
| 4 | Storage: keep `data/*.json`, or move to SQLite? | ✅ **SQLite** for the ledger (`data/ledger.db`), with a one-time migration from `ledger.json`. Runs and events stay NDJSON — they are per-run and append-only, so they do not have the concurrency problem. |
| 5 | Rebuild the UI in React, or extend the vanilla HTML? | ✅ **React + Vite + Tailwind + shadcn/ui** — Phase 2, deliberately not started yet. |
| 6 | Global daily cap — leads and pounds? | ✅ **300 pushes/day** (headroom under ~350 across 10 mailboxes) and **$5.00/day**. In `config/campaigns.json` → `globals`. Change the numbers there, no code edit. |

---

## Rules V2 must not break

1. `send_ready = yes` or it does not send.
2. Nothing leaves the machine without an explicit confirm, until `auto_push` is switched on
   per campaign.
3. Test mode stays free — no API calls, ever.
4. One firm, one campaign.
5. Never delete a row; quarantine it.
6. After fixing anything in the find-or-verify path, **clear the ledger** or the fix is invisible.
7. Every new module gets offline `eval_` checks, same as the existing 96.
