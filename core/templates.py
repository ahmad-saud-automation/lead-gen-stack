"""
templates.py — step 4: cold email templates per campaign, and the request queue to Claude.

A template is `live` (used for sending), `draft` (waiting for approval) or `rejected`. Leads
are split evenly between the live templates. Every template is scored by core/copy_score.py;
one with an unapproved figure is blocked and can never go live.

Requests ("New template", "Improve a template", "Subject lines", "Add facts to a template")
are queued here. Claude Code works the queue with the rulebook and the approved facts and
returns each result as a draft. A draft that scores 90 or more with no blocked figure is
approved automatically (his default, as in the approved sample); anything else waits for a
person. In the demo a stand-in writer answers at once with a fixed draft per request type,
so the demo costs nothing and gives the same result every time.

Templates live in the app database, never in a sheet. Writes no pipeline column.
"""
from __future__ import annotations

import json
import re
import string
from pathlib import Path

from . import copy_score

KINDS = {"new": "New template", "improve": "Improve a template", "subjects": "Subject lines",
         "facts": "Add facts to a template"}
VARS = ("first_name", "company", "ice_breaker")
REQ_LABEL = {"queued": "Queued", "draft_ready": "Draft ready", "approved": "Approved", "rejected": "Rejected"}


class TemplateError(ValueError):
    """A template action that cannot be done, in plain words."""


def load_demo(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scored(t: dict, approved) -> dict:
    res = copy_score.score(t.get("subject", ""), t.get("body", ""), approved)
    unknown = sorted(set(re.findall(r"\{\{\s*([a-z_]+)\s*\}\}", f"{t.get('subject', '')} {t.get('body', '')}")) - set(VARS))
    if unknown:
        res = {**res, "blocked": True, "unknown_fields": unknown}
    return res


def ensure_seeded(store, source: str, demo: dict) -> None:
    """The demo's starting templates and request history, once per reset (even when two
    requests ask at the same moment: only the one that claims the seed writes)."""
    if store.templates(source) or not store.claim_seed(source, "templates"):
        return
    ok = demo.get("approved_figures") or []
    for t in demo.get("templates") or []:
        res = scored(t, ok)
        rid = None
        if t.get("request"):
            rid = store.add_request(source, "improve", t["request"], "draft_ready")
        tid = store.add_template(source, {**t, "score": res["score"], "result": res,
                                          "approved_by": "you" if t.get("state") == "live" else ""})
        if rid:
            store.update_request(source, rid, template_id=tid)


def _next_name(existing: list[dict], draft: bool) -> str:
    used = {re.sub(r"^(Template|Draft)\s+", "", t.get("name", "")) for t in existing}
    for ch in string.ascii_uppercase:
        if ch not in used:
            return f"{'Draft' if draft else 'Template'} {ch}"
    return f"Draft {len(existing) + 1}"


def live(store, source: str) -> list[dict]:
    return [t for t in store.templates(source) if t["state"] == "live"]


def request(store, source: str, kind: str, instructions: str, approved, writer=None, *,
            auto_approve: bool = True) -> dict:
    """Queue a request. With a writer (the demo stand-in) the draft comes back at once."""
    if kind not in KINDS:
        raise TemplateError(f"Choose a request type: {', '.join(KINDS.values())}.")
    text = re.sub(r"\s+", " ", str(instructions or "")).strip()
    if len(text) < 5:
        raise TemplateError("Write a short instruction, for example “Shorter, lead with month-end”.")
    rid = store.add_request(source, kind, text[:500])
    if writer is None:
        return {"request": rid, "state": "queued"}
    draft = writer(kind, text)
    return {"request": rid, **attach_draft(store, source, rid, draft, approved, auto_approve=auto_approve)}


def attach_draft(store, source: str, rid: int, draft: dict, approved, *, auto_approve: bool = True) -> dict:
    """A draft returned for request `rid`: scored, and approved automatically when it
    qualifies AND the Schedules page's "Auto-approve at score 90 or above" is on."""
    res = scored(draft, approved)
    auto = bool(auto_approve) and copy_score.auto_approves(res)
    name = _next_name(store.templates(source), draft=not auto)
    req = next((r for r in store.requests(source) if r["id"] == rid), {})
    tid = store.add_template(source, {"name": name, "subject": draft.get("subject", ""), "body": draft.get("body", ""),
                                      "state": "live" if auto else "draft", "score": res["score"], "result": res,
                                      "request": req.get("instructions", ""), "approved_by": "auto" if auto else ""})
    store.update_request(source, rid, state="approved" if auto else "draft_ready", template_id=tid)
    return {"state": "approved" if auto else "draft_ready", "template": tid, "score": res["score"],
            "auto_approved": auto, "blocked": res["blocked"]}


def _get(store, source: str, tid: int) -> dict:
    t = next((x for x in store.templates(source) if x["id"] == int(tid)), None)
    if t is None:
        raise TemplateError("That template no longer exists.")
    return t


def _req_of(store, source: str, tid: int):
    return next((r for r in store.requests(source) if r.get("template_id") == int(tid)), None)


def approve(store, source: str, tid: int) -> dict:
    t = _get(store, source, tid)
    if t["state"] != "draft":
        raise TemplateError("Only a draft can be approved.")
    if t["result"].get("blocked"):
        bad = ", ".join(t["result"].get("unapproved") or t["result"].get("unknown_fields") or [])
        raise TemplateError(f"This draft is blocked and cannot be approved: {bad} has no recorded source. Edit it first.")
    others = store.templates(source)
    store.update_template(source, t["id"], state="live", approved_by="you",
                          name=_next_name([x for x in others if x["id"] != t["id"]], draft=False))
    r = _req_of(store, source, t["id"])
    if r:
        store.update_request(source, r["id"], state="approved")
    return {"ok": True}


def reject(store, source: str, tid: int) -> dict:
    t = _get(store, source, tid)
    if t["state"] != "draft":
        raise TemplateError("Only a draft can be rejected.")
    store.update_template(source, t["id"], state="rejected")
    r = _req_of(store, source, t["id"])
    if r:
        store.update_request(source, r["id"], state="rejected")
    return {"ok": True}


def edit(store, source: str, tid: int, subject: str, body: str, approved) -> dict:
    t = _get(store, source, tid)
    if t["state"] != "draft":
        raise TemplateError("Only a draft can be edited. Live templates stay as approved.")
    if not str(subject or "").strip() or not str(body or "").strip():
        raise TemplateError("A template needs a subject and a body.")
    res = scored({"subject": subject, "body": body}, approved)
    store.update_template(source, t["id"], subject=subject.strip(), body=body.strip(), score=res["score"], result=res)
    return {"ok": True, "score": res["score"], "blocked": res["blocked"]}


def render(t: dict, values: dict) -> dict:
    def fill(text: str) -> str:
        return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", lambda m: str(values.get(m.group(1), "")), text or "")
    return {"subject": fill(t.get("subject", "")), "body": fill(t.get("body", ""))}
