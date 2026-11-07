# Full lead gen stack — approved build plan (2026-11-06)

Approved by Ahmad on 2026-11-06 ("Approved, start building") after three rounds on the sample.
**The approved look and behaviour is `docs/sample-ui/full-stack.html`** (fake data, clickable).
Build the real app to match it. Do not re-design; if something in the sample cannot be built
as shown, stop and ask.

Purpose: a portfolio demo for an "AI Builder" job (Claude Code, n8n, self-healing automation).
He demonstrates the work; it does not have to run live campaigns yet.

## Hard rules (from him, unchanged)
- Design first, his yes, then build. One step at a time.
- Never send a real email. Never push to a live Instantly campaign. Test / dry-run only.
- Never delete or overwrite a live sheet row without showing him first. Adding pipeline columns
  to a LIVE sheet also needs his yes first.
- Never open or print a file that holds an API key.
- Edit files with Edit/Write only, never shell edits.
- Every fix gets a test that fails before and passes after. Run the whole `eval_*.py` suite.
  Baseline 2026-11-06: 24 of 26 files pass; the 2 failures are his live config, not code
  (`eval_campaigns.check_the_live_config_is_safe`, `eval_runner.check_loading_the_shipped_config...`).
- Plain simple English, tables, short. Production wording in the UI: no client brands
  (Northwind, Fabrikam, Contoso), no "Nick", no casual lines, no internal file names on screen.
- Verify screens with Playwright from `C:\ClaudeDeps\docpipeline-venv` (`channel="chrome"`,
  headless) at 1400 / 820 / 390 px. A reusable checker for the sample lives in the session
  scratchpad; copy its approach (page-by-page, overflow, banned words, master-detail scroll).

## Build order — 4 sessions (+1 if scheduling/demo needs it)
| # | Session | Delivers |
|---|---|---|
| 1 | **Base + steps 1–2** | shared lead record, demo data, Lead sources page, Leads master-detail page, Website research step, Find email writing `email_status` |
| 2 | **Steps 3–6** | Ice breakers page (connects `icebreaker-studio`), Cold email page + `/templates` request queue, Sending (test mode), Replies (read + classify) |
| 3 | **Schedules + Health + Live demo** | per-step triggers (time / after previous step), health agent with an allowed-fix list, daily summary, the Live demo page |
| 4 | **Publish** | the live-sheet bug fixes still open, fresh public GitHub repo, README, Loom script (Sonnet is enough) |

## Session 1 — what to build
1. **`core/lead_record.py` — one place that defines the pipeline columns.**

   | Logical column | Written by | Values (stored) | Read by |
   |---|---|---|---|
   | `website_status` | Website research | found · not_found · dead_domain · blocked | Find email, Ice breakers |
   | `email_status` | Find email | as-is · enriched · fallback · no_email · no_website · no_person · error | Ice breakers, Sending |
   | `icebreaker_status` | Ice breakers | written · waiting · no_facts · failed | Sending |
   | `push_status` | Sending | pushed · held · failed · pushed_by_hand | Ice breakers (already-emailed guard), Replies |
   | `reply_status` | Replies | interested · not_interested · ooo · wrong_person · unsubscribe | Home, stop rules |
   | `Status` | **nobody** (his own notes) | free text | humans |

   - Each sheet maps logical → real header through its field map. Organized / Fabrikam / Contoso
     sheets already have `enrich_status` (→ `email_status`) and `status` (→ `push_status`):
     **no new columns there**. CH tabs need new columns — his yes before adding.
   - Each stage may write ONLY its own column(s): an allow-list per stage, same idea as
     `Recipe.write_targets()`. Test that no stage can write another stage's column or `Status`.
   - ⛔ Keep the two pipeline paths separate (`_process_firm_fixed` / `_process_firm_recipe`).
     A legacy lane must not grow new keys (`eval_recipe.check_a_legacy_row_grows_no_new_keys`).
2. **Demo data.** `data/demo/demo-firms.csv`, 12 fake UK firms on `.example` domains, read via
   `local_tabs` so no live sheet is touched. A real demo Google Sheet is optional and needs his
   yes (it must sit in Drive `01 Campaigns & Leads` so the robot can write to it).
3. **Demo services = stand-ins (option A, my recommendation, not yet confirmed by him):**
   fake answers for website fetch, verification, finder and replies, so a demo costs $0 and
   gives the same result every time. The real code paths run; only the outside calls are faked.
4. **Website research step** — port the logic of `northwind/scripts/scrape_firm_sites.py`
   (Playwright, ≤5 pages, ~800 chars of signals per firm, resumable) into the engine. Facts go
   to an app database under `data/` (outside Drive per CLAUDE.md if it grows), sheet gets
   `website_status` only.
5. **Find email** writes `email_status` (not `Status`) on every path.
6. **Screens** (Next.js `web/`, `u-` classes, plain words from `web/lib/words.ts`): sidebar as
   in the sample, Lead sources (Connect sheet / Upload / Local file), Leads master-detail
   (list scrolls, record pane sticky and scrolls on its own), Website research, Find email.
7. **Done means:** evals pass (24/26 baseline kept, plus new ones), screens driven at 3 sizes,
   a read-back check on the demo data, STATE.md NEWEST box updated.

## Decisions still open (ask, don't assume)
| Decision | Default if he says "your call" |
|---|---|
| Demo services: stand-ins (A) or real services (B) | A |
| Icebreaker Studio reads `icebreaker_status` + `push_status` instead of `Status` (change in that project) | yes, in session 2 |
| Templates from Claude auto-approved at score ≥ 90 | as in the sample: on |
| "Dr Agrawal" contacts: hold, or greet "Hi Dr Agrawal," | hold (bug-fix session) |
| Service names on screen (sample shows generic "Email finder", "Sending platform") | generic |

## Open engine bugs (fix in session 4, before any live use)
⛔ Until then, tell him not to run live campaigns from the app, or at least not to sort a tab mid-run.

| # | Bug | Where | Fix |
|---|---|---|---|
| 1 | Wrong-row writes after a sort mid-run | `core/sheets.py` `open_writer` caches row index | re-read the key cell before each write, re-index on mismatch |
| 2 | No retry on Google 429 | `sheets.py` write, `server.py:497` swallows | backoff 2/4/8/16/32 s, ≤55 writes/min |
| 3 | Person memory skips the free as-is rung | `pipeline.py:305` | memory never applies to a `use_as_is`-only rung |
| 4 | Restart leaves a run `running` for ever | no startup sweep in `server._lifespan` | mark orphaned runs `interrupted`; launcher logs to `data/engine.log` |
| 5 | Push first_name from contact 1 | already fixed 10-19, uncommitted | commit with its eval |
| 6 | Unwritten results counted as done in the ledger | `server.py:481` records before the write | mark "not written", re-write later at no cost |
| 7 | App push lacks `company` / `email_source` / `trigger` vars | `core/instantly.build_payload` | add from field map |
| 8 | Copied campaign keeps a hidden `sheet_url` | campaign page | show the sheet on the campaign page |
| 9 | Missing field-map file accepted → "waiting for an ice breaker" | save + `runner.sheet_icebreaker` | refuse at save; say "ice breaker column not found" |
| 10 | "Dr X" → "Hi X," | `emailgen.spoken_words` | his rule needed |
| 11 | A recipe column named like an engine field (`contact_2_email`) reads as blank, so "as-is contact 2" never fires and contact 2 is guessed (paid) instead. Hits the live Organized recipes. Found 2026-11-06 on the demo (DM-004). | `recipe._read_col` → `fm.resolve` prefers the engine field | read the row's own header first when it exists; flip `eval_demo.EMAIL["DM-004"]` to "as-is" |

Bugs 2, 4 and 6 are also the health agent's demo cases in session 3 (allowed-fix list).

### Found 2026-11-06 while he pushed real leads (C10 Best 500 lane) — add to session 4
| # | Bug | Where | State |
|---|---|---|---|
| 12 | A spreadsheet a campaign reads through its own `sheet_url` / field map is not listed on Lead sources (only "Fabrikam Live" shows) | `/sources` page | open |
| 13 | Campaign page says "You have unsaved changes" right after opening, nothing edited. Saving could rewrite settings he never touched | `components/campaign/page.tsx` dirty check | open |
| 14 | Campaign page read the tab's columns from the MAIN sheet, so a lane with its own sheet showed no columns, an empty preview and every Instantly field as "(not in this source)". The run was right | `server.import_preview` ignored the lane's sheet | **FIXED 2026-11-06** (`eval_connections.check_preview_reads_the_campaigns_own_sheet`, page passes `campaign`) |
| 15 | Campaigns list "Leads left" column shows "…" for every campaign | `/campaigns` page | open |
| 16 | Last real run (fabrikam msmes, 5 Nov): 240 found but only 155 written back to the sheet — 85 results maybe lost (bug 2/6?) | ledger vs sheet | check |
| 17 | `start-app.bat` pointed Next.js deps at `C:\ClaudeDeps` (D:) — cross-drive build fault | `start-app.bat` | **FIXED 2026-11-06** |
| 18 | A dev server on 3200 (`next dev`) writes into the same `.next` as the `next start` build, so a stale test server corrupts the real build (500 on every page) | `web/.next` shared by dev and start | open — give dev its own dist dir |
| 19 | Push confirm box says "added to <app campaign name> in Instantly"; the real Instantly campaign is a different one ("Phase 2") — name the Instantly campaign | run page push dialog | open |
| 20 | "Run live now?" box drops the lead count: "works on up to leads" (number missing at per_run 1) | campaign page live dialog | open |
| 21 | Push attempt 1 timed out (read timeout) and was retried; check a timed-out POST can never add the lead twice | `instantly.push_lead` retry | check |
| 22 | "Send to Instantly automatically" only works for SCHEDULED runs (`fire_lane`); a run started with "Run live" never pushes, though the switch's own text says "after each run". 2026-11-06: 320 found, 0 pushed, pushed by hand from the run page | `server.start_campaign_run` vs `fire_lane` | open |
| 23 | Same run: 320 found, `written_back` 263 — 57 results not on the sheet (repeat of #16). Find out whether they were unchanged as-is rows or lost writes | ledger vs sheet write-back | check |
| 24 | Real Website research could never run from the app: `playwright` was not installed in `leadgen-venv`, and no bundled browser on this profile | `research.PlaywrightFetcher` | fixed 2026-11-06 (installed; falls back to installed Chrome) |
| 25 | The PC's DNS drops lookups: 3 of 10 live firms "did not resolve" locally, all 10 answered on 8.8.8.8 → false "no website" | real fetch | fixed 2026-11-06 (`LiveServices.fetch` asks again twice on NAME_NOT_RESOLVED) |
| 26 | Pipeline run card "Find email" counted no-website leads as "not found" ("8 in → 8 found · 4 not found") | `server._produced` | fixed 2026-11-06, `eval_showcase` |
| 27 | Copy scorer knows only £: US (or any $) copy can never pass "Offer stated" / "Real result", so US templates top out near 50–60 and always need a person to approve | `core/copy_score.py` | open |
| 28 | Schedules page rows still apply to Demo firms only; the showcase campaign runs from Pipeline run's one-time trigger | `stack_schedule` | open |
| 29 | Live showcase run: 3 of 10 sites "unreachable" (Wamhoff, Lawson, Cash Tax) though all 10 resolve on 8.8.8.8 — the 2-retry fix (#25) is not enough; try DNS-over-HTTPS in Chrome or a resolver check before calling a site dead | real fetch | open |
| 30 | Find email card counted only "found" websites as input; a site that refused the reader (blocked) still has a domain and its email was found → card "6 in → 4 found", log "5 found" | `server._produced` | fixed 2026-11-06, `eval_showcase` |
| 32 | Research ran before Find email and blanked the domain of every site it could not read, so those leads were never searched ("no website, so there is no format to guess"); a lead with no website was skipped; a lead with an email but no website facts got no ice breaker and was held. Live run: Lawson, Cash Tax, Wamhoff never searched; HofflerSmith, EZ Tax held | `find_email`, step order, `icebreakers`, showcase recipe | fixed 2026-11-07 (his order: Find email on every lead → research only leads with an email → Default line for no match; no-website leads go to the finder by company name) |
| 31 | Real-campaign pages still said demo/test: "Start the demo again" on Ice breakers, "Demo workspace" banner on Ice/Cold email lists + Health, "sent (test mode)" in summary + Home, Sending footnote "test campaign", NOT_YET_STEP "Only Demo firms" | screens + `health.summary` | fixed 2026-11-06 (shows after rebuild) |
