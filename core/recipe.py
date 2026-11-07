"""
recipe.py — the Finding Recipe: who to email, in what order, by which way.

Before this, the order was burnt into pipeline.py (existing email -> pattern guess ->
Icypeas -> Anymailfinder) and organize.py picked ONE person per row. So a new idea —
"1st director, then 2nd director, then the address already on the row last" — needed
new Python every time.

A recipe makes all of that settings. It is plain rules, no LLM: an ordered list of
PEOPLE to try, each with an ordered list of WAYS to find them, plus when to stop and
which four columns may be written.

    config/recipes/<id>.json  ->  Recipe  ->  plan_for_row(recipe, row, firm, fm)
                                              -> the people THIS row actually offers

`plan_for_row` is pure and free — it spends nothing and calls nothing — so the same
call drives a real run and the "Try on 10 rows" preview. A way the row cannot use comes
back marked `ok: False` with a plain reason, which is both what the pipeline skips and
what the screen greys out: one answer, one place.

⛔ FOUR THINGS A RECIPE MAY NEVER CHANGE (docs/RECIPE-BUILDER.md §3). Checked here and
enforced in pipeline.py, never left to the screen:
  * catch-all stays off — only a MillionVerifier pass counts as a pass
  * nothing unverified is pushed — every marked result carries send_ready = "no"
  * only the four `write` columns are written; the rest of the sheet is read-only
  * a free test writes to neither the ledger nor the person cache

A campaign with NO recipe keeps today's exact order. Nothing in here runs for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import emailgen
from . import rules as rules_mod

# ── the vocabulary a recipe may use ──────────────────────────────────

# way -> plain meaning (the screen's help line comes from here, not from the UI)
METHODS = {
    "guess_patterns": "guess the format from this person's name and the website",
    "icypeas_domain": "ask Icypeas, using the website",
    "icypeas_company": "ask Icypeas, using the company name (for firms with no website)",
    "use_as_is": "use the address already in a column, no searching",
}

# how many formats a guess tries. careful = first@, first.last@, f.last@
PATTERN_MODES = {"careful": "lean", "thorough": "plus", "full_name": "fullname",
                 "first_then_full": "firstfull"}

# what MillionVerifier's answer means
VERIFY_MODES = {
    "must_pass": "only keep it if the check passes",
    "write_failed": "write it even if the check fails, marked as failed, never sent",
    "no_check": "do not check it (it can still never be sent)",
}

STOP_WHEN = {
    "first_pass": "stop at the first email that passes",
    "try_all_keep_best": "try everyone and keep the best",
}

WRITE_WHEN = {
    "always": "every row, straight away",
    "on_find": "only when something is found",
}

# Which name to take when one cell holds several, comma separated. The CH trigger tabs do
# exactly this: 'Endole director' is 'Daljeet Kaur Bangaa, Amandeep Singh' on 380 of its 842
# filled cells, and 'Contact 2' on 217 of 471. Without this the engine searched for a person
# literally called "Daljeet Kaur Bangaa, Amandeep Singh" and burned a check on every one.
# `whole` is the default and is byte-for-byte today's behaviour, so no existing recipe moves.
NAME_PICKS = {
    "whole": "the whole cell",
    "1st": "the 1st name in the cell",
    "2nd": "the 2nd name in the cell",
    "3rd": "the 3rd name in the cell",
}

NAME_PICK_INDEX = {"1st": 0, "2nd": 1, "3rd": 2}

# the four columns a recipe may write, and nothing else
WRITE_KEYS = ("email_to", "person_to", "method_to", "status_to")

# `status_to` is Find email's own `email_status` column (core/lead_record.py). It was
# "Status" until 2026-11-06 — his notes column, which Icebreaker Studio reads as "finished".
WRITE_DEFAULTS = {"email_to": "Found Email", "person_to": "Found For",
                  "method_to": "Found By", "status_to": "email_status",
                  "write_when": "always"}

# Two MORE columns a recipe may ask for, and only if it names them. They have no
# defaults on purpose: a recipe that stays silent keeps writing exactly four columns,
# so the CH tabs - which have no such headers - cannot gain a fifth write target by
# upgrade. Added 2026-10-13 for the Northwind "Organized" sheet, whose own columns are
# final_contact_index and final_first_name.
WRITE_KEYS_OPTIONAL = ("index_to", "first_name_to")

# Which vocabulary `method_to` and `status_to` are written in.
#   engine - the finder's own words: 'pattern_first.last', 'email_found'. The default,
#            and byte-for-byte what every recipe before today wrote.
#   source - the plain words his sheet expects: the rung's own first word
#            ('as-is' / 'enriched' / 'fallback'), and 'no_email' when a row finds
#            nothing. The rung label is the single source of truth for both.
WRITE_WORDS = {"engine": "the finder's own words", "source": "as-is / enriched / fallback"}

LIMIT_DEFAULTS = {"per_run": 30, "per_day": 0, "daily_spend_cap_usd": 0.0,
                  "search_same_person_once": True, "push_to": ""}

STOP_DEFAULTS = {"stop_when": "first_pass", "skip_row_if": {}, "last_resort": False}

# settings that live in Settings, not in a recipe. Naming one in a recipe is an error
# rather than a silent no-op, because "I switched catch-all on" must never look like it
# worked. (`catch_all` is the lock; the other two are global ceilings.)
LOCKED_OUT = ("catch_all", "accept_catchall", "daily_push_cap")

# statuses the recipe path can produce. The four V1 ones keep their meaning.
STATUS_FOUND = "email_found"              # passed the check — the only sendable outcome
STATUS_CHECK_BY_HAND = "check_by_hand"    # found, but a human must confirm the firm
STATUS_FAILED_CHECK = "email_failed_check"  # written, marked failed, never sent
STATUS_NOT_FOUND = "email_not_found"
STATUS_NO_PERSON = "skipped_no_person"    # the row offered nobody to try
STATUS_SKIPPED = "skipped_by_rule"        # skip_row_if said to leave the row alone

# outcomes that mean "this lead is finished, do not try it again"
TERMINAL_STATUSES = (STATUS_FOUND, STATUS_CHECK_BY_HAND, STATUS_FAILED_CHECK,
                     STATUS_NOT_FOUND, STATUS_NO_PERSON, STATUS_SKIPPED)


def _s(v) -> str:
    return str(v or "").strip()


def pick_name(cell: str, which: str = "whole") -> str:
    """One name out of a cell that may hold several, comma separated.

    `whole` returns the cell untouched — that is the default and today's behaviour. An
    ordinal past the end of the list returns "", which drops that rung for this row; that is
    deliberate, because "the 2nd name" on a one-director firm means nobody, not the 1st
    again. A cell with no comma has exactly one name, so `1st` and `whole` agree on it."""
    cell = _s(cell)
    if not cell or which in ("", "whole"):
        return cell
    i = NAME_PICK_INDEX.get(which)
    if i is None:                       # an unknown value is never silently "the 1st"
        return cell
    parts = [p for p in (q.strip() for q in cell.split(",")) if p]
    return parts[i] if i < len(parts) else ""


def same_person_in(cell: str, key: str) -> bool:
    """Is the person whose `_name_key` is `key` named in this cell?

    A comma in these columns means TWO different things, so both readings are compared and
    either one counts:
      · "Smith, Ian"           — one person, surname first (`_name_key` sorts the words)
      · "Jane Doe, Brian Old"  — a list of people
    Comparing only the whole cell let the leaver through whenever the cell held a list;
    comparing only the parts broke "Smith, Ian". Both, and nothing is missed. Used by
    `never_if_same_as` and by its mirror `only_if_same_as`, so the two can never disagree."""
    cell, key = _s(cell), _s(key)
    if not cell or not key:
        return False
    parts = [cell] + [p for p in (q.strip() for q in cell.split(",")) if p]
    return any(_name_key(p) == key for p in parts)


def _name_key(name: str) -> str:
    """Letters only, words sorted — so "Ian Smith" and "Smith, Ian" are one person.

    Used ONLY to compare two names inside the same sheet row (never to decide who an
    address belongs to; the address decides that)."""
    words = sorted(w for w in re.sub(r"[^a-z ]", " ", _s(name).lower()).split() if w)
    return " ".join(words)


# words that say nothing about WHICH firm this is. Dropped before two company names are
# compared, so "Smith & Co" on one tab and "Smith and Co Ltd" on another are one firm.
COMPANY_NOISE = {"ltd", "limited", "llp", "lllp", "plc", "co", "company", "and", "the",
                 "group", "holdings", "services", "accountants", "accountancy"}


def company_words(company: str) -> list[str]:
    """The words that actually identify a firm. Never empty if anything was passed."""
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", str(company or "").lower()).split() if w]
    return [w for w in words if w not in COMPANY_NOISE] or words


def _as_list(v) -> list[str]:
    """A column pick is one name or an ordered list of names to try in turn."""
    if v in (None, ""):
        return []
    if isinstance(v, (list, tuple)):
        return [_s(x) for x in v if _s(x)]
    return [_s(v)]


# ── the shapes ───────────────────────────────────────────────────────

class Way:
    """One way to find one person. Dict in, attributes out."""

    def __init__(self, raw: dict | str):
        raw = {"method": raw} if isinstance(raw, str) else dict(raw or {})
        self.raw = raw
        self.method = _s(raw.get("method"))
        self.patterns = _s(raw.get("patterns")) or "careful"
        self.verify = _s(raw.get("verify")) or "must_pass"
        # for icypeas_company: an address on a domain that looks nothing like the
        # company name is still written, but marked for a human
        self.note_if_domain_mismatch = bool(raw.get("note_if_domain_mismatch", True))

    @property
    def pattern_mode(self) -> str:
        """The emailgen mode behind "careful" / "thorough"."""
        return PATTERN_MODES.get(self.patterns, "lean")

    def to_dict(self) -> dict:
        return dict(self.raw)

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Way {self.method} {self.verify}>"


class Person:
    """One rung of the ladder: who to try, and the ways to find them."""

    def __init__(self, raw: dict, idx: int = 0):
        raw = dict(raw or {})
        self.raw = raw
        self.idx = idx
        self.label = _s(raw.get("label")) or f"Person {idx + 1}"
        # one column, or several tried in order ("Endole director, then Apollo director")
        self.name_from = _as_list(raw.get("name_from"))
        # which name to take when the cell holds a comma-separated list — see NAME_PICKS
        self.name_pick = _s(raw.get("name_pick")) or "whole"
        self.address_from = _s(raw.get("address_from"))
        self.only_if = raw.get("only_if") or {}
        # the mirror pair: only try them IF they are the person in one of these columns /
        # never try them if they are. Both read a comma cell through `same_person_in`.
        self.only_if_same_as = _as_list(raw.get("only_if_same_as"))
        self.never_if_same_as = _as_list(raw.get("never_if_same_as"))
        self.how = [Way(w) for w in (raw.get("how") or [])]

    def to_dict(self) -> dict:
        return dict(self.raw)

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Person {self.idx + 1} {self.label!r} ways={len(self.how)}>"


class Recipe:
    """One saved recipe. A campaign points at it by id, so one recipe serves many tabs."""

    def __init__(self, raw: dict):
        raw = dict(raw or {})
        self.raw = raw
        self.id = _s(raw.get("id"))
        self.name = _s(raw.get("name")) or self.id
        self.note = _s(raw.get("note"))
        self.updated = _s(raw.get("updated"))
        self.people = [Person(p, i) for i, p in enumerate(raw.get("people") or [])]
        self.stop = {**STOP_DEFAULTS, **(raw.get("stop") or {})}
        self.write = {**WRITE_DEFAULTS, **(raw.get("write") or {})}
        self.limits = {**LIMIT_DEFAULTS, **(raw.get("limits") or {})}

    # ── the settings a run reads ─────────────────────────────────

    @property
    def stop_when(self) -> str:
        return _s(self.stop.get("stop_when")) or "first_pass"

    @property
    def skip_row_if(self) -> dict:
        return self.stop.get("skip_row_if") or {}

    @property
    def last_resort(self) -> bool:
        return bool(self.stop.get("last_resort", False))

    @property
    def write_when(self) -> str:
        return _s(self.write.get("write_when")) or "always"

    @property
    def write_words(self) -> str:
        """`engine` (the default, unchanged behaviour) or `source`. See WRITE_WORDS."""
        return _s(self.write.get("words")) or "engine"

    @property
    def search_same_person_once(self) -> bool:
        return bool(self.limits.get("search_same_person_once", True))

    @property
    def per_run(self) -> int:
        return max(0, int(self.limits.get("per_run") or 0))

    @property
    def per_day(self) -> int:
        return max(0, int(self.limits.get("per_day") or 0))

    def write_targets(self) -> dict:
        """The ONLY sheet columns this recipe may write: the four required ones, plus
        any of WRITE_KEYS_OPTIONAL this recipe actually names.

        This is the guard on his sheet: `Contact Name` and `Email Source` are not in
        here, so the old write-back can no longer touch them. An optional key left
        unset is absent from this dict entirely, so a recipe that does not ask for it
        keeps a four-column allow-list."""
        out = {k: _s(self.write.get(k)) or WRITE_DEFAULTS[k] for k in WRITE_KEYS}
        for k in WRITE_KEYS_OPTIONAL:
            col = _s(self.write.get(k))
            if col:
                out[k] = col
        return out

    def write_columns(self) -> list[str]:
        """Those columns, as a plain list of headers, in a stable order."""
        t = self.write_targets()
        return [t[k] for k in WRITE_KEYS + WRITE_KEYS_OPTIONAL if k in t]

    def to_dict(self) -> dict:
        return dict(self.raw)

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Recipe {self.id or '(unsaved)'} people={len(self.people)}>"


# ── validation: every problem at once, in plain English ──────────────

def validate(recipe) -> list[str]:
    """Every problem with a recipe, so they are all fixable in one pass.

    Empty list = the recipe is usable. The wording is what the screen shows, so it
    names the person by the label he gave it, not by an index."""
    r = recipe if isinstance(recipe, Recipe) else Recipe(recipe)
    issues: list[str] = []

    if not r.name:
        issues.append("the recipe needs a name")
    if not r.people:
        issues.append("a recipe needs at least one person to try")

    for key in LOCKED_OUT:
        for block, label in ((r.limits, "limits"), (r.stop, "stop rules"), (r.write, "write")):
            if key in block:
                issues.append(f"'{key}' cannot be set in a recipe ({label}) — "
                              "it is a locked setting in Settings")

    for p in r.people:
        where = f"person {p.idx + 1} ({p.label})"
        if not p.name_from and not p.address_from:
            issues.append(f"{where}: pick the column holding this person's name, "
                          "or the column holding their address")
        if not p.how:
            issues.append(f"{where}: pick at least one way to find them")
        if p.name_pick not in NAME_PICKS:
            issues.append(f"{where}: '{p.name_pick}' is not a choice of which name to take "
                          f"(choose one of: {', '.join(NAME_PICKS)})")
        elif p.name_pick != "whole" and not p.name_from:
            issues.append(f"{where}: '{NAME_PICKS[p.name_pick]}' needs a name column "
                          "to take it from")
        if p.only_if_same_as and not p.name_from:
            # with no name there is nobody to compare, so the test would silently drop
            # every row — the one failure mode that looks like "the recipe found nothing"
            issues.append(f"{where}: 'only if this person is the one in …' needs a name "
                          "column, or there is nobody to compare")
        both = [c for c in p.only_if_same_as if c in p.never_if_same_as]
        if both:
            issues.append(f"{where}: '{both[0]}' is in both 'only if this person is the one "
                          "in …' and 'never if the same as …' — nothing can ever pass")
        for i, w in enumerate(p.how, start=1):
            if w.method not in METHODS:
                issues.append(f"{where}, way {i}: unknown way '{w.method}' "
                              f"(choose one of: {', '.join(METHODS)})")
            if w.verify not in VERIFY_MODES:
                issues.append(f"{where}, way {i}: unknown check '{w.verify}' "
                              f"(choose one of: {', '.join(VERIFY_MODES)})")
            if w.method == "guess_patterns" and w.patterns not in PATTERN_MODES:
                issues.append(f"{where}, way {i}: formats must be "
                              f"{' or '.join(PATTERN_MODES)}, not '{w.patterns}'")
            if w.method == "use_as_is" and not p.address_from:
                issues.append(f"{where}, way {i}: 'use the address that is already there' "
                              "needs an address column on this person")
        for why in rules_mod.validate_rules(p.only_if):
            issues.append(f"{where}, 'only if': {why}")

    if r.stop_when not in STOP_WHEN:
        issues.append(f"'{r.stop_when}' is not a stop rule "
                      f"(choose one of: {', '.join(STOP_WHEN)})")
    for why in rules_mod.validate_rules(r.skip_row_if):
        issues.append(f"'skip the row if': {why}")

    if r.write_when not in WRITE_WHEN:
        issues.append(f"'{r.write_when}' is not a write rule "
                      f"(choose one of: {', '.join(WRITE_WHEN)})")
    if r.write_words not in WRITE_WORDS:
        issues.append(f"'{r.write_words}' is not a way to word the result "
                      f"(choose one of: {', '.join(WRITE_WORDS)})")
    from . import lead_record
    bad = lead_record.forbidden_headers("find_email")
    for key, col in r.write_targets().items():
        if col in bad:
            issues.append(f"'{col}' cannot be written by Find email — "
                          + ("it is your own notes column; use email_status"
                             if col == lead_record.NOTES_COLUMN
                             else "it belongs to another step"))
    seen: dict[str, str] = {}
    for key, col in r.write_targets().items():
        if col in seen:
            issues.append(f"'{col}' is picked for two things at once "
                          f"({seen[col]} and {key}) — each result needs its own column")
        seen[col] = key

    return issues


def check_against_sheet(recipe, headers) -> dict:
    """Does this recipe's columns exist in the real sheet?

    The silent-discard trap, again: a Google Sheets write to a column that is not there
    is dropped with no error. Read columns that are missing are a warning (that person
    simply never runs); write columns that are missing are blocking."""
    r = recipe if isinstance(recipe, Recipe) else Recipe(recipe)
    real = {re.sub(r"[^a-z0-9]", "", _s(h).lower()) for h in (headers or [])}

    def present(col: str) -> bool:
        return re.sub(r"[^a-z0-9]", "", _s(col).lower()) in real

    missing_read, missing_write = [], []
    for p in r.people:
        for col in (p.name_from + ([p.address_from] if p.address_from else [])
                    + p.never_if_same_as + p.only_if_same_as):
            if col and not present(col) and col not in missing_read:
                missing_read.append(col)
    for col in r.write_columns():
        if col and not present(col) and col not in missing_write:
            missing_write.append(col)

    blocking = [f"'{c}' is picked to be written to, but there is no such column in this "
                "sheet — a write there is silently discarded" for c in missing_write]
    warnings = [f"'{c}' is read by this recipe, but there is no such column in this sheet"
                for c in missing_read]
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings,
            "missing_read": missing_read, "missing_write": missing_write}


# ── the plan for one row (pure, free, no network) ────────────────────

def _row_domain(row: dict, firm: dict, fm) -> str:
    """This firm's domain. The organized firm already cleaned it; fall back to the row."""
    if firm and _s(firm.get("lead_domain")):
        return _s(firm.get("lead_domain"))
    from . import organize as organize_mod
    return organize_mod.clean_domain(fm.get(row, "website") if fm else _s(row.get("Website")))


def _company_of(row: dict, firm: dict, fm) -> str:
    if firm and _s(firm.get("Company Name")):
        return _s(firm.get("Company Name"))
    return fm.get(row, "company_name") if fm else _s(row.get("Company Name"))


def _read_col(row: dict, col: str, fm) -> str:
    """One column off the raw row. A recipe names real headers, but an engine field
    name works too, which is what `fm.resolve` already does for rules."""
    if not col:
        return ""
    return fm.resolve(row, col) if fm else _s(row.get(col))


def _why_not(method: str, *, name: str, first: str, last: str, domain: str,
             company: str, address: str) -> str:
    """Why this way cannot run on this row — the sentence the screen greys out with."""
    if method == "use_as_is":
        if not address:
            return "there is no address in that column on this row"
        if "@" not in address:
            return f"'{address}' is not an email address"
        return ""
    if not name:
        return "this row has no name for this person"
    if method == "guess_patterns":
        if not domain:
            return "this firm has no website, so there is no format to guess"
        if not (first and last):
            return "only one name word, so there is nothing to guess beyond first@"
        return ""
    if method == "icypeas_domain":
        return "" if domain else "this firm has no website"
    if method == "icypeas_company":
        return "" if company else "this row has no company name"
    return f"'{method}' is not a way this engine knows"


def plan_for_row(recipe, row: dict, firm: dict | None = None, fm=None) -> dict:
    """Who this recipe would try on ONE row, in order — and why it dropped the rest.

    Spends nothing and calls nothing, so the run and the "Try on 10 rows" preview are
    the same code. Each person comes back with their ways already checked against this
    row: `ok: False` ways are the ones the screen greys out and the run skips."""
    r = recipe if isinstance(recipe, Recipe) else Recipe(recipe)
    row = row or {}
    firm = firm or {}
    if fm is None:
        from . import fieldmap as fieldmap_mod
        fm = fieldmap_mod.FieldMap({})

    domain = _row_domain(row, firm, fm)
    company = _company_of(row, firm, fm)

    # the whole row, skipped by his own rule
    if r.skip_row_if:
        hit, _reason = rules_mod.match(row, r.skip_row_if, fm)
        if hit:
            return {"skip": True, "skip_reason": "this row matches 'skip the row if'",
                    "people": [], "dropped": [], "domain": domain, "company": company}

    people, dropped = [], []
    taken: set[str] = set()         # the same person named twice in the ladder runs once

    for p in r.people:
        # "only try this person if …"
        if p.only_if:
            passed, why = rules_mod.match(row, p.only_if, fm)
            if not passed:
                dropped.append({"label": p.label, "why": f"'only if' not met: {why}"
                                if why else "'only if' not met"})
                continue

        name, name_col = "", ""
        for col in p.name_from:                  # first column that actually has a name
            v = pick_name(_read_col(row, col, fm), p.name_pick)
            if v:
                name, name_col = v, col
                break
        address = _read_col(row, p.address_from, fm) if p.address_from else ""

        if not name and not address:
            cols = " / ".join(p.name_from + ([p.address_from] if p.address_from else []))
            dropped.append({"label": p.label, "why": f"nothing in {cols} on this row"})
            continue

        key = _name_key(name)

        # "only try this person if they ARE the person in one of those columns" — the mirror
        # of never_if_same_as below. What it is for: the row already holds an address, and it
        # is only worth using when it belongs to a director. Give the rung `name_from:
        # ["Email Person"]` + `address_from: "Email"` and this test, and the address is used
        # as it is when its owner is a director, and ignored when it is somebody else's.
        if p.only_if_same_as:
            hit = ""
            for col in p.only_if_same_as:
                if key and same_person_in(_read_col(row, col, fm), key):
                    hit = col
                    break
            if not hit:
                who = name or "this person"
                dropped.append({"label": p.label,
                                "why": f"{who} is not the person in "
                                       f"{' / '.join(p.only_if_same_as)}"})
                continue

        # "skip if this person is the same as the person in those columns"
        clash = ""
        for col in p.never_if_same_as:
            if key and same_person_in(_read_col(row, col, fm), key):
                clash = col
                break
        if clash:
            dropped.append({"label": p.label,
                            "why": f"{name} is the same person as '{clash}'"})
            continue

        if key and key in taken:
            dropped.append({"label": p.label, "why": f"{name} is already tried higher up"})
            continue

        parts = emailgen.derive_name(name,
                                     fallback_first=fm.get(row, "contact_first") if fm else "",
                                     fallback_last=fm.get(row, "contact_last") if fm else "")
        ways = []
        for w in p.how:
            why = _why_not(w.method, name=name, first=parts["first"], last=parts["last"],
                           domain=domain, company=company, address=address)
            ways.append({"method": w.method, "patterns": w.patterns,
                         "pattern_mode": w.pattern_mode, "verify": w.verify,
                         "note_if_domain_mismatch": w.note_if_domain_mismatch,
                         "ok": not why, "why": why, "way": w})

        usable = [w for w in ways if w["ok"]]
        if not usable:
            first_why = ways[0]["why"] if ways else "no way to find them is set"
            dropped.append({"label": p.label, "why": f"{name or address}: {first_why}"})
            continue

        # The person is reserved only now that this rung can actually BE tried. Reserving
        # before the test above let a rung that was dropped for having no way to run block
        # the same person lower down: on the Organized tabs, where "as-is contact 1" names
        # the same person as "enriched contact 1", every row with a name and no address in
        # the column ended `skipped_no_person` - the whole of C1 in the first test run
        # (2026-10-13). Nothing in the shipped director-waterfall recipe changes: its own
        # rungs already exclude each other with `never_if_same_as`.
        if key:
            taken.add(key)

        people.append({"label": p.label, "name": name, "name_column": name_col,
                       "first": parts["first"], "last": parts["last"],
                       "middle": parts["middle"], "address": address,
                       "address_column": p.address_from, "ways": ways,
                       "person_key": key, "idx": p.idx})

    reason = ""
    if not people:
        reason = ("no one on this row can be tried: "
                  + "; ".join(d["why"] for d in dropped)) if dropped else \
                 "this recipe has nobody to try"
    return {"skip": False, "skip_reason": reason, "people": people, "dropped": dropped,
            "domain": domain, "company": company}


def estimate_row(plan: dict) -> dict:
    """What one row would cost at most, for the free preview. Icypeas charges only on a
    find, so its number is a ceiling, not a bill."""
    checks = icypeas = 0
    for person in plan.get("people", []):
        for w in person["ways"]:
            if not w["ok"]:
                continue
            if w["method"] == "guess_patterns":
                n = len(emailgen.PATTERN_LIBRARY.get(w["pattern_mode"], []))
                checks += n
            elif w["method"] in ("icypeas_domain", "icypeas_company"):
                icypeas += 1
                checks += 0 if w["verify"] == "no_check" else 1
            elif w["method"] == "use_as_is":
                checks += 0 if w["verify"] == "no_check" else 1
    return {"max_checks": checks, "max_icypeas_credits": icypeas,
             "people": len(plan.get("people", []))}


def person_cache_key(company: str, name: str) -> str:
    """One person at one firm. "Search the same person once" keys on this, so the 32
    firms that sit on two tabs are not searched twice.

    The firm side drops Ltd / & Co / and, because the two tabs do not spell it the same."""
    return f"{' '.join(sorted(company_words(company)))}|{_name_key(name)}"


# ── files ────────────────────────────────────────────────────────────

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _s(text).lower()).strip("-")
    return s[:63] or "recipe"


def blank(name: str = "") -> dict:
    """A new, empty recipe — one person, one way, the safe defaults."""
    return {"id": slug(name) if name else "", "name": _s(name), "note": "", "updated": "",
            "people": [{"label": "Person 1", "name_from": "", "name_pick": "whole",
                        "address_from": "", "only_if": {},
                        "only_if_same_as": [], "never_if_same_as": [],
                        "how": [{"method": "guess_patterns", "patterns": "careful",
                                 "verify": "must_pass"}]}],
            "stop": dict(STOP_DEFAULTS), "write": dict(WRITE_DEFAULTS),
            "limits": dict(LIMIT_DEFAULTS)}


def load(path) -> Recipe | None:
    """One recipe file. A missing file is None, not a crash — a campaign pointing at a
    recipe that is gone must fall back to today's order, not stop the run."""
    p = Path(path)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8")) or {}
    raw.setdefault("id", p.stem)
    return Recipe(raw)


def load_dir(directory) -> dict:
    """Every recipe in config/recipes, keyed by id. Missing folder = no recipes."""
    d = Path(directory)
    if not d.is_dir():
        return {}
    out = {}
    for f in sorted(d.glob("*.json")):
        try:
            r = load(f)
        except (ValueError, OSError):
            continue                 # a broken file must not stop the other recipes
        if r is not None:
            out[r.id or f.stem] = r
    return out


def save(directory, recipe: dict, *, today: str = "") -> Path:
    """Write one recipe. The id comes from the name once and never changes after, so a
    campaign pointing at it keeps pointing at it."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    raw = dict(recipe or {})
    rid = _s(raw.get("id")) or slug(raw.get("name") or "")
    if not ID_RE.match(rid):
        raise ValueError(f"'{rid}' is not a usable recipe id (letters, numbers, - and _)")
    raw["id"] = rid
    if today:
        raw["updated"] = today
    p = d / f"{rid}.json"
    p.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def for_campaign(campaign, recipes: dict):
    """The recipe a campaign uses, or None for "keep today's order".

    None is the normal case and must stay cheap: every existing campaign has no
    `recipe` key at all."""
    rid = ""
    if campaign is not None:
        raw = getattr(campaign, "raw", None) or {}
        rid = _s(raw.get("recipe") or getattr(campaign, "recipe", ""))
    if not rid:
        return None
    return (recipes or {}).get(rid)
