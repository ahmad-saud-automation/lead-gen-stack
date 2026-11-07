"""
sending.py — step 5: queue ready leads in the sending platform. TEST MODE ONLY in this version.

A lead is READY when it has:
  * a usable email address (email_status as-is · enriched · fallback),
  * a written ice breaker (icebreaker_status = written),
  * a first name to greet (a company address with no person, or a name that starts with a
    title such as "Dr", is HELD for a human look: his "hold" pick, 2026-11-06),
  * and the campaign has at least one live template.
A lead already pushed, or that asked to unsubscribe, is never sent again.

Leads with an address but no ice breaker or no first name are HELD, not dropped: Sending
writes `push_status = held` with the reason, and looks at them again on the next run.

Leads are split evenly between the live templates (the least-used one goes next). At most
`daily_limit` leads go per day.

⛔ `run()` refuses to work unless `test_mode` is True ("no email leaves"). The platform is
either the demo stand-in (core/demo_services.DemoSendingPlatform, `test_only`), or a
`draft_only` platform (core/live_services.InstantlyDraftPlatform) whose `confirm_draft()`
must say the real campaign is a Draft or Paused right before the first lead: a campaign
in those states sends nothing. Writes ONLY `push_status` (pushed · held · failed)
through the store; nothing goes to `Status`.
"""
from __future__ import annotations

from datetime import date

from . import icebreakers as ICE
from . import lead_record as LR
from . import templates as TPL

STAGE = "sending"
COLUMN = "push_status"
DAILY_LIMIT = 50
SENT = ("pushed", "pushed_by_hand")


class SendRefused(RuntimeError):
    """Sending was asked to do something it must not do."""


def plan(rows: list[dict], fm, store, source: str) -> list[dict]:
    """Every lead with an address, and what Sending would do with it now."""
    stored = store.statuses(source)
    emails = store.email_results(source)
    lines = store.icebreakers(source)
    pushes = store.pushes(source)
    out = []
    for row in rows:
        key = str(fm.get(row, "row_key") or "").strip()
        if not key:
            continue
        s = {c: (stored.get(key) or {}).get(c, "") for c in LR.COLUMNS}
        if s["email_status"] not in ICE.USABLE_EMAIL:
            continue
        em = emails.get(key) or {}
        first, problem = ICE.first_name(em.get("contact", ""))
        rec = {"key": key, "company": str(fm.get(row, "company_name") or "").strip(),
               "email": em.get("email", ""), "first_name": first, "contact": em.get("contact", ""),
               "line": (lines.get(key) or {}).get("line", ""), "push_status": s[COLUMN],
               "template_id": (pushes.get(key) or {}).get("template_id")}
        if s[COLUMN] in SENT:
            rec.update(state="sent", reason="")
        elif s["reply_status"] == "unsubscribe":
            rec.update(state="stopped", reason="Asked to unsubscribe")
        elif s["icebreaker_status"] != "written":
            rec.update(state="held", reason="No ice breaker yet")
        elif not em.get("email"):
            rec.update(state="held", reason="No email address")
        elif problem:
            rec.update(state="held", reason=problem)
        else:
            rec.update(state="queued", reason="")
        out.append(rec)
    return out


def sent_today(store, source: str, today: date | None = None) -> int:
    day = (today or date.today()).isoformat()
    return sum(1 for p in store.pushes(source).values()
               if p.get("state") == "pushed" and str(p.get("pushed_on", "")).startswith(day))


def run(rows: list[dict], fm, store, source: str, platform, *, test_mode: bool,
        daily_limit: int = DAILY_LIMIT, today: date | None = None) -> dict:
    if test_mode is not True:
        raise SendRefused("Sending runs in test mode only in this version. Nothing was sent.")
    mode = "test"
    if not getattr(platform, "test_only", False):
        if not getattr(platform, "draft_only", False):
            raise SendRefused("Only the test sending platform can be used in this version. Nothing was sent.")
        why = platform.confirm_draft()      # asks the platform NOW: Draft or Paused, or nothing goes
        if why:
            raise SendRefused(why)
        mode = "draft"
    tpls = TPL.live(store, source)
    if not tpls:
        raise SendRefused("Approve a template on the Email template page first. Nothing was sent.")
    use = {t["id"]: 0 for t in tpls}
    for p in store.pushes(source).values():
        if p.get("state") == "pushed" and p.get("template_id") in use:
            use[p["template_id"]] += 1
    room = max(0, int(daily_limit) - sent_today(store, source, today))
    out = {"pushed": 0, "held": 0, "failed": 0, "over_limit": 0, "results": []}
    for lead in plan(rows, fm, store, source):
        key = lead["key"]
        if lead["state"] == "held":
            if lead["push_status"] != "held" or (store.pushes(source).get(key) or {}).get("reason") != lead["reason"]:
                store.write_status(STAGE, source, key, {COLUMN: "held"})
                store.save_push(source, key, {"state": "held", "reason": lead["reason"], "email": lead["email"],
                                              "campaign": platform.campaign, "mode": mode})
            out["held"] += 1
            out["results"].append({"key": key, "status": "held", "reason": lead["reason"]})
            continue
        if lead["state"] != "queued":
            continue
        if room <= 0:
            out["over_limit"] += 1
            continue
        tid = min(use, key=lambda i: (use[i], i))
        t = next(x for x in tpls if x["id"] == tid)
        mail = TPL.render(t, {"first_name": lead["first_name"], "company": ICE.short_company(lead["company"]),
                              "ice_breaker": lead["line"]})
        try:
            platform.add({"email": lead["email"], "first_name": lead["first_name"], "company": lead["company"],
                          "subject": mail["subject"], "body": mail["body"], "key": key})
        except Exception as e:  # noqa: BLE001 - one refused lead must not stop the rest
            store.write_status(STAGE, source, key, {COLUMN: "failed"})
            store.save_push(source, key, {"state": "failed", "reason": str(e)[:200], "template_id": tid,
                                          "email": lead["email"], "campaign": platform.campaign, "mode": mode})
            out["failed"] += 1
            out["results"].append({"key": key, "status": "failed"})
            continue
        use[tid] += 1
        room -= 1
        store.write_status(STAGE, source, key, {COLUMN: "pushed"})
        store.save_push(source, key, {"state": "pushed", "template_id": tid, "email": lead["email"],
                                      "campaign": platform.campaign, "mode": mode})
        out["pushed"] += 1
        out["results"].append({"key": key, "status": "pushed", "template": t["name"]})
    return out
