"""
health.py — the monitoring agent (build session 3).

It works in two places:

  1. while a step runs: every write a step makes goes through `GuardedStore`. A known
     error is fixed on the spot (a write limit: wait and retry); any other error stops the
     run and is escalated.
  2. on its own schedule (every 5 minutes, and at the end of each chain): `Agent.check`
     sweeps for known problems left behind (a run cut off by a restart, a result that was
     found but not saved, a website that did not answer).

THE RULE: the agent applies a fix only when the problem's kind is in ALLOWED. Every other
kind — spend, credits, sheet data, templates, anything new — is written down as
"Escalated" and waits for a person. There is no code path that fixes an escalated kind.

Every incident is stored (core/store.py `incidents`), so the Health page, Home and the
daily summary all read the same list.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from . import lead_record

# ── the errors a step (or a stand-in service) can raise ──────────────


class StackError(Exception):
    kind = "unknown"


class WriteLimit(StackError):
    """The place results are written to refused a write for now (Google's 429)."""
    kind = "write_limit"


class CreditsUsedUp(StackError):
    kind = "credits"


class SpendLimit(StackError):
    kind = "spend"


class SheetChange(StackError):
    """A fix would need to change data already in a sheet."""
    kind = "sheet_change"


class TemplateChange(StackError):
    kind = "template_change"


# ── the two lists (shown on the Health page word for word) ───────────

ALLOWED = {
    "write_limit": "Sheet write limit: wait and retry",
    "interrupted_run": "Interrupted run: close and resume",
    "unsaved_result": "Unsaved result: save again at no cost",
    "site_unreachable": "Unreachable website: retry the next day",
}
ALWAYS_ESCALATED = {
    "spend": "Extra spend or credit purchases",
    "credits": "Extra spend or credit purchases",
    "sheet_change": "Changes to existing sheet data",
    "template_change": "Template changes",
    "unknown": "Any issue not on the automatic list",
}
ESCALATED_LIST = ["Extra spend or credit purchases", "Changes to existing sheet data", "Template changes",
                  "Any issue not on the automatic list"]

ISSUE_WORDS = {
    "write_limit": "Sheet write limit reached",
    "credits": "Email finder credits used up",
    "spend": "Spend limit reached",
    "sheet_change": "A fix would change existing sheet data",
    "template_change": "Template change needed",
    "unknown": "Unexpected error",
}

STAGE_WORDS = {"research": "Website research", "find_email": "Find email", "icebreakers": "Ice breakers",
               "sending": "Sending", "replies": "Replies"}

RETRY_WAITS = (2, 4, 8)        # seconds between write retries
SITE_RETRY_TRIES = 3             # after this many next-day tries, a website is escalated

RESOLVED, ESCALATED, OPEN = "resolved", "escalated", "open"


def is_allowed(kind: str) -> bool:
    return kind in ALLOWED


def kind_of(exc: BaseException) -> str:
    return getattr(exc, "kind", "unknown") if isinstance(exc, StackError) else "unknown"


class Agent:
    def __init__(self, store, source: str, *, sleep=time.sleep, waits=RETRY_WAITS, now=datetime.now,
                 run_id: str = "", log=None):
        self.store = store                  # the real store, never a stand-in
        self.source = source
        self.sleep = sleep
        self.waits = tuple(waits)
        self.now = now
        self.run_id = run_id
        self.log = log or (lambda text, tone="": None)

    def _incident(self, step, kind, issue, action, result, row_key="") -> int:
        return self.store.add_incident(self.source, {
            "at": self.now().strftime("%Y-%m-%d %H:%M:%S"), "step": step, "kind": kind, "issue": issue,
            "action": action, "result": result, "run_id": self.run_id, "row_key": row_key})

    # ── while a step runs ────────────────────────────────────────

    def guard(self, inner, step: str) -> "GuardedStore":
        return GuardedStore(inner, self, step)

    def write_with_retry(self, inner, step, stage, source, key, values):
        values = lead_record.stage_update(stage, values)     # a step's own column only, before anything else
        try:
            return inner.write_status(stage, source, key, values)
        except WriteLimit:
            pass
        self.log(f"{step}: sheet write limit reached, result not saved yet", "bad")
        waited = 0
        for w in self.waits:
            self.log(f"Health agent: known issue. Waiting {w} seconds, then retrying.")
            self.sleep(w)
            waited += w
            try:
                out = inner.write_status(stage, source, key, values)
            except WriteLimit:
                continue
            self._incident(step, "write_limit", ISSUE_WORDS["write_limit"],
                           f"Waited {waited} seconds and retried. Result saved.", RESOLVED, key)
            self.log("Health agent: result saved. Resolved automatically.", "good")
            return out
        iid = self._incident(step, "write_limit", ISSUE_WORDS["write_limit"],
                             f"Retried {len(self.waits)} times. The result is kept and will be saved again "
                             "at the next check, at no cost.", OPEN, key)
        self.store.add_pending(source, key, stage, values, iid)
        self.log("Health agent: result kept. It will be saved at the next check.")
        return values

    def on_error(self, step: str, exc: BaseException, row_key: str = "") -> dict:
        """A step stopped with an error. Nothing on the allowed list stops a step, so this
        always escalates: the agent writes it down and the chain waits for a person."""
        kind = kind_of(exc)
        detail = str(exc).strip()
        issue = ISSUE_WORDS.get(kind, ISSUE_WORDS["unknown"]) + (f": {detail[:160]}" if detail and kind == "unknown" else "")
        action = (f"Paused {step}. " + (detail[:200] if detail and kind != "unknown" else "Waiting for you.")).strip()
        iid = self._incident(step, kind, issue, action, ESCALATED, row_key)
        self.log(f"Health agent: {issue}. Not on the automatic list, so it waits for you.", "bad")
        return {"id": iid, "kind": kind, "issue": issue, "action": action, "result": ESCALATED}

    # ── the regular check ────────────────────────────────────────

    def check(self, *, alive=frozenset(), resume=None, names=None, today: date | None = None,
              blocked_keys=(), live_templates: int | None = None, waiting_leads: int = 0) -> list[dict]:
        """Sweep for known problems. Returns the incidents it wrote this time.

        alive          ids of chain runs this process is running right now
        resume(run)    starts a new run from the old run's next unfinished step; returns its id
        names          row_key -> company, for plain words
        blocked_keys   leads whose website refused us
        live_templates how many live email templates there are (None = do not check)
        waiting_leads  leads with an ice breaker that are waiting for a template
        """
        today = today or self.now().date()
        names = names or {}
        before = {i["id"] for i in self.store.incidents(self.source)}

        # 1. a run cut off by a restart
        for r in self.store.runs(self.source, ("running",)):
            if r["id"] in alive:
                continue
            nxt = int(r.get("step") or 0)                 # the step it was on: not finished
            self.store.update_run(r["id"], state="interrupted", finished=self.now().strftime("%Y-%m-%d %H:%M:%S"),
                                  message="Cut off by a restart.")
            new_id = resume(r) if resume else ""
            action = (f"Closed the old run and resumed from step {nxt + 1}. No leads lost." if new_id
                      else "Closed the old run.")
            self._incident("Pipeline", "interrupted_run", "Run interrupted by restart", action, RESOLVED)

        # 2. a result found but not saved
        for p in self.store.pending(self.source):
            try:
                self.store.write_status(p["stage"], self.source, p["row_key"], p["vals"])
            except Exception:  # noqa: BLE001 - try again at the next check
                continue
            self.store.drop_pending(self.source, p["row_key"], p["stage"])
            if p.get("incident"):
                old = next((i for i in self.store.incidents(self.source) if i["id"] == p["incident"]), None)
                self.store.update_incident(self.source, p["incident"], result=RESOLVED,
                                           action=((old or {}).get("action", "") + " Saved again at the next check, no cost.").strip())
            else:
                self._incident(STAGE_WORDS.get(p["stage"], p["stage"]), "unsaved_result", "Result found but not saved",
                               "Saved it again, no cost.", RESOLVED, p["row_key"])

        # 3. a website that did not answer: try again tomorrow, then hand it over
        retries = self.store.retries(self.source, "research")
        for key in blocked_keys:
            key = str(key)
            r = retries.get(key)
            company = names.get(key, key)
            if r is None:
                self.store.set_retry(self.source, key, "research", (today + timedelta(days=1)).isoformat(), 0)
                self._incident("Website research", "site_unreachable", f"Website refused the visit: {company}",
                               "Will try again tomorrow.", RESOLVED, key)
            elif r["tries"] >= SITE_RETRY_TRIES:
                self.store.set_retry(self.source, key, "research", "9999-12-31", -1)   # escalated once
                self._incident("Website research", "unknown", f"Website still refuses after {SITE_RETRY_TRIES} tries: {company}",
                               "Not on the automatic list. Check the website by hand.", ESCALATED, key)

        # 4. no live template while leads wait for one: templates are always a person's call
        if live_templates == 0 and waiting_leads:
            issue = "No live email template"
            if not any(i["kind"] == "template_change" and i["issue"] == issue and i["result"] == ESCALATED
                       for i in self.store.incidents(self.source)):
                self._incident("Email template", "template_change", issue,
                               f"{waiting_leads} leads are waiting. Template changes need you.", ESCALATED)

        self.store.set_setting(f"health_last_check:{self.source}", self.now().strftime("%Y-%m-%d %H:%M:%S"))
        return [i for i in self.store.incidents(self.source) if i["id"] not in before]

    def due_site_retries(self, today: date | None = None) -> list[str]:
        """Leads whose next-day retry has come. Each is let back into Website research once."""
        today = today or self.now().date()
        out = []
        for key, r in self.store.retries(self.source, "research").items():
            if 0 <= r["tries"] < SITE_RETRY_TRIES and r["after"] <= today.isoformat():
                self.store.forget_research(self.source, key)
                self.store.set_retry(self.source, key, "research", (today + timedelta(days=1)).isoformat(),
                                     r["tries"] + 1)
                out.append(key)
        return out


class GuardedStore:
    """The store a step is given during a chain run. Reads pass straight through; each
    status write goes through the agent, which retries a write limit."""

    def __init__(self, inner, agent: Agent, step: str):
        self._inner = inner
        self._agent = agent
        self._step = step

    def write_status(self, stage, source, key, values):
        return self._agent.write_with_retry(self._inner, self._step, stage, source, key, values)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ── what the Health page, Home and the summary count ─────────────────

def day_incidents(incidents: list[dict], day: date) -> list[dict]:
    d = day.isoformat()
    return [i for i in incidents if str(i.get("at", "")).startswith(d)]


def tiles(incidents: list[dict], day: date) -> dict:
    today = day_incidents(incidents, day)
    return {"issues": len(today), "resolved": sum(1 for i in today if i["result"] == RESOLVED),
            "waiting": sum(1 for i in incidents if i["result"] in (ESCALATED, OPEN))}


def summary(day: date, incidents: list[dict], counts: dict, decisions: list[dict],
            sent_word: str = "sent (test mode)") -> dict:
    """The daily summary, as lines of plain text. Written into the app; never emailed.
    `sent_word`: how the sent count is described ("pushed to a Draft campaign" for a pipeline campaign)."""
    t = tiles(incidents, day)
    lines = [f"Issues: {t['issues']} · Resolved automatically: {t['resolved']} · Waiting for you: {t['waiting']}"]
    for i in incidents:
        if i["result"] in (ESCALATED, OPEN):
            lines.append(f"Action needed: {i['issue']}. {i['action']}")
    if decisions:
        lines.append("Needs your decision: " + " · ".join(d["text"] for d in decisions))
    lines.append(f"Today: {counts.get('leads', 0)} leads · {counts.get('emails', 0)} emails found · "
                 f"{counts.get('sent', 0)} {sent_word} · {counts.get('replies', 0)} replies "
                 f"({counts.get('interested', 0)} interested)")
    return {"title": f"Daily summary · {day:%A} {day.day} {day:%B}", "lines": lines, **t}
