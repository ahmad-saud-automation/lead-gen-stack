"""
copy_score.py — scores a cold email template against the copy rulebook.

A faithful port of the scoring in the copywriting assistant (`analyse()` + `SCORED` in its
single HTML file, weights from its RULES.md, which were measured 8/8 against before/after
pairs). Do not change a weight or a pattern here without changing it there too; the two
must never disagree. Baseline: the assistant's reference email scores 100 here as well
(eval_templates.check_the_reference_email_scores_100).

    8 checks, 100 points          mistakes subtract
    Offer stated        20        Unapproved figure          15  (blocks the template)
    Proof included      18        Subject over 50 characters  5
    Risk removed        15        Paragraph too long          5
    Real result         12        Long dash, exclamation,
    Time offered        10          legal name, Title Case    3 each
    About them          10        Over the word guide       0-6
    Easy for them        8
    Cold acknowledged    7

Every figure (a £ amount or a percentage) must be on the campaign's approved list. That is
the one mistake a reader can check and disprove, so a template with one is BLOCKED: it can
never be approved, by hand or automatically.

Pure, no network. Template variables such as {{first_name}} are scored as written.
"""
from __future__ import annotations

import re

WORD_GUIDE = 100
GRACE = 10
AUTO_APPROVE_AT = 90

# (key, screen name, points, test on the lowercased body)
CHECKS = [
    ("OFFER", "Offer stated", 20,
     lambda s, a: bool(re.search(r"£\s?[\d,]+", s) or re.search(r"£[^.?!]*\b(an hour|a quarter|per employee)\b", s, re.I))),
    ("PROOF", "Proof included", 18,
     lambda s, a: bool(re.search(r"\b\d[\d,]*\+?\s*(clients|practices|firms|businesses|staff|people|employees|hours|%)", s, re.I)
                       or re.search(r"\b\d+\s?%\s*(of|drop|fall|less|fewer|reduction)", s, re.I)
                       or re.search(r"(workload|turnaround|response times?|costs?|profit)[^.?!]*\b\d", s, re.I))),
    ("GUARANTEE", "Risk removed", 15,
     lambda s, a: bool(re.search(r"(no contract|no notice|refund|you do not pay|you don.t pay|no cost|nothing to cancel|"
                                 r"does not matter if you|not signing|walk away|will not chase)", s, re.I))),
    ("RESULT", "Real result", 12,
     lambda s, a: bool(re.search(r"\d+\s?%|£\s?[\d,]+", s))
     and bool(re.search(r"(dropped|cut|saved|improved|fell|reduced|freed|took on|stopped turning)", s, re.I))),
    ("CTA", "Time offered", 10,
     lambda s, a: bool(re.search(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", s, re.I)
                       or re.search(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b", s, re.I))),
    ("OPENER", "About them", 10, lambda s, a: a["you"] >= 1 and a["you"] >= a["i"] + a["we"]),
    ("EFFORT", "Easy for them", 8,
     lambda s, a: bool(re.search(r"(no work on your end|zero work|one call|20-minute|twenty minutes|nothing has to move|"
                                 r"we handle|my team.s problem|hands off|in the background|no migration)", s, re.I))),
    ("COLD", "Cold acknowledged", 7,
     lambda s, a: bool(re.search(r"(out of the blue|out of left field|we have not met|have never spoken|not heard of me|"
                                 r"bold ask|not pitching you|cold email|first you are hearing)", s, re.I))),
]


def figures(body: str) -> list[str]:
    """Every £ amount and percentage in the text, as the assistant reads them."""
    raw = re.findall(r"£\s?[\d,]+", body) + re.findall(r"\b\d{1,3}\s?%", body)
    out = []
    for x in raw:
        n = re.sub(r"[£%\s]", "", x)
        n = re.sub(r"[.,]+$", "", n)
        if n and n not in out:
            out.append(n)
    return out


def score(subject: str, body: str, approved_figures=()) -> dict:
    sub, body = str(subject or ""), str(body or "").replace("\r", "")
    s = body.lower()
    words = len(body.split())
    a = {"i": len(re.findall(r"\bi\b|\bmy\b|\bme\b", s)),
         "you": len(re.findall(r"\byou\b|\byour\b|\byou're\b|\byou've\b", s)),
         "we": len(re.findall(r"\bwe\b|\bour\b|\bus\b", s))}
    paras = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    checks, earned = [], 0
    for key, name, pts, test in CHECKS:
        ok = bool(test(s, a))
        earned += pts if ok else 0
        checks.append({"key": key, "name": name, "points": pts, "ok": ok})
    mistakes = []

    def miss(name, why, cost):
        mistakes.append({"name": name, "why": why, "cost": cost})

    if "—" in body:
        miss("Long dash", "A long dash is the clearest sign an email was machine-written. Use a comma or a full stop.", 3)
    if "!" in body:
        miss("Exclamation mark", "It reads as sales. Take it out.", 3)
    if words > WORD_GUIDE + GRACE:
        over = words - WORD_GUIDE - GRACE
        cost = min(6, -(-over // 5))
        miss("Too long", f"This email is {words} words. Up to {WORD_GUIDE + GRACE} is fine; it is {over} past that.", cost)
    if re.search(r"\b(limited|ltd\.?|llp|plc)\b", body, re.I):
        miss("Legal company name", "Write the name people actually say. The legal name shows it came off a list.", 3)
    ok_figs = {str(x).strip() for x in approved_figures or ()}
    bad = [n for n in figures(body) if n not in ok_figs]
    if bad:
        miss("Unapproved figure", ", ".join(bad) + " is not on the approved list. Every figure needs a recorded source.", 15)
    if sub and sub != sub.lower():
        miss("Subject case", "Lower case reads like a person typing. Title Case reads like a marketing campaign.", 3)
    if len(sub) > 50:
        miss("Long subject", f"The subject is {len(sub)} characters. Aim for 30 to 50.", 5)
    if any(len(p) > 300 for p in paras):
        miss("Long paragraph", "One paragraph is too long to read on a phone.", 5)
    penalty = sum(m["cost"] for m in mistakes)
    total = max(0, earned - penalty)
    return {"score": total, "earned": earned, "penalty": penalty, "checks": checks, "mistakes": mistakes,
            "passed": sum(1 for c in checks if c["ok"]), "of": len(checks), "words": words,
            "blocked": bool(bad), "unapproved": bad}


def auto_approves(result: dict) -> bool:
    return result["score"] >= AUTO_APPROVE_AT and not result["blocked"]
