"""
stack_view.py — what the stack screens show (build session 1, step 3).

Pure functions over rows + a field map + core/store.py: the Leads list and record, the
Website research results and the Find email tiles and rungs. webapp/server.py only fetches
the rows and hands them in, so these can be checked without a server or a sheet.

Screen words come from core/lead_record.LABELS. Outside service names never reach the
screen: `plain()` turns them into the generic words the approved sample uses.
"""
from __future__ import annotations

import re

from . import lead_record as LR

# step number, screen name, column — the order of the approved sample's record table
STEPS = [
    (1, "Find email", "email_status"),
    (2, "Website research", "website_status"),
    (3, "Ice breaker", "icebreaker_status"),
    (5, "Sending", "push_status"),
    (6, "Reply", "reply_status"),
]

GOOD = {"found", "as-is", "enriched", "fallback", "written", "interested"}
ACCENT = {"pushed", "pushed_by_hand"}
BAD = {"dead_domain", "blocked", "error", "failed", "unsubscribe"}
NO_ADDRESS = {"no_email", "no_website", "no_person", "skipped"}
FOUND_EMAIL = {"as-is", "enriched", "fallback", "check_by_hand"}

# outside services -> the generic words on the approved sample (his "generic" default)
_SERVICE = [(re.compile(r"\b(icypeas|anymailfinder|apollo)\b", re.I), "email finder"),
            (re.compile(r"\bmillion\s*verifier\b", re.I), "verification service"),
            (re.compile(r"\binstantly\b", re.I), "sending platform"),
            (re.compile(r"\bendole\b", re.I), "company register")]

PRICE_CHECK_USD = 0.002
PRICE_FINDER_USD = 0.03


def plain(text) -> str:
    s = str(text or "")
    for rx, word in _SERVICE:
        s = rx.sub(word, s)
    return s


def tone(value: str) -> str:
    if value in GOOD:
        return "good"
    if value in ACCENT:
        return "accent"
    if value in BAD:
        return "bad"
    return "warn" if value and value != "not_interested" else ""


def pill(column: str, value: str) -> dict:
    v = str(value or "").strip()
    return {"value": v, "label": LR.LABELS.get(column, {}).get(v, v.replace("_", " ")) if v else "",
            "tone": tone(v)}


def labels() -> dict:
    return {c: [{"value": v, "label": LR.LABELS[c].get(v, v), "tone": tone(v)} for v in LR.VALUES[c]]
            for c in LR.COLUMNS}


# ── the rows ─────────────────────────────────────────────────────────

def step_values(row: dict, fm, stored: dict) -> dict:
    """The five step columns for one row: the app database first, then the sheet's own column."""
    out = {}
    for col in LR.COLUMNS:
        v = str(stored.get(col) or "").strip()
        if not v:
            try:
                v = LR.read(row, fm, col)
            except Exception:  # noqa: BLE001 - a sheet without the column reads blank
                v = ""
        out[col] = v
    return out


def _person(row: dict, fm) -> tuple[str, str]:
    return str(fm.get(row, "contact_name") or "").strip(), str(fm.get(row, "job_title") or "").strip()


FILTERS = [
    ("all", "All", lambda s: True),
    # step 1 is Find email (2026-11-07): the first filter is the leads it has not searched yet
    ("not_searched", "Email not searched", lambda s: not s["email_status"]),
    # "waiting" is worked out, never stored (core/icebreakers.py): an address + research, no line yet
    ("waiting", "Waiting for ice breaker", lambda s: s["icebreaker_status"] == "waiting" or (
        s["email_status"] in ("as-is", "enriched", "fallback") and bool(s["website_status"])
        and not s["icebreaker_status"] and not s["push_status"])),
    ("ready", "Ready to send", lambda s: s["icebreaker_status"] == "written" and not s["push_status"]),
    ("replied", "Replied", lambda s: bool(s["reply_status"])),
]


SHOW_ROWS = 500       # a campaign tab can hold 21,095 rows; the browser draws the first 500


def leads_view(rows: list[dict], fm, store, source: str, *, show: int = SHOW_ROWS) -> dict:
    stored = store.statuses(source)
    emails = store.email_results(source)
    out = []
    for row in rows:
        key = str(fm.get(row, "row_key") or "").strip()
        if not key:
            continue
        s = step_values(row, fm, stored.get(key, {}))
        name, title = _person(row, fm)
        out.append({"key": key, "company": str(fm.get(row, "company_name") or "").strip(),
                    "person": name, "title": title,
                    "website": str(fm.get(row, "website") or "").strip(),
                    "email": (emails.get(key) or {}).get("email", ""),
                    "steps": {c: pill(c, v) for c, v in s.items()},
                    "filters": [k for k, _l, f in FILTERS if f(s)]})
    counts = [{"id": k, "label": lbl, "count": sum(1 for r in out if k in r["filters"])}
              for k, lbl, _f in FILTERS]
    # each filter keeps its own first `show` rows, so a filter never looks empty by mistake
    keep: set[int] = set()
    for k, _l, _f in FILTERS:
        keep.update([i for i, r in enumerate(out) if k in r["filters"]][:show])
    return {"source": source, "rows": [r for i, r in enumerate(out) if i in keep],
            "filters": counts, "total": len(out), "show": show}


def next_step(s: dict) -> str:
    if not s["email_status"]:
        return "Find email"
    if s["email_status"] in NO_ADDRESS:
        return "None. No email address available."
    if s["email_status"] in ("held", "check_by_hand", "error"):
        return "Check this lead by hand"
    if not s["website_status"]:
        return "Website research"
    if s["icebreaker_status"] in ("", "waiting", "failed", "no_facts"):
        return "Ice breakers"
    if not s["push_status"]:
        return "Sending"
    if s["push_status"] == "held":
        return "Held in Sending. Check this lead by hand"
    if not s["reply_status"]:
        return "Waiting for reply"
    return "Complete"


def fact_lines(facts: dict) -> list[dict]:
    """Each extracted fact as one line with the page it came from."""
    f = facts or {}
    lines = []
    for v in f.get("vacancies") or []:
        lines.append({"kind": "Open role", "text": v.get("title") or v.get("line", ""), "url": v.get("url", "")})
    for a in f.get("awards") or []:
        lines.append({"kind": "Award", "text": a.get("name", ""), "url": a.get("url", "")})
    for c in f.get("cases") or []:
        lines.append({"kind": "Case study", "text": c.get("title") or c.get("line", ""), "url": c.get("url", "")})
    for p in f.get("posts") or []:
        lines.append({"kind": "News", "text": p.get("title") or p.get("line", ""), "url": p.get("url", "")})
    for r in f.get("reviews") or []:
        lines.append({"kind": "Review", "text": r.get("quote") or r.get("line", ""), "url": r.get("url", "")})
    if f.get("sectors"):
        lines.append({"kind": "Sectors served", "text": ", ".join(f["sectors"]), "url": ""})
    if f.get("software"):
        lines.append({"kind": "Software", "text": ", ".join(f["software"]), "url": ""})
    n = f.get("numbers") or {}
    bits = [f"since {n['since']}" if n.get("since") else "", n.get("clients", ""),
            f"team of {n['team']}" if n.get("team") else "", n.get("offices", "")]
    if any(bits):
        lines.append({"kind": "Numbers", "text": " · ".join(b for b in bits if b), "url": ""})
    return [x for x in lines if x["text"]]


def fact_chips(facts: dict) -> list[str]:
    f = facts or {}
    chips = []
    if f.get("vacancies"):
        chips.append("Open role")
    if f.get("awards"):
        chips.append("Award")
    if f.get("cases"):
        chips.append("Case study")
    if f.get("posts"):
        chips.append("News")
    if f.get("reviews"):
        chips.append("Reviews")
    if f.get("sectors"):
        chips.append("Sectors: " + ", ".join(f["sectors"][:2]))
    if f.get("software"):
        chips.append("Software")
    return chips


def lead_record(rows: list[dict], fm, store, source: str, key: str, headers=None) -> dict:
    row = next((r for r in rows if str(fm.get(r, "row_key") or "").strip() == str(key)), None)
    if row is None:
        return {"error": f"There is no lead '{key}' in this source."}
    s = step_values(row, fm, store.statuses(source).get(str(key), {}))
    name, title = _person(row, fm)
    fx = store.facts(source).get(str(key))
    em = store.email_results(source).get(str(key))
    heads = headers if headers is not None else list(row.keys())
    steps = []
    for n, label, col in STEPS:
        try:
            real = LR.header(fm, col, heads) or col
        except Exception:  # noqa: BLE001
            real = col
        steps.append({"n": n, "name": label, "column": real, **pill(col, s[col])})
    history = []
    if fx:
        history.append(f"Website researched on {fx.get('researched_on', '')}: {plain(fx.get('detail', ''))}")
    if em:
        history.append(f"Email step completed {em.get('updated', '')[:16]}")
    for col, text in (("icebreaker_status", "Ice breaker written"), ("push_status", "Queued in sending platform"),
                      ("reply_status", "Reply received")):
        if s[col]:
            history.append(text)
    return {
        "key": str(key), "company": str(fm.get(row, "company_name") or "").strip(),
        "person": name, "title": title,
        "email": (em or {}).get("email", "") or "",
        "website": str(fm.get(row, "website") or "").strip(),
        "next": next_step(s), "steps": steps,
        "research": None if not fx else {
            "status": pill("website_status", fx.get("website_status", "")),
            "detail": plain(fx.get("detail", "")), "checked": fx.get("researched_on", ""),
            "facts": fact_lines(fx.get("facts") or {}),
            "pages": fx.get("pages") or []},
        "find": None if not em else {
            "status": pill("email_status", s["email_status"]),
            "email": em.get("email", ""), "contact": em.get("contact", ""),
            "rung": rung_name_from_label(em.get("rung", "")),
            "method": plain(em.get("method", "")),
            "checks": int(em.get("checks") or 0), "finder_calls": int(em.get("finder_calls") or 0),
            "steps": [{"kind": st.get("kind", ""), "detail": plain(st.get("detail", ""))}
                      for st in em.get("steps") or []]},
        "history": history,
    }


# ── step 1: website research ────────────────────────────────────────

def research_view(rows: list[dict], fm, store, source: str) -> dict:
    facts = store.facts(source)
    stored = store.statuses(source)
    out, todo = [], 0
    for row in rows:
        key = str(fm.get(row, "row_key") or "").strip()
        if not key:
            continue
        fx = facts.get(key)
        if not fx:
            # step 2: only a lead Find email found an address for waits to be researched
            # (a lead whose sheet already has an ice breaker is never researched)
            if ((stored.get(key) or {}).get("email_status") in ("as-is", "enriched", "fallback")
                    and not str(fm.get(row, "icebreaker") or "").strip()):
                todo += 1
            continue
        out.append({"key": key, "company": fx.get("company") or str(fm.get(row, "company_name") or ""),
                    "host": fx.get("host", ""),
                    "status": pill("website_status", (stored.get(key) or {}).get("website_status")
                                   or fx.get("website_status", "")),
                    "chips": fact_chips(fx.get("facts") or {}),
                    "detail": plain(fx.get("detail", "")),
                    "facts": fact_lines(fx.get("facts") or {}),
                    "pages": fx.get("pages") or [],
                    "checked": fx.get("researched_on", "")})
    tally = {k: sum(1 for r in out if r["status"]["value"] == k) for k in LR.VALUES["website_status"]}
    return {"source": source, "rows": out, "to_research": todo, "tally": tally,
            "values": [pill("website_status", v) for v in LR.VALUES["website_status"]]}


# ── step 2: find email ───────────────────────────────────────────────

def _who(person: dict) -> str:
    names = person.get("name_from") or []
    names = [names] if isinstance(names, str) else list(names)
    joined = " ".join(str(n) for n in names).lower()
    m = re.search(r"contact[_ ]?(\d)", joined)
    if m:
        return f"contact {m.group(1)}"
    if not joined.strip() and person.get("address_from"):
        return "company address"
    return "the named person"


_METHOD = {"use_as_is": "Address in sheet", "guess_patterns": "Pattern and verify",
           "icypeas_domain": "Email finder", "icypeas_company": "Email finder",
           "anymailfinder": "Email finder"}
_HINT = {"use_as_is": "Uses the address already in the sheet. No cost.",
         "guess_patterns": "Common address patterns such as first@ and first.last@, checked by "
                           f"the verification service. About ${PRICE_CHECK_USD:.3f} each.",
         "icypeas_domain": f"Email finder. Charged only when an address is found. About ${PRICE_FINDER_USD:.2f}.",
         "icypeas_company": f"Email finder. Charged only when an address is found. About ${PRICE_FINDER_USD:.2f}.",
         "anymailfinder": f"Email finder. Charged only when an address is found. About ${PRICE_FINDER_USD:.2f}."}


def rung_name(person: dict) -> str:
    who = _who(person)
    methods = []
    for h in person.get("how") or []:
        m = _METHOD.get(h.get("method", ""), "Other method")
        if m not in methods:
            methods.append(m)
    if who == "company address":
        return "Company address"
    what = ", then ".join(methods) if methods else "No method"
    return f"{what}, {who}"


def rung_name_from_label(label: str) -> str:
    """'enriched contact 1' (the engine's rung label) -> a plain name for the record pane."""
    low = str(label or "").lower()
    if not low:
        return ""
    if low.startswith("fallback"):
        return "Company address"
    m = re.search(r"contact\s*(\d)", low)
    who = f"contact {m.group(1)}" if m else ""
    what = "Address in sheet" if low.startswith("as-is") else "Pattern and verify or email finder"
    return f"{what}, {who}" if who else what


def find_view(rows: list[dict], fm, store, source: str, recipe: dict | None) -> dict:
    stored = store.statuses(source)
    res = store.email_results(source)
    statuses = []
    ready = 0
    for row in rows:
        key = str(fm.get(row, "row_key") or "").strip()
        if not key:
            continue
        s = step_values(row, fm, stored.get(key, {}))
        if s["email_status"]:
            statuses.append(s["email_status"])
        else:                       # step 1: every lead is ready, website or not
            ready += 1
    count = {v: statuses.count(v) for v in LR.VALUES["email_status"]}
    found = sum(count[v] for v in FOUND_EMAIL)
    checks = sum(int(r.get("checks") or 0) for r in res.values())
    finder = sum(int(r.get("finder_calls") or 0) for r in res.values())
    by_rung: dict[str, int] = {}
    for r in res.values():
        if r.get("email") and r.get("rung"):
            by_rung[r["rung"]] = by_rung.get(r["rung"], 0) + 1
    rungs = []
    for i, p in enumerate((recipe or {}).get("people") or [], start=1):
        hints = []
        for h in p.get("how") or []:
            t = _HINT.get(h.get("method", ""), "")
            if t and t not in hints:
                hints.append(t)
        if _who(p) == "contact 2":
            hints.append("Runs only if contact 1 has no address.")
        if _who(p) == "company address":
            hints = ["General address such as info@, already in the sheet. No cost."]
        rungs.append({"n": i, "name": rung_name(p), "hint": " ".join(hints),
                      "found": by_rung.get(p.get("label", ""), 0)})
    return {
        "source": source, "recipe": {"id": (recipe or {}).get("id", ""), "name": (recipe or {}).get("name", "")},
        "processed": len(statuses), "ready": ready,
        "no_website": count["no_website"],
        "found": found, "from_sheet": count["as-is"], "found_new": count["enriched"],
        "company_address": count["fallback"],
        "not_found": len(statuses) - found,
        "checks": checks, "finder_calls": finder,
        "would_cost": round(checks * PRICE_CHECK_USD + finder * PRICE_FINDER_USD, 2),
        "counts": [{**pill("email_status", v), "count": n} for v, n in count.items() if n],
        "values": [pill("email_status", v) for v in ("as-is", "enriched", "fallback", "no_email", "no_website")],
        "rungs": rungs,
    }
