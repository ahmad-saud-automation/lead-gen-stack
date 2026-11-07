# UX redesign — architecture

**Status: approved 2026-10-04 and BUILT 2026-10-05 (branch v5, merged to main).** See STATE.md
"V5" for where each page lives. Written 2026-10-04. Goal from the user: *"less noisy, production friendly, easy to use like a
native app — without nerfing any functionality."* Problem in his words: every section "feels a
little technical"; a new user would never understand "field map file", "lane", "limits".

Order agreed: **research → this architecture (his yes) → clickable sample UI (his yes) → build.**

---

## 1. What real tools of this type do

| Tool | How a campaign is organised | What we take |
|---|---|---|
| **Smartlead** | Steps in work order: Name → **Leads** (upload, map columns, "processing" = dedupe against block/unsubscribe/bounce lists) → Sequence → Email accounts → **Settings grouped**: Schedule · Behaviour · Delivery · Protection & limits. Launch checklist: leads added, sequence exists, accounts assigned | Sections in the order the work happens; settings in named groups; a **launch checklist** |
| **Instantly** | Campaign tabs; the Options tab uses plain labels ("Daily limit", "Stop sending emails on reply") and hides the rest behind **"Show advanced options"** | Plain labels; **advanced hidden by default** |
| **lemlist** | Three parts only: Sequence · Lead list · Settings. Before launch, a **review** of every lead: email status (deliverable / risky / unknown) and missing variables | Few top-level parts; **review before sending** with per-lead status in words |
| **HubSpot import** | Column-matching step: auto-matched columns, "Don't import column", one checkbox for all unmatched | Column matching shown as "we matched 12 of 14", never as a file |
| **Clay** | Shows credit cost before a run; auto-run is OFF while you build, ON when you launch | **Cost before spending**; automation off until you choose |

Sources: [Smartlead – create a campaign (new version)](https://helpcenter.smartlead.ai/en/articles/442-how-to-create-an-email-campaign-in-smartlead-the-new-version) ·
[Smartlead – map CSV columns](https://helpcenter.smartlead.ai/en/articles/409-how-to-map-csv-columns-in-smartlead-campaigns) ·
[Instantly – campaign options](https://help.instantly.ai/en/articles/6222396-campaign-options) ·
[lemlist – create a campaign](https://help.lemlist.com/en/articles/4452686-create-a-campaign) ·
[lemlist academy – review leads before launching](https://academy.lemlist.com/academy/launch-campaigns/review-and-launch-my-campaign/review-your-leads-before-launching-your-campaign/) ·
[HubSpot – import objects](https://knowledge.hubspot.com/crm-setup/import-objects?lang=en-US) ·
[Clay – credit conservation](https://university.clay.com/fr/docs/clay-credit-conservation)

---

## 2. Seven rules for every screen

1. **Each screen answers three questions at the top:** what is this · what should I do next · what happens if I click.
2. **One main button per screen** (the "elephant in the room"); everything else is quieter.
3. **Plain words only** on the main view (word list in §5). Engine words live only under "Advanced".
4. **Pick, don't paste:** Instantly campaigns, sheet tabs and columns come from dropdowns, never typed ids.
5. **Money and numbers before action:** "This live run takes 50 leads and costs about $0.18."
6. **Test first:** a free test run is always the easy default; going live is a deliberate switch.
7. **Problems come with a Fix button** that jumps to the exact field.

---

## 3. New navigation: 10 pages → 5

| New page | What it holds | Replaces |
|---|---|---|
| **Home** | New user: a **setup checklist** (connect sheet → add keys → first campaign → free test → go live). After that: *today* — what runs next, what ran, money spent, leads waiting to be sent, anything that needs attention | Dashboard |
| **Campaigns** | One card/row per campaign: name, status word (Draft · Test · Live · Paused · Needs attention), leads left, next run, last result. **Drag to reorder** = who gets a shared lead first. **+ New campaign** opens a 4-step wizard | Campaigns + Plan preview |
| **Leads** | Every lead source: Google Sheet tabs + uploaded files. Each source: rows, health (repeats, suppressed, already contacted), **column matching**, preview. **+ Upload CSV** | Import + Field map |
| **Activity** | Every run and send, newest first, in words ("Practices 2-10 · test run · 5 leads · 4 emails found · $0.00"). Open one → progress, results, send review, full event list | Runs + History + Log |
| **Settings** | Groups: **Connections** (Google Sheet, Instantly, finders — each with *Test connection* ✓) · **Spending limits** · **Lead safety** (do-not-contact lists, hold leads without an ice breaker) · **Login** · **Advanced** (everything else, unchanged) | Settings |

The V1 screens stay reachable from Settings → Advanced, as today.

---

## 4. The campaign page (the screen he named)

**Top — status card, always visible**

> **Practices 2-10 staff** · 🟡 Test mode · next run Mon 09:00
> Ready to go live: **4 of 5** — ✕ No Instantly campaign chosen **[Fix]**
> [ **Run a free test** ] [ Run live ] [ Send found leads to Instantly ]

**Below — four sections in work order, each one sentence + a live count** (one Save for all):

| # | Section | Shows | Holds (today's settings) |
|---|---|---|---|
| 1 | **Who** — *Which leads does this campaign take?* | Source dropdown; filters as sentences: *Include leads where [Staff] [is between] [2] and [10]*; "Best leads first: sort by [Seniority]". Live count: **"1,670 match · 1,605 not contacted yet"** | Sheet tab, rules (all/any/none), order |
| 2 | **How many** — *How fast should it work?* | Leads per run · leads per day · max spend per run, each with a one-line hint and the $ estimate | Limits |
| 3 | **Send to** — *Where do the leads go?* | Instantly campaign **dropdown**; "Send to Instantly automatically" switch (off = you review first); "Update my Google Sheet" switch | Instantly id, auto push, write back |
| 4 | **When** — *Should it run by itself?* | One sentence: *Run [every weekday] at [09:00]*, test or live, "in the app / from Windows" | Schedule |
| ▸ | **Advanced** (closed by default) | Extra info sent to Instantly (labels) · blocklist / list id / skip options · column matching file · Campaign Type label · internal id · duplicate · delete | Labels, rest of Instantly tab, field map file, campaign type |

**New campaign = the same four sections as a wizard** (Who → How many → Send to → When → Review),
ending on a review screen with the checklist and a **free test run** button.

---

## 5. Word list (main screens)

| Today | New |
|---|---|
| Lane | Campaign |
| Sheet tab / tab | Lead source |
| Field map / field map file | Column matching (file name hidden, made automatically) |
| Priority | Order on the Campaigns list ("if a lead fits two campaigns, the higher one gets it") |
| Rules | Which leads (filters) |
| Order | Best leads first |
| Labels | Extra info sent to Instantly |
| Per run / Per day | Leads per run / Leads per day |
| Write back | Update my Google Sheet |
| Auto push | Send to Instantly automatically |
| Push | Send to Instantly |
| Test mode | Free test (nothing is spent or sent) |
| Ledger | Lead history ("leads already handled") |
| held / send_ready / email_not_found | "Waiting — email not verified" · "Ready to send" · "No email found" |
| Plan preview | Preview (counts inside each campaign) |

---

## 6. Nothing is removed — where every current control goes

| Today | New home |
|---|---|
| Setup → name, enabled | Campaign status card (name, on/off) |
| Setup → sheet tab, priority, field map file | Who (source) · Campaigns list drag (order) · Advanced (file) |
| Setup → per run, per day, max spend | How many |
| Setup → write back, auto push | Send to |
| Setup → Campaign Type, remove, duplicate | Advanced |
| Rules (all / any / none, 17 operators) | Who — same power, written as sentences |
| Order (sort keys) | Who → "Best leads first" |
| Labels | Advanced → Extra info sent to Instantly |
| Instantly → campaign id | Send to (dropdown, paste still possible) |
| Instantly → blocklist, list id, 3 skip options | Advanced |
| Schedule (all of it) | When |
| Plan preview | Campaigns list counts + each campaign's Who count |
| Import + Field map | Leads |
| Runs + History + Log (filters, search, CSV downloads) | Activity |
| Settings, every key and switch | Settings groups; rarely used ones under Advanced |
| /legacy (V1) | Settings → Advanced |

---

## 7. Engine work this needs (small, all read-only or already existing)

- **Instantly campaign list** for the dropdown (read-only API call with the saved key)
- **Sheet tab list** for the source dropdown (read-only, service account)
- **Test connection** per key (one cheap read call each; none spend credits)
- **Reorder** = rewrite priorities from the dragged order (existing save)
- A **readiness** answer per campaign (the checklist) — computed from data the engine already has

---

## 8. Plan

| Step | What | Gate |
|---|---|---|
| 1 | This document | **his yes / changes** |
| 2 | **Clickable sample UI** of all 5 pages + the campaign page + wizard: one HTML file, fake data, same look as today, opens in the browser | **his yes / changes** |
| 3 | Build page by page into the real app; old screens stay reachable until each new one is driven in Chrome and passes | per page |
