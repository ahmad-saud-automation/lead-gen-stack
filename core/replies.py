"""
replies.py — step 6: collect replies, put each in one category, record it.

    interested · not_interested · ooo (out of office) · wrong_person · unsubscribe

Classification is plain rules, checked in this order, so the costly mistakes are the least
likely: an unsubscribe is never read as interest, and "not interested" is checked before
"interested" (which it contains). A reply that matches nothing is put in `interested`, so a
person reads it: it lands under "Needs your decision" rather than being quietly dropped.

Each reply also gets a recommended action, using what the message says (the return date of
an out-of-office, the new address of a wrong person, a day offered for a call).

Writes ONLY `reply_status` through the store. The message itself stays in the app database.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

STAGE = "replies"
COLUMN = "reply_status"

RULES = [
    ("unsubscribe", r"\b(unsubscribe|remove me|take me off|stop (emailing|contacting|sending)|do not (email|contact)|"
                    r"don.t (email|contact)|opt me out|gdpr)\b"),
    ("wrong_person", r"\b(left the (company|firm|business|practice)|no longer (work|with)|wrong person|"
                     r"not the right person|please contact|you should contact|retired)\b"),
    ("ooo", r"\b(out of (the )?office|on (annual )?leave|away until|back on|return(ing)? on|limited access to email|"
            r"automatic reply|auto.?reply)\b"),
    ("not_interested", r"\b(not interested|no thanks|no thank you|not for us|not at (the|this) moment|"
                       r"not right now|we are (all )?covered|already have|not looking)\b"),
    ("interested", r"\b(interested|yes|send (me )?more|tell me more|call|speak|chat|meet|cost|price|pricing|quote|"
                   r"how much|sounds good|go ahead)\b"),
]

_DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december)"


def classify(message: str) -> str:
    low = str(message or "").lower()
    for cat, rx in RULES:
        if re.search(rx, low):
            return cat
    return "interested"


def action(category: str, message: str) -> str:
    low = str(message or "").lower()
    if category == "interested":
        d = re.search(r"\b" + _DAY + r"\b", low)
        if d:
            return f"Book a call. {d.group(1).title()} was offered."
        if re.search(r"\b(cost|price|pricing|quote|how much)\b", low):
            return "Reply with pricing."
        if not re.search(RULES[-1][1], low):
            return "Read this reply and decide. It did not match any rule."
        return "Reply by hand today."
    if category == "not_interested":
        return "No action. Follow-ups stopped."
    if category == "ooo":
        m = re.search(r"\b(?:until|back on|returning on|return on)\s+((?:" + _DAY + r"\s+)?\d{1,2}(?:st|nd|rd|th)?\s+"
                      + _MONTH + r"|" + _DAY + r")", low)
        when = m.group(1).title() if m else "the return date"
        return f"No action. The sequence resumes after {when}."
    if category == "wrong_person":
        m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", message or "")
        return f"Add {m.group(0)} as a new contact for this company." if m else "Find the right contact for this company."
    if category == "unsubscribe":
        return "Removed from all campaigns."
    return ""


def when_label(stamp: str, now: datetime | None = None) -> str:
    try:
        t = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(stamp or "")
    now = now or datetime.now()
    if t.date() == now.date():
        return f"Today {t:%H:%M}"
    if t.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {t:%H:%M}"
    return f"{t:%d %b %H:%M}"


def check(rows: list[dict], fm, store, source: str, inbox, *, now: datetime | None = None) -> dict:
    """Collect new replies for pushed leads, classify each, write reply_status."""
    pushes = store.pushes(source)
    emails = store.email_results(source)
    by_key = {str(fm.get(r, "row_key") or "").strip(): r for r in rows}
    sent = [k for k, p in pushes.items() if p.get("state") == "pushed" and k in by_key]
    out = {"new": 0, "seen": 0, "by_category": {}}
    for item in inbox(sent, now=now):
        key = str(item["key"])
        row = by_key.get(key) or {}
        cat = classify(item["message"])
        rid = store.add_reply(source, {
            "row_key": key, "sender": (emails.get(key) or {}).get("contact", "") or item.get("sender", ""),
            "company": str(fm.get(row, "company_name") or "").strip(), "email": (pushes.get(key) or {}).get("email", ""),
            "message": item["message"], "received": item["received"], "category": cat,
            "action": action(cat, item["message"])})
        if rid is None:
            out["seen"] += 1
            continue
        store.write_status(STAGE, source, key, {COLUMN: cat})
        out["new"] += 1
        out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
    return out


def recategorise(store, source: str, rid: int, category: str) -> dict:
    rep = next((r for r in store.replies(source) if r["id"] == int(rid)), None)
    if rep is None:
        raise ValueError("That reply no longer exists.")
    store.write_status(STAGE, source, rep["row_key"], {COLUMN: category})   # refuses an unknown value
    store.update_reply(source, rep["id"], category=category, action=action(category, rep["message"]))
    return {"ok": True}


def mark_handled(store, source: str, rid: int, handled: bool = True) -> dict:
    if not any(r["id"] == int(rid) for r in store.replies(source)):
        raise ValueError("That reply no longer exists.")
    store.update_reply(source, int(rid), handled=1 if handled else 0)
    return {"ok": True}
