"""
stack_steps.py — what the step 3–6 screens show (build session 2): Ice breakers, Cold email,
Sending, Replies.

Pure functions over rows + a field map + core/store.py, like core/stack_view.py. The server
only fetches the rows and hands them in, so every number on these screens can be checked
without a server.
"""
from __future__ import annotations

from . import icebreakers as ICE
from . import replies as REP
from . import sending as SEND
from . import templates as TPL
from .stack_view import pill

ICE_STATE = {"written": ("Written", "good"), "waiting": ("Waiting", "warn"), "no_facts": ("No facts", ""),
             "failed": ("Failed", "bad"), "no_email": ("No email", ""), "not_researched": ("Not researched", "")}
SEND_STATE = {"queued": ("Queued", "warn"), "held": ("Held", ""), "sent": ("Pushed", "accent"),
              "stopped": ("Stopped", "bad")}
TPL_STATE = {"live": ("Live", "good"), "draft": ("Awaiting approval", "accent"), "rejected": ("Rejected", "")}
REQ_STATE = {"queued": ("Queued", "warn"), "draft_ready": ("Draft ready", "accent"), "approved": ("Approved", "good"),
             "rejected": ("Rejected", "")}


def _p(table: dict, value: str) -> dict:
    label, tone = table.get(value, (value, ""))
    return {"value": value, "label": label, "tone": tone}


def _key(fm, row) -> str:
    return str(fm.get(row, "row_key") or "").strip()


def _steps(store, source: str, key: str) -> dict:
    st = store.statuses(source).get(key) or {}
    return {c: st.get(c, "") for c in ("website_status", "email_status", "icebreaker_status", "push_status", "reply_status")}


# ── step 3: ice breakers ─────────────────────────────────────────────

def ice_leads(rows, fm, store, source: str) -> list[dict]:
    stored = store.statuses(source)
    facts = store.facts(source)
    lines = store.icebreakers(source)
    out = []
    for row in rows:
        key = _key(fm, row)
        if not key:
            continue
        s = {c: (stored.get(key) or {}).get(c, "") for c in
             ("website_status", "email_status", "icebreaker_status", "push_status", "reply_status")}
        fx = (facts.get(key) or {}).get("facts") or {}
        state = ICE.lead_state(s, bool(fx))
        if state == "not_researched" and ICE.sheet_icebreaker(fm, row):
            state = "waiting"                     # its own sheet line is used: never researched
        ln = lines.get(key) or {}
        out.append({"key": key, "company": str(fm.get(row, "company_name") or "").strip(),
                    "rung": ln.get("rung_name", "") if state == "written" else "",
                    "line": ln.get("line", "") if state == "written" else "",
                    "status": _p(ICE_STATE, state), "sent": s["push_status"] in ICE.PUSHED})
    return out


def ice_camp(rows, fm, store, source: str, ruleset: dict) -> dict:
    leads = ice_leads(rows, fm, store, source)
    lines = store.icebreakers(source)
    written_keys = {x["key"] for x in leads if x["status"]["value"] == "written"}
    used: dict[str, int] = {}
    for k, ln in lines.items():
        if k in written_keys:
            used[ln.get("rung", "")] = used.get(ln.get("rung", ""), 0) + 1
    rungs = [{**r, "needs": ICE.SOURCES.get(r.get("source", ""), ""), "used": used.get(r["id"], 0)}
             for r in ruleset.get("rungs") or []]
    count = {k: sum(1 for x in leads if x["status"]["value"] == k) for k in ICE_STATE}
    return {"source": source, "ruleset": {**ruleset, "rungs": rungs, "default_used": used.get("default", 0)},
            "sources": [{"id": k, "label": v} for k, v in ICE.SOURCES.items()],
            "leads": leads, "counts": count,
            "preview": [{"key": x["key"], "company": x["company"]} for x in leads
                        if x["status"]["value"] in ("written", "waiting")]}


def ice_preview(rows, fm, store, source: str, ruleset: dict, key: str) -> dict:
    row = next((r for r in rows if _key(fm, r) == str(key)), None)
    if row is None:
        return {"error": f"There is no lead '{key}' in this source."}
    s = _steps(store, source, str(key))
    company = str(fm.get(row, "company_name") or "").strip()
    ln = store.icebreakers(source).get(str(key)) or {}
    if s["icebreaker_status"] == "written" and ln:
        return {"key": key, "company": company, "rung": ln.get("rung_name", ""), "fact": ln.get("fact", ""),
                "line": ln.get("line", ""), "saved": True}
    # same rule as the run: no website facts -> no rung can match -> the Default line
    fx = (store.facts(source).get(str(key)) or {}).get("facts") or {} if s["website_status"] == "found" else {}
    rung, item, evidence = ICE.pick(fx, ruleset)
    line = ICE.compose(ruleset, company, rung, item, 0, 0)
    return {"key": key, "company": company, "rung": rung["name"] if rung else "Default", "fact": evidence,
            "line": line, "saved": False, "note": "Preview only. Not written yet."}


# ── step 4: cold email ───────────────────────────────────────────────

def email_camp(rows, fm, store, source: str) -> dict:
    tpls = store.templates(source)
    live = [t for t in tpls if t["state"] == "live"]
    pushes = store.pushes(source)
    replied = {r["row_key"] for r in store.replies(source)}
    sent: dict[int, int] = {}
    reps: dict[int, int] = {}
    for k, p in pushes.items():
        if p.get("state") == "pushed" and p.get("template_id") is not None:
            sent[p["template_id"]] = sent.get(p["template_id"], 0) + 1
            if k in replied:
                reps[p["template_id"]] = reps.get(p["template_id"], 0) + 1
    share = round(100 / len(live)) if live else 0
    out = []
    for t in tpls:
        if t["state"] == "rejected":
            continue
        res = t.get("result") or {}
        out.append({"id": t["id"], "name": t["name"], "subject": t["subject"], "body": t["body"],
                    "state": _p(TPL_STATE, t["state"]), "share": share if t["state"] == "live" else 0,
                    "score": int(t.get("score") or 0), "sent": sent.get(t["id"], 0), "replies": reps.get(t["id"], 0),
                    "request": t.get("request", ""), "approved_by": t.get("approved_by", ""),
                    "blocked": bool(res.get("blocked")), "unapproved": res.get("unapproved") or [],
                    "checks": res.get("checks") or [], "mistakes": res.get("mistakes") or [],
                    "passed": res.get("passed", 0), "of": res.get("of", 8)})
    reqs = [{"id": r["id"], "kind": TPL.KINDS.get(r["kind"], r["kind"]), "instructions": r["instructions"],
             "state": _p(REQ_STATE, r["state"]), "created": r.get("created", "")} for r in store.requests(source)]
    leads = [x for x in ice_leads(rows, fm, store, source) if x["status"]["value"] == "written"]
    return {"source": source, "templates": out, "requests": reqs,
            "kinds": [{"id": k, "label": v} for k, v in TPL.KINDS.items()],
            "live": len(live), "drafts": sum(1 for t in tpls if t["state"] == "draft"),
            "top_score": max([int(t.get("score") or 0) for t in live] or [0]),
            "preview": [{"key": x["key"], "company": x["company"]} for x in leads],
            "auto_approve_at": 90}


def email_preview(rows, fm, store, source: str, key: str, tid: int) -> dict:
    t = next((x for x in store.templates(source) if x["id"] == int(tid)), None)
    if t is None:
        return {"error": "That template no longer exists."}
    row = next((r for r in rows if _key(fm, r) == str(key)), None)
    if row is None:
        return {"error": f"There is no lead '{key}' in this source."}
    em = store.email_results(source).get(str(key)) or {}
    first, problem = ICE.first_name(em.get("contact", ""))
    line = (store.icebreakers(source).get(str(key)) or {}).get("line", "")
    mail = TPL.render(t, {"first_name": first, "company": ICE.short_company(str(fm.get(row, "company_name") or "")),
                          "ice_breaker": line})
    note = problem + ". Sending will hold this lead." if problem else ("" if line else "No ice breaker yet. Sending will hold this lead.")
    return {"to": em.get("email", ""), "contact": em.get("contact", ""), **mail, "note": note}


# ── step 5: sending ─────────────────────────────────────────────────

def send_view(rows, fm, store, source: str, *, campaign_name: str, sending_campaign: str,
              daily_limit: int = SEND.DAILY_LIMIT) -> dict:
    plan = SEND.plan(rows, fm, store, source)
    pushes = store.pushes(source)
    tnames = {t["id"]: t["name"] for t in store.templates(source)}
    leads = []
    for p in plan:
        tid = (pushes.get(p["key"]) or {}).get("template_id")
        leads.append({"key": p["key"], "company": p["company"], "email": p["email"],
                      "status": _p(SEND_STATE, p["state"]), "reason": p["reason"],
                      "template": tnames.get(tid, "") if p["state"] == "sent" else ""})
    queued = sum(1 for p in plan if p["state"] == "queued")
    today = SEND.sent_today(store, source)
    return {"source": source, "leads": leads,
            "row": {"campaign": campaign_name, "sending_campaign": sending_campaign, "queued": queued,
                    "held": sum(1 for p in plan if p["state"] == "held"),
                    "sent": sum(1 for p in plan if p["state"] == "sent"),
                    "sent_today": today, "daily_limit": daily_limit},
            "can_send": min(queued, max(0, daily_limit - today)),
            "live_templates": len(TPL.live(store, source))}


# ── step 6: replies ─────────────────────────────────────────────────

def replies_view(store, source: str, *, campaign_name: str, now=None) -> dict:
    out = []
    for r in store.replies(source):
        out.append({"id": r["id"], "key": r["row_key"], "sender": r["sender"] or r["email"], "company": r["company"],
                    "email": r["email"], "message": r["message"], "received": REP.when_label(r["received"], now),
                    "category": pill("reply_status", r["category"]), "action": r["action"],
                    "handled": bool(r["handled"]), "campaign": campaign_name,
                    "changed": r["category"] != r["auto_category"]})
    counts = {}
    for r in out:
        counts[r["category"]["value"]] = counts.get(r["category"]["value"], 0) + 1
    pushed = sum(1 for p in store.pushes(source).values() if p.get("state") == "pushed")
    return {"source": source, "replies": out, "counts": counts, "pushed": pushed,
            "categories": [pill("reply_status", v) for v in
                           ("interested", "not_interested", "ooo", "wrong_person", "unsubscribe")]}
