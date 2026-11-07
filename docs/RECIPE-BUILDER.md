# Design — the Finding Recipe builder

**Status: design APPROVED 2026-10-07 — his picks `1A 2A 3A 4A` (section 7). Nothing is built yet.**

## Why

Today every campaign uses **one fixed order** burnt into `core/pipeline.py` (158 lines):

1 security check → 2 the email already on the row → 3 guess the format → 4 Icypeas → 5 Anymailfinder → 6 result

and `core/organize.py` picks **one** person per row. So a new idea — like "1st director, then
2nd director, then the owner's email last" — needs new Python every time.

**After this change the order and the people are settings**, saved per campaign and editable on
screen. His CH director plan becomes **recipe #1**, not code. No LLM runs at any point; a recipe
is plain rules.

---

## 1. What a recipe is

One saved file per recipe in `config/recipes/<id>.json`. A campaign points at it by name, so
**one recipe can serve all 5 CH tabs**. A campaign with no recipe keeps today's behaviour exactly.

### 1a. Header

| Field | Type | Default | Plain meaning | Control on screen |
|---|---|---|---|---|
| `id` | slug | from the name | internal name | hidden |
| `name` | text | — | "Director waterfall" | text box |
| `note` | text | blank | why this recipe exists | one-line box |
| `updated` | date | auto | last change | shown, not editable |

### 1b. `people` — who to email, in order (the ladder)

An ordered list. The engine tries person 1, then person 2, and so on. Each row:

| Field | Type | Default | Plain meaning | Control |
|---|---|---|---|---|
| `label` | text | "Person 1" | what you call this step — "1st director" | text box |
| `name_from` | column pick | — | which column holds this person's name | dropdown of your sheet columns |
| `address_from` | column pick | blank | use the address in this column as-is, no searching | dropdown (leave empty for a search) |
| `only_if` | condition | blank | "only try this person if …" | sentence builder (the 17 operators you already have) |
| `never_if_same_as` | column picks | blank | skip if this person is the same as the person in those columns | multi-select (e.g. `Director Who Left`, `Email Person`) |
| `how` | list | — | the ways to find this person, in order — see 1c | drag list of chips |

### 1c. `how` — the ways to find one person, in order

| Field | Type | Options | Plain meaning |
|---|---|---|---|
| `method` | pick | `guess_patterns` · `icypeas_domain` · `icypeas_company` · `use_as_is` | guess the format · ask Icypeas with the website · ask Icypeas with the company name · use the address that is already there |
| `patterns` | pick | `careful (3)` · `thorough (6)` | only for `guess_patterns`. careful = `first@`, `first.last@`, `f.last@` |
| `verify` | pick | `must pass` (default) · `write but mark as failed` · `no check` | what MillionVerifier's answer means |
| `note_if_domain_mismatch` | on/off | on | for `icypeas_company`: if the found domain does not look like the company name, still write it but mark "check by hand" |

The screen greys out a method the row cannot use (e.g. `guess_patterns` with no website) and says why.

### 1d. `stop` — when to stop

| Field | Type | Default | Plain meaning |
|---|---|---|---|
| `stop_when` | pick | `first email that passes` | or `try everyone and keep the best` |
| `skip_row_if` | condition | blank | skip the whole row — e.g. `Next Step` starts with "Stop" |
| `last_resort` | pick | `off` | `on` = if nothing passed, write the best candidate anyway, marked, **never sent** |

### 1e. `write` — where results go (this is the guard on your columns)

| Field | Type | Default | Plain meaning |
|---|---|---|---|
| `email_to` | column pick | `Found Email` | the address that passed |
| `person_to` | column pick | `Found For` | who it belongs to + which step found them |
| `method_to` | column pick | `Found By` | guess / Icypeas / your email, plus the check result |
| `status_to` | column pick | `Status` | found / not found / skipped / check by hand |
| `write_when` | pick | `every row, straight away` | or `only when something is found` |

⛔ The engine may write **only these 4 columns**. Everything else on your sheet is read-only to it.
That is what stops the old write-back touching `Contact Name` and `Email Source`.

### 1f. `limits`

| Field | Type | Default | Plain meaning |
|---|---|---|---|
| `per_run` | number | 30 | rows per run |
| `per_day` | number | from Settings | rows per day |
| `daily_spend_cap_usd` | number | from Settings | stop when this is reached |
| `search_same_person_once` | on/off | on | the same person at the same firm is searched once, even across tabs |
| `catch_all` | locked off | off | cannot be switched on in a recipe |
| `push_to` | pick | `nothing (finding only)` | or an Instantly campaign from the dropdown |

---

## 2. The screens

### Screen A — Campaign → "Finding recipe" tab

| Part | What you see | Control |
|---|---|---|
| Top | "This campaign finds emails using: **Director waterfall**" | dropdown of saved recipes · **New** · **Edit** |
| The ladder | numbered person rows: label · "name from *Endole director*" · method chips · the condition as a sentence | drag ⋮⋮ to reorder · **+ Add person** · copy · delete |
| A person row, opened | the fields of 1b + 1c, each with one help line and a **real example from your sheet** ("Ian Smith → ian@smithco.co.uk") | as listed above |
| Stop rules | the 3 fields of 1d as sentences | — |
| Write to | the 4 column dropdowns of 1e, pre-filled | — |
| Limits | the fields of 1f | — |
| Footer | **Try on 10 rows** (free, no credits) → a table: the row, who it picked, what it would try, estimated credits. Then **Save**. | — |

### Screen B — Settings → Recipes

A list: name · used by which campaigns · last change. Buttons: copy, rename, delete (refused while a
campaign uses it).

No new words on screen come from the engine. `web/lib/words.ts` gains: recipe, person, way to find,
check, stop, write to.

---

## 3. What changes in the engine

| # | Change | File |
|---|---|---|
| 1 | Read and check a recipe; build the ordered people for one row; the methods per person | **new** `core/recipe.py` |
| 2 | Replace the fixed 6 steps with: security check → for each person → for each way → check → stop rule → result. **No recipe = today's exact order**, so existing campaigns do not change | `core/pipeline.py` |
| 3 | Rank one person from the row only when the recipe does not name the people | `core/organize.py` |
| 4 | Write-back takes the 4-column whitelist from the recipe | `core/sheets.py` (`build_writeback_row`) |
| 5 | Write on every outcome, straight away, not at push time | `webapp/server.py` `_worker` |
| 6 | New field-map fields: `next_step`, `existing_email`, `email_person`, `found_for`, `found_by`, `director_left`, `director_1`, `director_2` | `core/fieldmap.py` + `config/fieldmap.ch-tabs.json` |
| 7 | New outcomes count as done: `email_failed_check`, `check_by_hand` | `core/ledger.py`, `server.TALLY` |
| 8 | `recipe` key on a campaign + validation + the Recipes screens' endpoints (`/api/recipes`, `/api/recipes/preview`) | `core/campaigns.py`, `webapp/server.py` |
| 9 | The same person + firm searched once; never in test mode | `data/person_cache.json` |
| 10 | Offline tests | **new** `eval_recipe.py` + more in `eval_pipeline.py` |
| 11 | Later, at push time: greet the person we found, not `Contact Name` | `core/instantly.py` |

**Locked in code, a recipe cannot change them:** no catch-all · nothing unverified is pushed ·
only the 4 chosen columns are written · a free test never writes to the ledger or the cache.

---

## 4. Recipe #1 — your CH director plan, in the fields above

| Field | Value |
|---|---|
| name | Director waterfall |
| skip_row_if | blank. Under decision 1A the recipe decides, not the `Next Step` text: a row where every person is blank or is the leaver / the person already emailed simply runs out of people and gets Status "skipped — no director" (the 45 "Stop" rows land here on their own) |
| Person 1 | label "1st director" · name from `Endole director` (then `Apollo director` if blank) · never if same as `Director Who Left` or `Email Person` |
| Person 2 | label "2nd director" · name from `Contact 2` · never if same as `Director Who Left` or `Email Person` |
| Person 3 | label "the email already on the row" · address from `Email` · only if `Seniority` is Director |
| how (persons 1–2), firm **with** a website | guess_patterns `careful (3)` → `icypeas_domain` — each `must pass` |
| how (persons 1–2), firm **without** a website | `icypeas_company` · `must pass` · mark a mismatched domain "check by hand" |
| how (person 3) | `use_as_is` · `must pass` |
| stop_when | first email that passes |
| last_resort | **on** — "maximum leads filled": if nothing passed, the `Email` on the row is written marked "failed check" and is never sent |
| write | U `Found Email` · V `Found For` · W `Found By` · `Status` · every row, straight away |
| limits | per_run 30 for the paid test · same person searched once (32 firms sit on 2 tabs) · push: nothing |
| used by | all 5 CH tabs (one recipe, five campaigns) |

**Numbers, unchanged:** 1,332 rows · 1,212 to search (526 with a website, 686 without) · 75 "use the
email on the row" · 45 Stop · at most ~1,700 Icypeas credits (charged only on a find) and
~4,100 MillionVerifier checks.

---

## 5. Order of work

| Step | What | Size |
|---|---|---|
| 1 | `core/recipe.py` + pipeline rewrite + tests, no screens (a recipe file by hand) | ~1 session |
| 2 | Screens A and B, "Try on 10 rows", validation | ~1 session |
| 3 | Recipe #1 built in the UI → free test run → paid test on 30 "New loan" rows → you check by hand | ~0.5 session |
| 4 | The rest, one tab at a time. Instantly later (needs copy, ice breakers, campaign ids, your ok) | — |

**Your side, before step 3:** Settings → Connections — MillionVerifier key → Save → **Test**;
Icypeas key → Save (no test button). Catch-all off, Anymailfinder off, daily spend cap set.
n8n must not run on these 5 tabs.

## 6. What a recipe can never do (code, once, when you want it)

- A new provider (another finder, phone numbers) = a new method in the list.
- A new kind of condition beyond the 17 operators.
- A new concept (e.g. "call them" instead of "email them").

Everything else — who, in what order, under what condition, by which method, written where — is
settings from then on.

---

## 7. Decisions — APPROVED 2026-10-07: `1A 2A 3A 4A`

| # | Approved | Effect |
|---|---|---|
| 1 | **A** — the order lives in the recipe | `Next Step` is a note for his eyes only. The engine never reads it. **Sheet-prep step (b), the 75-row edit, is not needed.** |
| 2 | **A** — a shared recipe library | one recipe, used by the 5 CH tabs |
| 3 | **A** — no recipe = today's order | old campaigns are untouched by this change |
| 4 | **A** — builder first, then the emails | steps 1 → 2 → 3 of section 5, about 2.5 sessions |

The options as they were put to him (⭐ = the pick):

1. **Where the order lives**
   - **A ⭐** In the recipe. `Next Step` stays in the sheet as a note for your eyes only. Changing
     your mind = one dropdown, no sheet script, no re-run. It also removes sheet-prep step (b),
     the 75-row edit.
   - **B** The engine follows the `Next Step` text, as planned this morning. The sheet decides;
     every change means editing 1,332 rows again.
2. **Recipes are shared**
   - **A ⭐** A library: one recipe used by the 5 tabs. Fix it once, all 5 follow.
   - **B** A separate copy inside each campaign.
3. **Existing campaigns**
   - **A ⭐** No recipe = exactly today's order, nothing changes for the old lanes.
   - **B** Convert them all to recipes now.
4. **Build order**
   - **A ⭐** Steps 1 → 2 → 3 above: the builder first, then the emails (about 2.5 sessions).
   - **B** Step 1 + a plain screen now so the emails start sooner; the full editor after.

Answer like "1A 2A 3A 4A".
