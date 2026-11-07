"""
lead_record.py — the shared lead record: one status column per pipeline step.

THE TRAP THIS FIXES (found 2026-10-08): the engine wrote `email_found` / `no_website` into
`Status`, and Icebreaker Studio reads ANY text in `Status` as "this lead is finished", so it
skipped every lead the engine had just found. `Status` is his own notes column. From now on
no step writes it; each step writes its own column and nothing else.

    column             written only by     stored values
    website_status     research            found · not_found · dead_domain · blocked
    email_status       find_email          as-is · enriched · fallback · no_email · no_website
                                           · no_person · check_by_hand · held · skipped · error
    icebreaker_status  icebreakers         written · waiting · no_facts · failed
    push_status        sending             pushed · held · failed · pushed_by_hand
    reply_status       replies             interested · not_interested · ooo · wrong_person
                                           · unsubscribe
    Status             NOBODY              his own notes

`check_by_hand`, `held` and `skipped` were added on his "ok, all 3 values" (2026-11-06): each
is a real engine outcome that Sending must hold, and folding them into `no_email` would make
"needs a human look" indistinguishable from "dead".

Each sheet maps a logical column to its real header through its field map. Without an explicit
line the column's own name is used, and `email_status` also answers to `enrich_status` (the
Organized-style sheets). `push_status` deliberately has NO alias: the Organized sheets call it
`status`, which compares equal to his `Status` once case is ignored, so it is only ever reached
through an explicit field-map line.
"""
from __future__ import annotations

import re

STAGES: dict[str, tuple[str, ...]] = {
    "research": ("website_status",),
    "find_email": ("email_status",),
    "icebreakers": ("icebreaker_status",),
    "sending": ("push_status",),
    "replies": ("reply_status",),
}

VALUES: dict[str, tuple[str, ...]] = {
    "website_status": ("found", "not_found", "dead_domain", "blocked"),
    "email_status": ("as-is", "enriched", "fallback", "no_email", "no_website", "no_person",
                     "check_by_hand", "held", "skipped", "error"),
    "icebreaker_status": ("written", "waiting", "no_facts", "failed"),
    "push_status": ("pushed", "held", "failed", "pushed_by_hand"),
    "reply_status": ("interested", "not_interested", "ooo", "wrong_person", "unsubscribe"),
}

# what the screens call each stored value (plain words, no internal names)
LABELS: dict[str, dict[str, str]] = {
    "website_status": {"found": "Found", "not_found": "Not found",
                       "dead_domain": "Unreachable", "blocked": "Blocked"},
    "email_status": {"as-is": "From sheet", "enriched": "Found", "fallback": "Company address",
                     "no_email": "Not found", "no_website": "No website",
                     "no_person": "No contact", "check_by_hand": "Check by hand",
                     "held": "Held", "skipped": "Skipped", "error": "Error"},
    "icebreaker_status": {"written": "Written", "waiting": "Waiting",
                          "no_facts": "No facts", "failed": "Failed"},
    "push_status": {"pushed": "Pushed", "held": "Held", "failed": "Failed",
                    "pushed_by_hand": "Pushed by hand"},
    "reply_status": {"interested": "Interested", "not_interested": "Not interested",
                     "ooo": "Out of office", "wrong_person": "Wrong person",
                     "unsubscribe": "Unsubscribe"},
}

COLUMNS: tuple[str, ...] = tuple(c for cols in STAGES.values() for c in cols)
OWNER: dict[str, str] = {c: stage for stage, cols in STAGES.items() for c in cols}

ALIASES: dict[str, tuple[str, ...]] = {
    "website_status": ("website_status",),
    "email_status": ("email_status", "enrich_status"),
    "icebreaker_status": ("icebreaker_status",),
    "push_status": ("push_status",),
    "reply_status": ("reply_status",),
}

NOTES_COLUMN = "Status"          # his — never written by any step

# values that mean "this step is finished for this row"; `error` is retried next run
RETRY_VALUES = {"error"}


class WriteRefused(ValueError):
    """A step tried to write a column it does not own."""


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def allowed(stage: str) -> tuple[str, ...]:
    """The ONLY pipeline columns a step may write."""
    if stage not in STAGES:
        raise WriteRefused(f"unknown step '{stage}' (choose one of: {', '.join(STAGES)})")
    return STAGES[stage]


def header(fm, column: str, headers=None) -> str:
    """The real sheet header for a logical pipeline column.

    An explicit field-map line always wins. Otherwise, with the sheet's headers known, the
    first alias present in the sheet; without them, the column's own name."""
    if column not in OWNER:
        raise WriteRefused(f"'{column}' is not a pipeline column")
    mapped = (getattr(fm, "mapping", None) or {}).get(column) if fm is not None else ""
    if mapped:
        return mapped
    if headers is not None:
        real = {_norm(h): str(h).strip() for h in headers}
        for alias in ALIASES[column]:
            if _norm(alias) in real:
                return real[_norm(alias)]
        return ""
    return column


def read(row: dict, fm, column: str) -> str:
    """One pipeline column's value off a raw row ('' when the row has no such column)."""
    h = header(fm, column, headers=list(row.keys()))
    return str(row.get(h) or "").strip() if h else ""


def done(row: dict, fm, column: str) -> bool:
    """True when this step already finished the row (any value except a retryable one)."""
    v = read(row, fm, column).lower()
    return bool(v) and v not in RETRY_VALUES


def forbidden_headers(stage: str, fm=None, headers=None) -> set[str]:
    """Every header this step must never write: his `Status`, plus the other steps' columns."""
    out = {NOTES_COLUMN}
    for col, owner in OWNER.items():
        if owner != stage:
            h = header(fm, col, headers)
            if h:
                out.add(h)
    return out


def guard(stage: str, update: dict, fm=None, headers=None, *, key_header: str = "") -> dict:
    """Refuse an update that touches `Status` or another step's column. Returns it unchanged.

    Matching is exact on `Status` (his notes column) and exact on the other steps' resolved
    headers, so an Organized sheet's lowercase `status` (= push_status there) is protected
    from every step except Sending."""
    allowed(stage)
    bad = forbidden_headers(stage, fm, headers)
    for k in update:
        if k == key_header:
            continue
        if k in bad:
            raise WriteRefused(f"step '{stage}' may not write '{k}'")
    return update


def check_value(column: str, value: str) -> str:
    v = str(value or "").strip()
    if v not in VALUES.get(column, ()):
        raise WriteRefused(f"'{v}' is not an allowed value for {column} "
                           f"(choose one of: {', '.join(VALUES.get(column, ()))})")
    return v


def stage_update(stage: str, values: dict, fm=None, headers=None) -> dict:
    """{logical column: value} -> {real header: value}, after the allow-list and value checks."""
    own = allowed(stage)
    out = {}
    for col, val in values.items():
        if col not in own:
            raise WriteRefused(f"step '{stage}' may not write '{col}'")
        h = header(fm, col, headers)
        if not h:
            raise WriteRefused(f"the sheet has no '{col}' column — add the pipeline columns first")
        out[h] = check_value(col, val)
    return guard(stage, out, fm, headers)


# ── Find email: engine outcome -> email_status ───────────────────────

_SIMPLE = {
    "email_not_found": "no_email",
    "email_failed_check": "no_email",
    "no_website": "no_website",
    "skipped_no_person": "no_person",
    "check_by_hand": "check_by_hand",
    "hold_security_gateway": "held",
    "skipped_by_rule": "skipped",
}


def email_status_for(result: dict) -> str:
    """The stored email_status for one Find email result, from either pipeline path.

    A found address is 'as-is' when it was already on the row, 'fallback' when it came from
    a rung labelled as the fallback column, and 'enriched' when it was guessed or found."""
    status = str(result.get("status") or "").strip()
    if status in _SIMPLE:
        return _SIMPLE[status]
    if status == "email_found" and str(result.get("found_email") or "").strip():
        rung = str(result.get("found_rung") or "").strip().lower()
        first = rung.split(" ")[0] if rung else ""
        if first in ("as-is", "enriched", "fallback"):
            return first
        src = str(result.get("email_source") or "").strip().lower()
        return "as-is" if src == "endole" else "enriched"
    return "error"
