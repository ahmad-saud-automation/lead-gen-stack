"""
icebreakers.py — step 3: one ice-breaker line per lead, from the facts Website research found.

A RULE SET holds an ordered list of rungs, a line template and a default. Rungs are checked
top to bottom; the first rung whose fact source has something for this lead is used. Its
`fact` text (with {item} filled from the website) and its `implication` go into the template.
When no rung matches, one of the default versions is used, given out evenly.

    template  "I noticed {company} {fact}. We {shared_ground}, and in our experience that
               usually means {implication}."

`shared_ground` is fixed per campaign and A/B tested: the two versions are given out evenly.

The line is written by plain code from facts already on record, so it costs nothing and gives
the same result every time; nothing is invented. Every lead with a usable email address gets a
line once Website research has looked at it (2026-11-07, his rule): a rung that matches gives
its line; no matching rung, no website, a site that could not be read or one with nothing
usable on it gets the Default line (the floor rung). No lead with an email is left without one.
A lead that was already pushed is never rewritten (the already-emailed guard).

`no_facts` is no longer written; a lead stored as `no_facts` by an older run is written again.

Writes ONLY `icebreaker_status` (written · failed) through core/lead_record.py via
the store. "Waiting" is what the screen shows for a lead that can be written now; it is not
stored. The line itself stays in the app database, never in `Status`.
"""
from __future__ import annotations

import copy
import re

from . import lead_record as LR

STAGE = "icebreakers"
COLUMN = "icebreaker_status"
USABLE_EMAIL = ("as-is", "enriched", "fallback")
PUSHED = ("pushed", "pushed_by_hand")

# where a rung's {item} comes from, and what the screen says it needs
SOURCES: dict[str, str] = {
    "vacancies": "Requires a job listing on the careers page",
    "awards": "Requires an award or accreditation on the website",
    "articles": "Requires a recent post or client story",
    "sectors": "Requires named sectors, for example care homes",
    "software": "Requires an accounting software partner badge",
    "since": "Requires an “about us” history statement",
}

SOFTWARE_NAMES = {"xero": "Xero", "quickbooks": "QuickBooks", "freeagent": "FreeAgent", "sage": "Sage",
                  "dext": "Dext", "taxcalc": "TaxCalc", "iris": "IRIS", "cch": "CCH", "kashflow": "KashFlow",
                  "pandle": "Pandle", "hubdoc": "Hubdoc", "receipt bank": "Receipt Bank"}

_LEGAL = re.compile(r"[\s,]+(ltd\.?|limited|llp|plc|l\.l\.p\.)$", re.I)
_GENERIC = {"accountants", "accountancy", "accounting", "accounts", "tax", "taxation", "partners",
            "bookkeeping", "bookkeepers", "payroll", "services", "service", "ledger", "advisory",
            "practice", "co", "co.", "company", "group", "uk", "&", "and"}


class RuleSetError(ValueError):
    """A rule set that cannot be saved, in plain words."""


def short_company(name: str) -> str:
    """'Westbury Tax & Accounts Ltd' -> 'Westbury'. The name people say, not the legal one."""
    s = str(name or "").strip()
    s = _LEGAL.sub("", s).strip()
    words = s.split()
    while len(words) > 1 and words[-1].lower().strip(",") in _GENERIC:
        words.pop()
    return " ".join(words) or s


_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "mx", "rev"}


def first_name(contact: str) -> tuple[str, str]:
    """(first name, problem). A name that starts with a title is held for a human look."""
    parts = [p for p in str(contact or "").replace(".", " ").split() if p]
    if not parts:
        return "", "No contact name"
    if parts[0].lower() in _TITLES:
        return "", "The name starts with a title. Check it by hand"
    return parts[0][:1].upper() + parts[0][1:], ""


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else " and ".join([", ".join(items[:-1]), items[-1]]) if items else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".!?;:")


def item_for(source: str, facts: dict) -> tuple[str, str]:
    """(the {item} text, the website fact it came from) for one rung source; ('', '') if none."""
    f = facts or {}
    if source == "vacancies":
        for v in f.get("vacancies") or []:
            t = _clean(v.get("title") or "")
            if t:
                return t.lower(), v.get("line") or t
    elif source == "awards":
        for a in f.get("awards") or []:
            t = _clean(a.get("name") or "")
            if t:
                return t, t
    elif source == "articles":
        for x in (f.get("cases") or []) + (f.get("posts") or []):
            t = _clean(x.get("title") or x.get("line") or "")
            if t:
                return t, t
    elif source == "sectors":
        s = [str(x).strip() for x in (f.get("sectors") or []) if str(x).strip()][:2]
        if s:
            return _join(s), "Sectors served: " + ", ".join(f.get("sectors") or [])
    elif source == "software":
        s = [SOFTWARE_NAMES.get(str(x).lower(), str(x).title()) for x in (f.get("software") or [])][:2]
        if s:
            return _join(s), "Software: " + ", ".join(s)
    elif source == "since":
        y = str((f.get("numbers") or {}).get("since") or "").strip()
        if y:
            return y, f"In practice since {y}"
    return "", ""


def validate(ruleset: dict) -> dict:
    """Check a rule set before it is saved. Returns a clean copy; raises RuleSetError."""
    rs = copy.deepcopy(ruleset or {})
    if not str(rs.get("name") or "").strip():
        raise RuleSetError("Give the rule set a name.")
    rungs = rs.get("rungs") or []
    if not rungs:
        raise RuleSetError("A rule set needs at least one rung.")
    seen = set()
    for i, r in enumerate(rungs, start=1):
        r["name"] = str(r.get("name") or "").strip()
        r["fact"] = str(r.get("fact") or "").strip()
        r["implication"] = str(r.get("implication") or "").strip()
        r["on"] = bool(r.get("on", True))
        if not r["name"]:
            raise RuleSetError(f"Rung {i} has no name.")
        if r.get("source") not in SOURCES:
            raise RuleSetError(f"Rung {i} ({r['name']}) needs a fact source.")
        if "{item}" not in r["fact"]:
            raise RuleSetError(f"Rung {i} ({r['name']}): the fact text must contain {{item}}, "
                               "where the website fact goes.")
        if not r["implication"]:
            raise RuleSetError(f"Rung {i} ({r['name']}) needs an implication.")
        rid = str(r.get("id") or "").strip() or re.sub(r"[^a-z0-9]+", "-", r["name"].lower()).strip("-")
        while rid in seen:
            rid += "-2"
        r["id"] = rid
        seen.add(rid)
    if not [d for d in rs.get("default") or [] if d.get("fact") and d.get("implication")]:
        raise RuleSetError("The default needs at least one version.")
    if len([g for g in rs.get("shared_ground") or [] if str(g).strip()]) < 1:
        raise RuleSetError("Add at least one shared-ground line.")
    for k in ("{company}", "{fact}", "{implication}"):
        if k not in str(rs.get("template") or ""):
            raise RuleSetError(f"The template must contain {k}.")
    return rs


def pick(facts: dict, ruleset: dict) -> tuple[dict | None, str, str]:
    """(the first matching rung or None for the default, its {item}, the website fact)."""
    for r in ruleset.get("rungs") or []:
        if not r.get("on", True):
            continue
        item, evidence = item_for(r.get("source", ""), facts)
        if item:
            return r, item, evidence
    return None, "", ""


def compose(ruleset: dict, company: str, rung: dict | None, item: str, ground: int, default_version: int) -> str:
    if rung is not None:
        fact, implication = rung["fact"].replace("{item}", item), rung["implication"]
    else:
        versions = ruleset.get("default") or []
        d = versions[default_version % len(versions)]
        fact, implication = d["fact"], d["implication"]
    grounds = [g for g in ruleset.get("shared_ground") or [] if str(g).strip()]
    line = (ruleset.get("template") or "").format(
        company=short_company(company), fact=fact, implication=implication,
        shared_ground=grounds[ground % len(grounds)])
    return re.sub(r"\s+", " ", line).strip()


# ── which leads ──────────────────────────────────────────────────────

def lead_state(s: dict, has_facts: bool) -> str:
    """What the screen shows for one lead: written · no_facts · failed (stored) or
    waiting · no_email · not_researched (worked out, never stored)."""
    v = s.get(COLUMN, "")
    if v in ("written", "failed"):
        return v
    if v == "no_facts" and s.get("email_status", "") not in USABLE_EMAIL:
        return v
    if s.get("email_status", "") not in USABLE_EMAIL:
        return "no_email"
    if not s.get("website_status"):
        return "not_researched"
    return "waiting"


def _key(fm, row) -> str:
    return str(fm.get(row, "row_key") or "").strip()


def sheet_icebreaker(fm, row) -> str:
    """The ice breaker already in the lead's own sheet row ('' when none)."""
    try:
        return str(fm.get(row, "icebreaker") or "").strip()
    except Exception:  # noqa: BLE001 - a map without the field simply has no line
        return ""


def run(rows: list[dict], fm, store, source: str, ruleset: dict, *, keys=None, rewrite: bool = False,
        companies: dict | None = None) -> dict:
    """Write ice breakers for every waiting lead (or, with `keys` + `rewrite`, rewrite those).

    `rows` are the source rows; the step columns are read from the store. Returns counts."""
    ruleset = validate(ruleset)
    stored = store.statuses(source)
    facts = store.facts(source)
    done_lines = store.icebreakers(source)
    want = {str(k) for k in keys} if keys else None
    grounds = [0] * max(1, len([g for g in ruleset.get("shared_ground") or [] if str(g).strip()]))
    defaults = [0] * max(1, len(ruleset.get("default") or []))
    for rec in done_lines.values():
        if store_status(stored, source, rec["row_key"]) == "written":
            grounds[int(rec.get("shared_ground") or 0) % len(grounds)] += 1
            if rec.get("default_version") is not None:
                defaults[int(rec["default_version"]) % len(defaults)] += 1
    out = {"processed": 0, "written": 0, "default": 0, "from_sheet": 0, "no_facts": 0, "failed": 0,
           "skipped_sent": 0, "results": []}
    for row in rows:
        key = _key(fm, row)
        if not key or (want is not None and key not in want):
            continue
        s = {c: (stored.get(key) or {}).get(c, "") for c in LR.COLUMNS}
        if s["push_status"] in PUSHED:
            if want is not None:
                out["skipped_sent"] += 1
            continue
        if s[COLUMN] == "written" and not (rewrite and want is not None):
            continue
        # 2026-11-07: a lead whose sheet already holds an ice breaker keeps that line. It is
        # never researched, so it does not wait for a website_status.
        sheet_line = sheet_icebreaker(fm, row)
        if s["email_status"] not in USABLE_EMAIL or not (s["website_status"] or sheet_line):
            continue
        out["processed"] += 1
        if sheet_line:
            store.save_icebreaker(source, key, {
                "ruleset": ruleset["id"], "rung": "sheet", "rung_name": "From your sheet", "fact": "",
                "line": sheet_line, "shared_ground": 0, "default_version": None})
            store.write_status(STAGE, source, key, {COLUMN: "written"})
            out["written"] += 1
            out["from_sheet"] += 1
            out["results"].append({"key": key, "status": "written", "rung": "From your sheet"})
            continue
        # no website, unreadable, or nothing usable read: no rung can match, so the Default
        # line is used (the floor rung)
        fx = (facts.get(key) or {}).get("facts") or {} if s["website_status"] == "found" else {}
        try:
            rung, item, evidence = pick(fx, ruleset)
            old = done_lines.get(key) or {}
            if old and store_status(stored, source, key) == "written":   # a rewrite keeps the balance true
                grounds[int(old.get("shared_ground") or 0) % len(grounds)] -= 1
                if old.get("default_version") is not None:
                    defaults[int(old["default_version"]) % len(defaults)] -= 1
            ground = grounds.index(min(grounds))
            dv = defaults.index(min(defaults)) if rung is None else None
            company = (companies or {}).get(key) or str(fm.get(row, "company_name") or "")
            line = compose(ruleset, company, rung, item, ground, dv or 0)
        except Exception as e:  # noqa: BLE001 - one bad lead must not stop the run
            store.write_status(STAGE, source, key, {COLUMN: "failed"})
            out["failed"] += 1
            out["results"].append({"key": key, "status": "failed", "error": str(e)[:200]})
            continue
        grounds[ground] += 1
        if dv is not None:
            defaults[dv] += 1
        store.save_icebreaker(source, key, {
            "ruleset": ruleset["id"], "rung": rung["id"] if rung else "default",
            "rung_name": rung["name"] if rung else "Default", "fact": evidence, "line": line,
            "shared_ground": ground, "default_version": dv})
        store.write_status(STAGE, source, key, {COLUMN: "written"})
        out["written"] += 1
        out["default"] += 1 if rung is None else 0
        out["results"].append({"key": key, "status": "written", "rung": rung["name"] if rung else "Default"})
    return out


def store_status(stored: dict, source: str, key: str) -> str:
    return str((stored.get(str(key)) or {}).get(COLUMN, ""))
