"""
find_email.py — step 2 of the stack for sources the app may not write to (files, demo).

The live-sheet run stays in webapp/server.py, untouched apart from writing `email_status`.
This is the same chain on a file: organize -> the recipe path of pipeline.process_firm ->
lead_record.email_status_for -> the store. Nothing here re-implements a finding rule.

Find email is step 1 (2026-11-07): it runs on EVERY lead, before any website is read, so it
never looks at Website research. A lead with a website goes through the recipe as built
(as-is, then patterns + verification, then the finder by domain). A lead with no website is
not skipped: the recipe's `icypeas_company` method searches the finder by company name.
"""
from __future__ import annotations

from . import lead_record
from . import organize
from . import pipeline
from . import recipe as recipe_mod


def run(rows: list[dict], fm, recipe, store, source: str, verify, find, *,
        limit: int = 0, emit=None, budget: float = 0, spent=None) -> dict:
    """`rows` must already carry the stored step columns (store.overlay).

    `budget` (the campaign's "Most it may spend per run", $) with `spent()` (what the run has
    cost so far): no new lead is started once the run has spent its budget."""
    outer_emit = emit or (lambda *a, **k: None)
    r = recipe if isinstance(recipe, recipe_mod.Recipe) else recipe_mod.Recipe(recipe)
    org = organize.organize(rows, fm=fm, keep_raw=True)
    firms = org["firms"]
    if limit:
        firms = firms[:limit]
    cfg = {"recipe": r.to_dict(), "use_icebreaker": False, "block_security_gateways": False}
    seen: set[str] = set()
    tally = {"processed": 0, "already_done": org["skipped"].get("already_processed", 0),
             "found": 0, "not_found": 0, "no_website": 0, "checks": 0, "finder_calls": 0,
             "stopped_at_budget": False}
    results = []

    for firm in firms:
        if budget and spent is not None and spent() >= budget:
            tally["stopped_at_budget"] = True
            break
        key = str(firm.get("row_key") or "")
        steps: list[dict] = []

        def emit_one(company, stage, kind, detail="", email=""):
            steps.append({"stage": stage, "kind": kind, "detail": detail})
            outer_emit(company, stage, kind, detail, email)

        calls = {"finder": 0}

        def finder(view):
            calls["finder"] += 1
            return find(view)

        res = pipeline.process_firm(firm, cfg, verify, emit_one, fm=fm, find_icypeas=finder,
                                    seen_person=seen.__contains__, remember_person=seen.add)
        value = lead_record.email_status_for(res)
        store.write_status("find_email", source, key, {"email_status": value})
        found = str(res.get("found_email") or "") if value in ("as-is", "enriched", "fallback",
                                                                "check_by_hand") else ""
        store.save_email_result(source, key, {
            "company": res.get("company", ""), "email": found,
            "contact": res.get("contact_name", ""), "rung": res.get("found_rung", ""),
            "method": res.get("found_by", ""), "verification": res.get("verification", ""),
            "checks": res.get("verifications_used", 0), "finder_calls": calls["finder"],
            "steps": steps[-12:]})
        tally["processed"] += 1
        tally["checks"] += int(res.get("verifications_used") or 0)
        tally["finder_calls"] += calls["finder"]
        if found:
            tally["found"] += 1
        elif value == "no_website":
            tally["no_website"] += 1
        else:
            tally["not_found"] += 1
        results.append({"row_key": key, "company": res.get("company", ""),
                        "email_status": value, "email": found, "rung": res.get("found_rung", "")})
    return {**tally, "results": results}
