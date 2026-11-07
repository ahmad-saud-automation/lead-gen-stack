"""
eval_recipe.py — offline test for the Finding Recipe (no network, no keys, no cost).
    python eval_recipe.py   /   pytest eval_recipe.py

Two jobs:
  1. the recipe itself — validation, and the free plan for one row
  2. the recipe path through pipeline.py — the ladder, the stop rules, the locks

⛔ The most important check in here is `check_no_recipe_is_untouched`: it runs the WHOLE
of eval_pipeline against the rewritten pipeline, because "a campaign with no recipe keeps
today's exact order" is the promise this change was allowed to be built on.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from core import fieldmap as fieldmap_mod
from core import pipeline
from core import recipe as recipe_mod

FM = fieldmap_mod.FieldMap({})          # a CH tab needs no map: recipes name real headers

CFG = {"block_security_gateways": True, "use_icebreaker": False}


# ── the row and the firm, shaped like a real CH trigger tab ──────────

def _row(**over) -> dict:
    base = {"lead_id": "ch-1", "Company Name": "Smith & Co", "Website": "smithco.co.uk",
            "Endole director": "Ian Smith", "Apollo director": "", "Contact 2": "Jane Doe",
            "Director Who Left": "Brian Old", "Email Person": "",
            "Email": "owner@smithco.co.uk", "Seniority": "Director",
            "Next Step": "New loan", "Status": "",
            # Find email's own column (core/lead_record.py) — a CH tab once he adds it
            "email_status": ""}
    base.update(over)
    return base


def _firm(row=None, **over) -> dict:
    row = row if row is not None else _row()
    base = {"Company Name": row.get("Company Name", ""), "company_key": row.get("lead_id", ""),
            "row_key": row.get("lead_id", ""), "lead_domain": row.get("Website", ""),
            "lead_website": row.get("Website", ""),
            "is_no_website_path": not row.get("Website"),
            "lead_endole_email": "", "endole_generic": False,
            "email_security_gateway_provider": "", "_raw": row}
    base.update(over)
    return base


# ── recipe #1, exactly as docs/RECIPE-BUILDER.md §4 writes it ────────

def _ways_with_website():
    return [{"method": "guess_patterns", "patterns": "careful", "verify": "must_pass"},
            {"method": "icypeas_domain", "verify": "must_pass"}]


def recipe1(**over) -> dict:
    r = {
        "id": "director-waterfall", "name": "Director waterfall",
        "note": "1st director, 2nd director, then the address on the row",
        "people": [
            {"label": "1st director", "name_from": ["Endole director", "Apollo director"],
             "never_if_same_as": ["Director Who Left", "Email Person"],
             "how": _ways_with_website()},
            {"label": "2nd director", "name_from": "Contact 2",
             "never_if_same_as": ["Director Who Left", "Email Person"],
             "how": _ways_with_website()},
            {"label": "the email already on the row", "address_from": "Email",
             "only_if": {"all": [{"field": "Seniority", "op": "equals", "value": "Director"}]},
             "how": [{"method": "use_as_is", "verify": "must_pass"}]},
        ],
        "stop": {"stop_when": "first_pass", "skip_row_if": {}, "last_resort": True},
        "write": {"email_to": "Found Email", "person_to": "Found For",
                  "method_to": "Found By", "status_to": "email_status", "write_when": "always"},
        "limits": {"per_run": 30, "search_same_person_once": True, "push_to": ""},
    }
    r.update(over)
    return r


# ── stubs ────────────────────────────────────────────────────────────

def vstub(*good):
    """A verifier that accepts only the addresses named. Records what it was asked."""
    asked: list[str] = []
    ok = set(good)

    def verify(email):
        asked.append(email)
        passed = email in ok
        return {"accepted": passed, "verification": "good" if passed else "bad",
                "tier": "pass" if passed else "bad"}
    verify.asked = asked
    return verify


def istub(email, certainty="probable"):
    """An Icypeas that always answers with this address. Records the firm view it got."""
    seen: list[dict] = []

    def find(firm):
        seen.append({"first": firm.get("lead_firstname", ""), "last": firm.get("lead_lastname", ""),
                     "domain": firm.get("lead_domain", ""), "company": firm.get("Company Name", "")})
        return {"email": email, "certainty": certainty}
    find.seen = seen
    return find


def inothing():
    return lambda firm: {"email": "", "error": "not found"}


def _emit_collector():
    events = []
    return events, (lambda company, stage, status, detail, email="":
                    events.append({"company": company, "stage": stage, "status": status,
                                   "detail": detail, "email": email}))


def _run(recipe, row=None, firm=None, *, verify=None, icypeas=None, cfg=None):
    """One firm through the recipe path. Returns (result, events, verifier)."""
    row = row if row is not None else _row()
    firm = firm if firm is not None else _firm(row)
    verify = verify or vstub()
    events, emit = _emit_collector()
    r = pipeline.process_firm(firm, {**CFG, **(cfg or {}), "recipe": recipe},
                              verify, emit, fm=FM,
                              find_icypeas=icypeas or inothing())
    return r, events, verify


# ═══════════════════ 1. the recipe: validation ═══════════════════════

def check_valid_recipe_has_no_complaints():
    issues = recipe_mod.validate(recipe1())
    assert issues == [], issues


def check_validate_catches_every_problem_at_once():
    bad = {
        "name": "",
        "people": [
            {"label": "nobody", "how": []},                                   # no column, no way
            {"label": "odd", "name_from": "Endole director",
             "how": [{"method": "ring_them_up", "verify": "maybe"},           # unknown way + check
                     {"method": "guess_patterns", "patterns": "sloppy", "verify": "must_pass"},
                     {"method": "use_as_is", "verify": "must_pass"}],         # no address column
             "only_if": {"all": [{"field": "Seniority", "op": "sort_of", "value": "x"}]}},
        ],
        "stop": {"stop_when": "whenever"},
        "write": {"email_to": "Found Email", "person_to": "Found Email",      # same column twice
                  "write_when": "sometimes"},
        "limits": {"catch_all": True},                                        # locked out
    }
    issues = recipe_mod.validate(bad)
    joined = " | ".join(issues)
    for want in ["needs a name", "person 1 (nobody): pick the column", "at least one way",
                 "unknown way 'ring_them_up'", "unknown check 'maybe'", "'sloppy'",
                 "needs an address column", "unknown operator 'sort_of'",
                 "'whenever' is not a stop rule", "two things at once",
                 "'sometimes' is not a write rule", "'catch_all' cannot be set"]:
        assert want in joined, f"missing {want!r} in:\n  " + "\n  ".join(issues)


def check_empty_recipe_needs_a_person():
    issues = recipe_mod.validate({"name": "Empty", "people": []})
    assert any("at least one person" in i for i in issues), issues


def check_missing_write_column_is_blocking():
    headers = list(_row().keys()) + ["Found For", "Found By"]       # no "Found Email"
    out = recipe_mod.check_against_sheet(recipe1(), headers)
    assert out["ok"] is False, out
    assert out["missing_write"] == ["Found Email"], out
    assert "silently discarded" in out["blocking"][0], out


def check_missing_read_column_is_only_a_warning():
    headers = [h for h in _row().keys() if h != "Contact 2"] + \
              ["Found Email", "Found For", "Found By"]
    out = recipe_mod.check_against_sheet(recipe1(), headers)
    assert out["ok"] is True, out
    assert out["missing_read"] == ["Contact 2"], out
    assert out["warnings"], out


def check_write_targets_are_only_four():
    r = recipe_mod.Recipe(recipe1())
    # since 2026-11-06 the status goes to email_status, never his Status column
    assert r.write_columns() == ["Found Email", "Found For", "Found By", "email_status"], r.write_columns()
    bare = recipe_mod.Recipe({"name": "x", "people": []})          # defaults fill in
    assert bare.write_columns() == ["Found Email", "Found For", "Found By", "email_status"]
    assert "Status" not in bare.write_columns()
    assert "Contact Name" not in bare.write_columns()
    assert "Email Source" not in bare.write_columns()


# ═══════════════════ 2. the free plan for one row ════════════════════

def check_plan_lists_his_three_people_in_order():
    plan = recipe_mod.plan_for_row(recipe1(), _row(), _firm(), FM)
    assert [p["label"] for p in plan["people"]] == \
        ["1st director", "2nd director", "the email already on the row"], plan["people"]
    assert plan["people"][0]["name"] == "Ian Smith"
    assert plan["people"][0]["name_column"] == "Endole director"
    assert plan["people"][2]["address"] == "owner@smithco.co.uk"


def check_name_falls_through_to_the_next_column():
    row = _row(**{"Endole director": "", "Apollo director": "Ada Lovelace"})
    plan = recipe_mod.plan_for_row(recipe1(), row, _firm(row), FM)
    p1 = plan["people"][0]
    assert p1["name"] == "Ada Lovelace" and p1["name_column"] == "Apollo director", p1


def check_the_leaver_is_dropped_whatever_the_name_order():
    row = _row(**{"Endole director": "Ian Smith", "Director Who Left": "Smith, Ian"})
    plan = recipe_mod.plan_for_row(recipe1(), row, _firm(row), FM)
    assert [p["label"] for p in plan["people"]] == ["2nd director", "the email already on the row"]
    assert "same person as 'Director Who Left'" in plan["dropped"][0]["why"], plan["dropped"]


def check_only_if_drops_the_row_address():
    row = _row(Seniority="Bookkeeper")
    plan = recipe_mod.plan_for_row(recipe1(), row, _firm(row), FM)
    assert [p["label"] for p in plan["people"]] == ["1st director", "2nd director"]
    assert any("'only if' not met" in d["why"] for d in plan["dropped"]), plan["dropped"]


def check_skip_row_if_skips_the_whole_row():
    rec = recipe1(stop={"stop_when": "first_pass", "last_resort": False,
                        "skip_row_if": {"all": [{"field": "Next Step", "op": "starts_with",
                                                 "value": "Stop"}]}})
    plan = recipe_mod.plan_for_row(rec, _row(**{"Next Step": "Stop — already a client"}), _firm(), FM)
    assert plan["skip"] is True and plan["people"] == [], plan


def check_no_website_greys_out_guessing_and_says_why():
    row = _row(Website="")
    rec = recipe1(people=[{"label": "1st director", "name_from": "Endole director",
                           "how": [{"method": "guess_patterns", "verify": "must_pass"},
                                   {"method": "icypeas_company", "verify": "must_pass"}]}])
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    ways = plan["people"][0]["ways"]
    assert ways[0]["ok"] is False and "no website" in ways[0]["why"], ways[0]
    assert ways[1]["ok"] is True, ways[1]


def check_a_person_named_twice_is_tried_once():
    rec = recipe1(people=[
        {"label": "1st director", "name_from": "Endole director", "how": _ways_with_website()},
        {"label": "again", "name_from": "Endole director", "how": _ways_with_website()}])
    plan = recipe_mod.plan_for_row(rec, _row(), _firm(), FM)
    assert [p["label"] for p in plan["people"]] == ["1st director"], plan["people"]
    assert "already tried higher up" in plan["dropped"][0]["why"], plan["dropped"]


def check_a_rung_that_cannot_run_does_not_reserve_its_person():
    """⛔ The bug that cost every row on C1 (2026-10-13).

    The Organized recipe names the same contact twice: take the address already in their
    column, else guess it. The first rung has a NAME but no address, so it is dropped —
    and while the reservation happened before that test, the guess rung was then refused
    as "already tried higher up" and the row ended skipped_no_person."""
    rec = recipe1(people=[
        {"label": "as-is contact 1", "name_from": "Endole director",
         "address_from": "Nothing Here",                       # the column is empty
         "how": [{"method": "use_as_is", "verify": "no_check"}]},
        {"label": "enriched contact 1", "name_from": "Endole director",
         "how": _ways_with_website()}])
    plan = recipe_mod.plan_for_row(rec, _row(), _firm(), FM)
    assert [p["label"] for p in plan["people"]] == ["enriched contact 1"], plan["people"]
    assert not any("already tried higher up" in d["why"] for d in plan["dropped"]), plan["dropped"]


def check_the_full_name_pattern_set_is_offered_to_a_recipe():
    rec = recipe1(people=[{"label": "1st director", "name_from": "Endole director",
                           "how": [{"method": "guess_patterns", "patterns": "full_name",
                                    "verify": "must_pass"}]}])
    assert recipe_mod.validate(rec) == [], recipe_mod.validate(rec)
    plan = recipe_mod.plan_for_row(rec, _row(), _firm(), FM)
    assert plan["people"][0]["ways"][0]["pattern_mode"] == "fullname", plan["people"][0]["ways"]
    # three guesses, so it costs exactly what 'careful' costs
    assert recipe_mod.estimate_row(plan)["max_checks"] == 3, recipe_mod.estimate_row(plan)


def check_the_two_extra_write_columns_are_opt_in():
    plain = recipe_mod.Recipe(recipe1())
    assert "index_to" not in plain.write_targets(), plain.write_targets()
    assert len(plain.write_columns()) == 4, plain.write_columns()
    asked = recipe_mod.Recipe(recipe1(
        write={"email_to": "final_email", "person_to": "final_contact_name",
               "method_to": "final_email_source", "status_to": "enrich_status",
               "index_to": "final_contact_index",
               "first_name_to": "final_first_name", "words": "source"}))
    assert recipe_mod.validate(asked) == [], recipe_mod.validate(asked)
    assert asked.write_columns() == ["final_email", "final_contact_name", "final_email_source",
                                     "enrich_status", "final_contact_index",
                                     "final_first_name"], asked.write_columns()
    assert asked.write_words == "source"
    bad = recipe_mod.Recipe(recipe1(write={"words": "whatever"}))
    assert any("not a way to word the result" in w for w in recipe_mod.validate(bad)), \
        recipe_mod.validate(bad)


def check_estimate_is_a_ceiling_not_a_bill():
    plan = recipe_mod.plan_for_row(recipe1(), _row(), _firm(), FM)
    est = recipe_mod.estimate_row(plan)
    # 2 directors x (3 guesses + 1 Icypeas + its check) + 1 row address check
    assert est["max_checks"] == 2 * (3 + 1) + 1, est
    assert est["max_icypeas_credits"] == 2, est
    assert est["people"] == 3, est


def check_person_cache_key_ignores_name_order():
    a = recipe_mod.person_cache_key("Smith & Co", "Ian Smith")
    b = recipe_mod.person_cache_key("smith and co", "Smith, Ian")
    assert a == b, (a, b)
    assert a != recipe_mod.person_cache_key("Smith & Co", "Jane Doe")


# ═══════════════════ 3. files ════════════════════════════════════════

def check_save_load_round_trip_and_campaign_lookup():
    d = Path(tempfile.mkdtemp(prefix="recipes-"))
    try:
        recipe_mod.save(d, recipe1(), today="2026-10-07")
        recipe_mod.save(d, {"id": "other", "name": "Other", "people": []})
        (d / "broken.json").write_text("{not json", encoding="utf-8")   # must not stop the rest

        one = recipe_mod.load(d / "director-waterfall.json")
        assert one.name == "Director waterfall" and one.updated == "2026-10-07"
        assert len(one.people) == 3 and one.people[0].name_from == \
            ["Endole director", "Apollo director"]

        all_of_them = recipe_mod.load_dir(d)
        assert sorted(all_of_them) == ["director-waterfall", "other"], sorted(all_of_them)

        class C:
            raw = {"id": "northwind-ch", "recipe": "director-waterfall"}
        assert recipe_mod.for_campaign(C(), all_of_them).id == "director-waterfall"

        class NoRecipe:
            raw = {"id": "old-lane"}
        assert recipe_mod.for_campaign(NoRecipe(), all_of_them) is None
        assert recipe_mod.load(d / "nope.json") is None
        assert recipe_mod.load_dir(d / "nope") == {}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def check_blank_recipe_is_valid_shape():
    b = recipe_mod.blank("Director waterfall")
    assert b["id"] == "director-waterfall"
    assert json.loads(json.dumps(b)) == b            # it is plain JSON, nothing clever
    assert recipe_mod.Recipe(b).write_columns()[0] == "Found Email"


# ═══════════════════ 4. the ladder, through the pipeline ═════════════

def check_second_director_wins_when_the_first_fails():
    v = vstub("jane.doe@smithco.co.uk")
    r, events, _ = _run(recipe1(), verify=v, icypeas=istub("ian.smith@smithco.co.uk"))
    assert r["status"] == "email_found", r["status"]
    assert r["found_email"] == "jane.doe@smithco.co.uk", r["found_email"]
    assert r["found_for"] == "Jane Doe (2nd director)", r["found_for"]
    assert r["email_source"] == "pattern_first.last", r["email_source"]
    assert r["send_ready"] == "yes" and r["accepted"] is True, r
    # 3 guesses + 1 Icypeas answer for Ian, then 2 guesses for Jane
    assert r["verifications_used"] == 6, (r["verifications_used"], v.asked)
    assert r["people_tried"] == ["1st director", "2nd director"], r["people_tried"]


def check_first_pass_stops_and_never_pays_for_the_rest():
    v = vstub("ian.smith@smithco.co.uk")
    r, _events, _ = _run(recipe1(), verify=v)
    assert r["found_email"] == "ian.smith@smithco.co.uk", r
    assert r["found_for"] == "Ian Smith (1st director)", r["found_for"]
    assert r["verifications_used"] == 2, v.asked           # ian@ failed, ian.smith@ passed
    assert r["people_tried"] == ["1st director"], r["people_tried"]
    assert "owner@smithco.co.uk" not in v.asked, "it paid to check the row address anyway"


def check_the_row_address_is_used_when_no_director_is_named():
    row = _row(**{"Endole director": "", "Apollo director": "", "Contact 2": ""})
    v = vstub("owner@smithco.co.uk")
    r, _events, _ = _run(recipe1(), row=row, verify=v)
    assert r["status"] == "email_found" and r["found_email"] == "owner@smithco.co.uk", r
    assert r["email_source"] == "endole", r["email_source"]
    assert r["found_by"] == "the address on the row · good", r["found_by"]
    # that rung has no name column, so the rung's label is all there is to say — and
    # a blank name must NOT be written over his Contact Name column
    assert r["found_for"] == "the email already on the row", r["found_for"]
    assert r["contact_name"] == "" and r["selected_director"] == "", r
    assert r["people_tried"] == ["the email already on the row"], r["people_tried"]
    assert len(r["people_dropped"]) == 2, r["people_dropped"]


def check_a_row_with_nobody_is_skipped_not_failed():
    row = _row(**{"Endole director": "", "Apollo director": "", "Contact 2": "",
                  "Seniority": "Bookkeeper"})
    v = vstub()
    r, _events, _ = _run(recipe1(), row=row, verify=v)
    assert r["status"] == recipe_mod.STATUS_NO_PERSON, r["status"]
    assert r["found_email"] == "" and r["verifications_used"] == 0, r
    assert v.asked == [], v.asked


def check_skip_row_if_spends_nothing():
    rec = recipe1(stop={"stop_when": "first_pass", "last_resort": False,
                        "skip_row_if": {"all": [{"field": "Next Step", "op": "starts_with",
                                                 "value": "Stop"}]}})
    v = vstub("ian.smith@smithco.co.uk")
    r, events, _ = _run(rec, row=_row(**{"Next Step": "Stop — already a client"}), verify=v)
    assert r["status"] == recipe_mod.STATUS_SKIPPED, r["status"]
    assert v.asked == [], v.asked
    assert any(e["stage"] == "organize" and e["status"] == "skip" for e in events)


def check_the_security_guard_still_runs_first():
    v = vstub("ian.smith@smithco.co.uk")
    firm = _firm(email_security_gateway_provider="Mimecast")
    r, events, _ = _run(recipe1(), firm=firm, verify=v)
    assert r["status"] == "hold_security_gateway", r["status"]
    assert r["verifications_used"] == 0 and v.asked == [], v.asked
    assert events[0]["status"] == "held", events


# ═══════════════════ 5. the no-website lane ══════════════════════════

def _company_recipe(**over):
    return recipe1(people=[
        {"label": "1st director", "name_from": "Endole director",
         "never_if_same_as": ["Director Who Left"],
         "how": [{"method": "guess_patterns", "verify": "must_pass"},
                 {"method": "icypeas_company", "verify": "must_pass",
                  "note_if_domain_mismatch": True}]}], **over)


def check_no_website_asks_icypeas_by_company_name():
    row = _row(Website="")
    ic = istub("ian.smith@smithco.co.uk")
    v = vstub("ian.smith@smithco.co.uk")
    r, events, _ = _run(_company_recipe(), row=row, verify=v, icypeas=ic)
    assert r["status"] == "email_found" and r["send_ready"] == "yes", r
    assert r["email_source"] == "icypeas_company", r["email_source"]
    # the finder was handed the company name and NO domain — that is the whole trick
    assert ic.seen == [{"first": "ian", "last": "smith", "domain": "", "company": "Smith & Co"}], ic.seen
    assert any("no website" in e["detail"] for e in events if e["status"] == "skip"), events


def check_a_foreign_domain_is_found_but_marked_for_a_human():
    row = _row(Website="")
    r, _events, _ = _run(_company_recipe(), row=row,
                         verify=vstub("ian.smith@totallyother.com"),
                         icypeas=istub("ian.smith@totallyother.com"))
    assert r["status"] == recipe_mod.STATUS_CHECK_BY_HAND, r["status"]
    assert r["found_email"] == "ian.smith@totallyother.com", r
    assert r["needs_check"] is True, r
    # ⛔ THE LOCK: it passed MillionVerifier, and it still cannot be sent
    assert r["send_ready"] == "no" and r["accepted"] is False, r
    assert "does not look like Smith & Co" in r["found_by"], r["found_by"]


def check_the_firms_own_domain_is_not_nagged_about():
    for dom in ["smithco.co.uk", "smith-co.com", "smithandco.co.uk"]:
        em = f"ian.smith@{dom}"
        r, _e, _v = _run(_company_recipe(), row=_row(Website=""),
                         verify=vstub(em), icypeas=istub(em))
        assert r["status"] == "email_found", (dom, r["status"])
        assert r["send_ready"] == "yes", (dom, r)


def check_the_real_icypeas_test_mode_still_fits_the_recipe_path():
    """Not a stub: the shipped finder, in test mode, driven by a recipe."""
    from core import finders
    row = _row(Website="")
    r, _events, _ = _run(_company_recipe(), row=row,
                         verify=vstub("ian.smith@smithco.co.uk"),
                         icypeas=lambda firm: finders.find_icypeas(firm, test_mode=True))
    assert r["status"] == "email_found", r["status"]
    assert r["found_email"] == "ian.smith@smithco.co.uk", r["found_email"]


# ═══════════════════ 6. the stop rules ═══════════════════════════════

def check_nothing_passed_and_last_resort_off_writes_no_address():
    rec = recipe1(stop={"stop_when": "first_pass", "skip_row_if": {}, "last_resort": False})
    r, _events, _ = _run(rec, verify=vstub(), icypeas=istub("ian.smith@smithco.co.uk"))
    assert r["status"] == "email_not_found", r["status"]
    assert r["found_email"] == "" and r["send_ready"] == "no", r


def check_last_resort_writes_a_real_address_marked_and_unsendable():
    r, events, _ = _run(recipe1(), verify=vstub(), icypeas=istub("ian.smith@smithco.co.uk"))
    assert r["status"] == recipe_mod.STATUS_FAILED_CHECK, r["status"]
    assert r["found_email"] == "ian.smith@smithco.co.uk", r["found_email"]
    # ⛔ THE LOCK: written so he can see it, never sendable
    assert r["send_ready"] == "no" and r["accepted"] is False, r
    assert any("never sent" in e["detail"] for e in events), events


def check_a_failed_guess_is_never_the_last_resort():
    """A guess that failed its check is noise — nobody ever said that mailbox exists."""
    rec = recipe1(people=[{"label": "1st director", "name_from": "Endole director",
                           "how": [{"method": "guess_patterns", "verify": "must_pass"}]}])
    r, _events, _ = _run(rec, verify=vstub())
    assert r["status"] == "email_not_found", r["status"]
    assert r["found_email"] == "", r["found_email"]


def check_write_but_mark_as_failed_keeps_a_guess():
    rec = recipe1(people=[{"label": "1st director", "name_from": "Endole director",
                           "how": [{"method": "guess_patterns", "verify": "write_failed"}]}],
                  stop={"stop_when": "first_pass", "skip_row_if": {}, "last_resort": False})
    r, _events, _ = _run(rec, verify=vstub())
    assert r["status"] == recipe_mod.STATUS_FAILED_CHECK, r["status"]
    assert r["found_email"] == "ian@smithco.co.uk", r["found_email"]
    assert r["send_ready"] == "no", r


def check_no_check_is_accepted_but_still_cannot_be_sent():
    rec = recipe1(people=[{"label": "the row address", "address_from": "Email",
                           "how": [{"method": "use_as_is", "verify": "no_check"}]}])
    v = vstub()
    r, _events, _ = _run(rec, verify=v)
    assert r["status"] == "email_found" and r["found_email"] == "owner@smithco.co.uk", r
    assert v.asked == [], "no_check paid for a check anyway"
    assert r["send_ready"] == "no" and r["accepted"] is False, r


def check_try_everyone_keeps_the_best_not_the_first():
    rec = recipe1(
        people=[
            {"label": "1st director", "name_from": "Endole director",
             "how": [{"method": "icypeas_company", "verify": "must_pass"}]},
            {"label": "2nd director", "name_from": "Contact 2",
             "how": [{"method": "guess_patterns", "verify": "must_pass"}]},
        ],
        stop={"stop_when": "try_all_keep_best", "skip_row_if": {}, "last_resort": False})
    # person 1 gets a verified address at the WRONG-looking firm; person 2 a clean pass
    r, _events, _ = _run(rec, verify=vstub("ian.smith@totallyother.com",
                                           "jane.doe@smithco.co.uk"),
                         icypeas=istub("ian.smith@totallyother.com"))
    assert r["found_email"] == "jane.doe@smithco.co.uk", r["found_email"]
    assert r["status"] == "email_found" and r["send_ready"] == "yes", r
    assert r["found_for"] == "Jane Doe (2nd director)", r["found_for"]
    assert "ian.smith@totallyother.com" in r["alternate_emails"], r["alternate_emails"]
    assert r["people_tried"] == ["1st director", "2nd director"], r["people_tried"]


def check_the_same_person_is_searched_once_across_firms():
    """The 32 firms that sit on two CH tabs must not be searched twice."""
    row_a = _row(lead_id="ch-1")
    row_b = _row(lead_id="ch-2", **{"Contact 2": "", "Email": "", "Seniority": "x"})
    rec = recipe1(people=[{"label": "1st director", "name_from": "Endole director",
                           "how": [{"method": "guess_patterns", "verify": "must_pass"}]}])
    v = vstub()
    _events, emit = _emit_collector()
    out = pipeline.run([_firm(row_a), _firm(row_b)], {**CFG, "recipe": rec}, v, emit, fm=FM)
    assert len(out) == 2, out
    assert out[0]["people_tried"] == ["1st director"], out[0]["people_tried"]
    assert out[1]["people_tried"] == [], out[1]["people_tried"]
    assert out[1]["status"] == recipe_mod.STATUS_NO_PERSON, out[1]["status"]
    assert len(v.asked) == 3, v.asked          # Ian guessed once, not twice


# ═══════════════════ 7. ⛔ the old lanes are untouched ═══════════════

LEGACY_CFG = {"use_endole": True, "verify_endole_with_mf": True, "use_patterns": True,
              "pattern_mode": "lean", "block_security_gateways": True}


def check_no_recipe_is_untouched():
    """Run the WHOLE of eval_pipeline against the rewritten pipeline.

    This is the promise the design was approved on: a campaign with no recipe keeps
    today's exact order. If this fails, the rewrite is not allowed to ship."""
    import eval_pipeline
    for c in eval_pipeline.CHECKS:
        c()


def check_a_legacy_row_grows_no_new_keys():
    """The recipe row carries `accepted` and `send_ready`. A LEGACY row must not — both
    are read by core/sheets.py build_writeback_row and webapp/server.py's send gate, so
    one leaking in would quietly change what every old campaign writes and pushes."""
    _events, emit = _emit_collector()
    firm = {"Company Name": "Smith & Co", "company_key": "Smith & Co",
            "lead_domain": "smithco.co.uk", "lead_director": "Ian Smith",
            "lead_firstname": "ian", "lead_lastname": "smith",
            "Oldest Director Name": "Ian Smith", "is_no_website_path": False,
            "lead_endole_email": "", "endole_generic": False,
            "email_security_gateway_provider": ""}
    r = pipeline.process_firm(firm, LEGACY_CFG, vstub("ian.smith@smithco.co.uk"), emit)
    assert r["status"] == "email_found" and r["email_source"] == "pattern_first.last", r
    for leaked in ("send_ready", "accepted", "recipe", "found_for", "found_by",
                   "needs_check", "people_tried", "people_dropped", "alternate_emails",
                   "contact_name"):
        assert leaked not in r, f"the recipe work leaked '{leaked}' into a legacy row"
    assert r["selected_director"] == "Ian Smith", r["selected_director"]


def check_an_empty_recipe_key_still_means_no_recipe():
    """`cfg["recipe"] = None` / "" / {} is the normal case for every existing campaign."""
    firm = {"Company Name": "Smith & Co", "lead_domain": "smithco.co.uk",
            "lead_director": "Ian Smith", "lead_firstname": "ian", "lead_lastname": "smith",
            "is_no_website_path": False, "lead_endole_email": "", "endole_generic": False,
            "email_security_gateway_provider": ""}
    for empty in (None, "", {}, []):
        _events, emit = _emit_collector()
        r = pipeline.process_firm(firm, {**LEGACY_CFG, "recipe": empty},
                                  vstub("ian.smith@smithco.co.uk"), emit)
        assert r["status"] == "email_found", (empty, r["status"])
        assert "send_ready" not in r, (empty, "took the recipe path")


# ═══════════════════ 8. the wiring: write-back, campaigns, ledger ════

def check_writeback_touches_only_the_four_columns():
    from core import sheets as sheets_mod
    r = recipe_mod.Recipe(recipe1())
    result = {"lead_id": "ch-1", "status": "email_found", "found_email": "a@b.co.uk",
              "found_for": "Ian Smith (1st director)", "found_by": "guessed (first.last@) · good",
              # things the OLD write-back would have written over:
              "contact_name": "Ian Smith", "email_source": "pattern_first.last",
              "icebreaker": "a line", "company": "Smith & Co", "verification": "good"}
    up = sheets_mod.build_recipe_writeback_row(result, r, key_header="lead_id")
    assert sorted(up) == ["Found By", "Found Email", "Found For", "email_status", "lead_id"], sorted(up)
    # ⛔ his two hand-filled columns are not reachable from here, nor is his Status
    assert "Contact Name" not in up and "Email Source" not in up, up
    assert "Ice Breaker" not in up and "send_ready" not in up, up
    assert "Status" not in up, up
    assert up["email_status"] == "enriched" and up["Found Email"] == "a@b.co.uk"


def check_a_row_that_found_nothing_writes_only_its_status():
    from core import sheets as sheets_mod
    r = recipe_mod.Recipe(recipe1())
    up = sheets_mod.build_recipe_writeback_row(
        {"lead_id": "ch-9", "status": "email_not_found", "found_email": ""}, r, key_header="lead_id")
    assert sorted(up) == ["email_status", "lead_id"], sorted(up)
    assert up["email_status"] == "no_email", up
    # rule 1: a failed search says nothing about the address already on the row
    assert "Found Email" not in up, up


def check_only_when_something_is_found_writes_nothing():
    from core import sheets as sheets_mod
    r = recipe_mod.Recipe(recipe1(write={**recipe1()["write"], "write_when": "on_find"}))
    assert sheets_mod.build_recipe_writeback_row(
        {"lead_id": "x", "status": "email_not_found", "found_email": ""}, r, key_header="lead_id") == {}
    got = sheets_mod.build_recipe_writeback_row(
        {"lead_id": "x", "status": "email_found", "found_email": "a@b.co"}, r, key_header="lead_id")
    assert got["Found Email"] == "a@b.co", got


def check_a_campaign_can_point_at_a_recipe():
    from core import campaigns as campaigns_mod
    c = campaigns_mod.Campaign({"id": "northwind-ch", "tab": "CH 1", "recipe": "director-waterfall"})
    assert c.recipe == "director-waterfall"
    assert campaigns_mod.Campaign({"id": "old", "tab": "T"}).recipe == "", "old lanes have none"
    # a copied campaign keeps the recipe: recipes are shared on purpose
    row, probs = campaigns_mod.new_campaign([], name="Copy", tab="CH 2", copy_from=c.to_dict())
    assert probs == [] and row["recipe"] == "director-waterfall", (probs, row)


def check_validate_reports_a_missing_or_broken_recipe():
    from core import campaigns as campaigns_mod
    camp = campaigns_mod.Campaign({"id": "northwind-ch", "tab": "CH 1", "recipe": "gone",
                                   "limits": {"per_run": 30, "per_day": 100}})
    issues = [i["issue"] for i in campaigns_mod.validate([camp], recipes={})]
    assert any("no longer exists" in i for i in issues), issues
    # a recipe that exists but is broken is reported too, not silently ignored
    broken = recipe_mod.Recipe({"id": "gone", "name": "Broken", "people": []})
    issues = [i["issue"] for i in campaigns_mod.validate([camp], recipes={"gone": broken})]
    assert any("at least one person" in i for i in issues), issues
    # and a lane with no recipe is never complained about
    plain = campaigns_mod.Campaign({"id": "old", "tab": "T", "limits": {"per_run": 1, "per_day": 1}})
    assert [i for i in campaigns_mod.validate([plain], recipes={}) if "recipe" in i["issue"]] == []


def check_the_ledger_knows_the_new_outcomes():
    """Without this a lead marked "check by hand" is picked up and paid for again."""
    from core import ledger as ledger_mod
    for s in recipe_mod.TERMINAL_STATUSES:
        if s == recipe_mod.STATUS_NOT_FOUND:
            continue
        assert s in ledger_mod.TERMINAL, f"{s} is not terminal — it would be retried"
    # a row that had nobody YET may be tried again: a name added later makes it workable,
    # and nothing was ever spent on it
    assert recipe_mod.STATUS_NO_PERSON in ledger_mod.RETRYABLE
    assert recipe_mod.STATUS_CHECK_BY_HAND not in ledger_mod.RETRYABLE


def check_every_recipe_status_has_a_tally_bucket():
    from webapp import server as S
    for s in recipe_mod.TERMINAL_STATUSES:
        assert s in S.TALLY, f"{s} would not be counted on the run page"
        assert S.TALLY[s] in S._new_counters(), f"{S.TALLY[s]} is not a counter"


def check_a_free_test_never_writes_the_person_memory():
    """⛔ its finds are invented — remembering them would stop the real run searching."""
    from webapp import server as S
    rec = recipe_mod.Recipe(recipe1())
    with tempfile.TemporaryDirectory() as d:
        saved = S.PERSON_CACHE_FILE
        try:
            S.PERSON_CACHE_FILE = Path(d) / "person_cache.json"
            seen, remember, flush = S._person_memory(rec, test_mode=True)
            remember("smith|ian smith")
            assert seen("smith|ian smith"), "it must still de-duplicate inside the one test run"
            flush()
            assert not S.PERSON_CACHE_FILE.exists(), "a free test wrote to the person cache"

            seen, remember, flush = S._person_memory(rec, test_mode=False)
            remember("smith|ian smith")
            flush()
            assert S.PERSON_CACHE_FILE.exists(), "a live run did not remember anybody"
            # a later run reads it back
            seen2, _r2, _f2 = S._person_memory(rec, test_mode=False)
            assert seen2("smith|ian smith")
            # ...and a test run does not, so a test shows the whole ladder
            seen3, _r3, _f3 = S._person_memory(rec, test_mode=True)
            assert not seen3("smith|ian smith")
        finally:
            S.PERSON_CACHE_FILE = saved


def check_a_campaign_can_be_saved_while_its_recipe_is_still_blank():
    """The chicken-and-egg this nearly shipped with.

    A brand-new recipe has no columns picked, so it does not validate. The editor cannot
    offer the right columns until a campaign points at it (that is where the sheet comes
    from). If saving the campaign is blocked on the recipe being complete, a new recipe can
    never be attached to anything. The RUN is the gate, not the save."""
    from webapp import server as S
    with tempfile.TemporaryDirectory() as d:
        saved_cfg, saved_rec = S.CONFIG_DIR, S.RECIPES_DIR
        try:
            S.CONFIG_DIR = Path(d)
            S.RECIPES_DIR = Path(d) / "recipes"
            recipe_mod.save(S.RECIPES_DIR, recipe_mod.blank("Brand new"))
            body = {"globals": {}, "campaigns": [
                {"id": "lane", "name": "Lane", "tab": "T", "recipe": "brand-new",
                 "limits": {"per_run": 10, "per_day": 10}}]}
            out = S._write_campaigns_raw(body)
            assert out["ok"], f"a campaign could not be attached to a new recipe: {out}"

            # ...but every screen still SHOWS the problem
            camp = __import__("core.campaigns", fromlist=["x"]).Campaign(body["campaigns"][0])
            issues = [i["issue"] for i in
                      __import__("core.campaigns", fromlist=["x"]).validate(
                          [camp], recipes=recipe_mod.load_dir(S.RECIPES_DIR))]
            assert any("pick the column" in i for i in issues), issues
        finally:
            S.CONFIG_DIR, S.RECIPES_DIR = saved_cfg, saved_rec


def check_the_whole_cell_is_the_default_and_unchanged():
    """`whole` must be byte-for-byte today's behaviour, or every saved recipe moves."""
    for cell in ("Ian Smith", "Ian Smith, Jane Doe", "", "  Ian Smith  ", "Smith & Co, Ian"):
        assert recipe_mod.pick_name(cell) == cell.strip(), cell
        assert recipe_mod.pick_name(cell, "whole") == cell.strip(), cell
    # a person with no name_pick at all is "whole"
    p = recipe_mod.Person({"label": "x", "name_from": "Contact 2"})
    assert p.name_pick == "whole", p.name_pick


def check_one_name_is_taken_out_of_a_comma_list():
    cell = "Daljeet Kaur Bangaa, Amandeep Singh, Third Person"
    assert recipe_mod.pick_name(cell, "1st") == "Daljeet Kaur Bangaa"
    assert recipe_mod.pick_name(cell, "2nd") == "Amandeep Singh"
    assert recipe_mod.pick_name(cell, "3rd") == "Third Person"
    # a cell with no comma holds one name, so 1st and whole agree
    assert recipe_mod.pick_name("Ian Smith", "1st") == "Ian Smith"
    # past the end is NOBODY, never the 1st again — "the 2nd director" of a one-director
    # firm does not exist, and emailing the 1st twice would be the silent wrong answer
    assert recipe_mod.pick_name("Ian Smith", "2nd") == ""
    # empty entries from a trailing or doubled comma are not names
    assert recipe_mod.pick_name("Ian Smith,", "2nd") == ""
    assert recipe_mod.pick_name("Ian Smith, , Jane Doe", "2nd") == "Jane Doe"
    # an unknown value is never silently treated as the 1st
    assert recipe_mod.pick_name("Ian Smith, Jane Doe", "4th") == "Ian Smith, Jane Doe"


def check_a_rung_with_no_name_left_falls_to_the_next_column():
    """The real CH shape: Contact Name is one name, Contact 2 is the rest of the board."""
    row = _row(**{"Contact Name": "Ian Smith, Jane Doe", "Contact 2": "Jane Doe, Kim Lee"})
    rec = recipe_mod.Recipe(recipe1(people=[
        {"label": "1st director", "name_from": ["Contact Name"], "name_pick": "1st",
         "how": _ways_with_website()},
        {"label": "2nd director", "name_from": ["Contact 2"], "name_pick": "1st",
         "how": _ways_with_website()},
        {"label": "3rd director", "name_from": ["Contact 2"], "name_pick": "2nd",
         "how": _ways_with_website()},
    ]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    assert [p["name"] for p in plan["people"]] == ["Ian Smith", "Jane Doe", "Kim Lee"], plan["people"]
    # and the 2nd rung is dropped, not wrongly filled, when the list is only one long
    thin = _row(**{"Contact Name": "Ian Smith", "Contact 2": ""})
    plan2 = recipe_mod.plan_for_row(rec, thin, _firm(thin), FM)
    assert [p["name"] for p in plan2["people"]] == ["Ian Smith"], plan2["people"]


def check_the_leaver_is_caught_inside_a_list():
    """'Director Who Left' compared against a whole list would miss the leaver."""
    row = _row(**{"Contact Name": "Brian Old", "Director Who Left": "Jane Doe, Brian Old"})
    rec = recipe_mod.Recipe(recipe1(people=[
        {"label": "1st director", "name_from": ["Contact Name"], "name_pick": "1st",
         "never_if_same_as": ["Director Who Left"], "how": _ways_with_website()},
    ]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    assert not plan["people"], plan["people"]
    assert "Director Who Left" in plan["dropped"][0]["why"], plan["dropped"]


def check_a_bad_which_name_value_is_refused():
    bad = recipe1(people=[{"label": "1st director", "name_from": "Contact Name",
                           "name_pick": "the first one", "how": _ways_with_website()}])
    issues = recipe_mod.validate(bad)
    assert any("not a choice of which name" in i for i in issues), issues
    # and picking a name out of a cell needs a cell to pick from
    noc = recipe1(people=[{"label": "x", "address_from": "Email", "name_pick": "2nd",
                           "how": [{"method": "use_as_is", "verify": "must_pass"}]}])
    assert any("needs a name column" in i for i in recipe_mod.validate(noc)), \
        recipe_mod.validate(noc)


def _reuse_rung(**over) -> dict:
    """His 2026-10-08 rule: use the address already on the row, but only when it belongs to
    a director and the firm was never contacted from the Northwind domain."""
    rung = {"label": "the email already on the row",
            "name_from": ["Email Person"], "address_from": "Email",
            "only_if": {"all": [{"field": "Already Contacted", "op": "is_blank"}]},
            "only_if_same_as": ["Contact Name", "Endole director", "Apollo director"],
            "how": [{"method": "use_as_is", "verify": "must_pass"}]}
    rung.update(over)
    return rung


def check_only_if_same_as_keeps_a_directors_own_address():
    row = _row(**{"Contact Name": "Ian Smith", "Email Person": "Ian Smith",
                  "Email": "ian@smithco.co.uk", "Already Contacted": ""})
    rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung()]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    assert [p["label"] for p in plan["people"]] == ["the email already on the row"], plan["dropped"]
    assert plan["people"][0]["address"] == "ian@smithco.co.uk", plan["people"][0]
    # and it costs nothing to work out — plan_for_row is pure
    est = recipe_mod.estimate_row(plan)
    assert est["max_icypeas_credits"] == 0, est


def check_only_if_same_as_drops_somebody_elses_address():
    """A case seen live: the row's address belongs to someone who is not a director."""
    row = _row(**{"Contact Name": "Ian Smith", "Contact 2": "", "Email Person": "Caroline Reed",
                  "Email": "caroline@smithco.co.uk", "Already Contacted": ""})
    rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung()]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    assert not plan["people"], plan["people"]
    assert "is not the person in" in plan["dropped"][0]["why"], plan["dropped"]


def check_only_if_same_as_reads_a_comma_cell_both_ways():
    """Same two readings of a comma as never_if_same_as — they share `same_person_in`."""
    listed = _row(**{"Contact Name": "Jane Doe, Ian Smith", "Email Person": "Ian Smith",
                     "Email": "ian@smithco.co.uk"})
    surname_first = _row(**{"Contact Name": "Smith, Ian", "Email Person": "Ian Smith",
                            "Email": "ian@smithco.co.uk"})
    rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung(
        only_if_same_as=["Contact Name"], only_if={})]))
    for row, what in ((listed, "a list"), (surname_first, "surname first")):
        plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
        assert plan["people"], f"{what}: {plan['dropped']}"


def check_already_contacted_still_blocks_the_reuse():
    row = _row(**{"Contact Name": "Ian Smith", "Email Person": "Ian Smith",
                  "Email": "ian@smithco.co.uk", "Already Contacted": "2026-09-14"})
    rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung()]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    assert not plan["people"], plan["people"]
    assert "'only if' not met" in plan["dropped"][0]["why"], plan["dropped"]


def check_reusing_the_address_stops_the_director_being_searched_again():
    """Put the reuse rung FIRST and the 1st-director rung must not search the same person."""
    row = _row(**{"Contact Name": "Ian Smith", "Contact 2": "Jane Doe",
                  "Email Person": "Ian Smith", "Email": "ian@smithco.co.uk",
                  "Already Contacted": ""})
    rec = recipe_mod.Recipe(recipe1(people=[
        _reuse_rung(),
        {"label": "1st director", "name_from": ["Contact Name"], "name_pick": "1st",
         "how": _ways_with_website()},
        {"label": "2nd director", "name_from": ["Contact 2"], "name_pick": "1st",
         "how": _ways_with_website()},
    ]))
    plan = recipe_mod.plan_for_row(rec, row, _firm(row), FM)
    labels = [p["label"] for p in plan["people"]]
    assert labels[0] == "the email already on the row", labels
    assert "1st director" not in labels, labels
    assert any("already tried higher up" in d["why"] for d in plan["dropped"]), plan["dropped"]
    # the 2nd director is still available if the reused address fails its check
    assert "2nd director" in labels, labels


def check_a_person_test_with_no_name_column_is_refused():
    """Without a name there is nobody to compare, so every row would silently be dropped."""
    bad = recipe1(people=[{"label": "x", "address_from": "Email",
                           "only_if_same_as": ["Contact Name"],
                           "how": [{"method": "use_as_is", "verify": "must_pass"}]}])
    assert any("nobody to compare" in i for i in recipe_mod.validate(bad)), recipe_mod.validate(bad)
    # and a column in both lists can never pass
    both = recipe1(people=[{"label": "x", "name_from": "Email Person",
                            "address_from": "Email",
                            "only_if_same_as": ["Contact Name"],
                            "never_if_same_as": ["Contact Name"],
                            "how": [{"method": "use_as_is", "verify": "must_pass"}]}])
    assert any("nothing can ever pass" in i for i in recipe_mod.validate(both)), \
        recipe_mod.validate(both)


def check_the_two_person_tests_cannot_disagree():
    """Both go through `same_person_in`, so one can never see a match the other misses."""
    for cell in ("Ian Smith", "Smith, Ian", "Jane Doe, Ian Smith", "", "Ian  Smith"):
        key = recipe_mod._name_key("Ian Smith")
        row = _row(**{"Contact Name": cell, "Email Person": "Ian Smith",
                      "Email": "ian@smithco.co.uk"})
        want = recipe_mod.same_person_in(cell, key)
        only_rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung(
            only_if_same_as=["Contact Name"], only_if={})]))
        never_rec = recipe_mod.Recipe(recipe1(people=[_reuse_rung(
            only_if_same_as=[], never_if_same_as=["Contact Name"], only_if={})]))
        got_only = bool(recipe_mod.plan_for_row(only_rec, row, _firm(row), FM)["people"])
        got_never = bool(recipe_mod.plan_for_row(never_rec, row, _firm(row), FM)["people"])
        assert got_only == want, f"only_if_same_as disagrees on {cell!r}"
        assert got_never == (not want), f"never_if_same_as disagrees on {cell!r}"


def check_the_shipped_recipe_one_matches_the_real_ch_tabs():
    """Guards the live config against the design's two wrong column names coming back."""
    path = Path(__file__).parent / "config" / "recipes" / "director-waterfall.json"
    r = recipe_mod.Recipe(json.loads(path.read_text(encoding="utf-8")))
    assert recipe_mod.validate(r) == [], recipe_mod.validate(r)
    # 4 rungs since 2026-10-08: reuse a director's own address first, then the two searches,
    # then the old row's-email step kept as the last resort (dropping it lost 18 rows)
    assert [p.label for p in r.people] == [
        "an address already here, if it is a director's", "1st director", "2nd director",
        "the email already on the row"], [p.label for p in r.people]
    reuse, first, second = r.people[0], r.people[1], r.people[2]
    assert reuse.name_from == ["Email Person"], reuse.name_from
    assert reuse.address_from == "Email", reuse.address_from
    assert reuse.only_if_same_as, "the reuse rung MUST check the address belongs to a director"
    assert [w.method for w in reuse.how] == ["use_as_is"], reuse.how
    assert first.name_from[0] == "Contact Name", first.name_from
    assert first.name_pick == "1st", first.name_pick
    assert second.name_from == ["Contact 2"], second.name_from
    assert second.name_pick == "1st", second.name_pick
    # the 23 real headers of every CH trigger tab, read from the live sheet 2026-10-08
    headers = ["lead_id", "Status", "Company Name", "Website", "Contact Name", "Job Title",
               "Seniority", "Town", "Employees", "Trading Years", "Email", "Email Source",
               "Contact 2", "Ice Breaker", "Endole director", "Apollo director",
               "Email Person", "Already Contacted", "Director Who Left", "Next Step",
               "Found Email", "Found For", "Found By"]
    # ⛔ 2026-11-06: the recipe writes email_status, which the live tabs do not have yet.
    # Until he says yes to adding it, the pre-run check BLOCKS on that one column only.
    check = recipe_mod.check_against_sheet(r, headers)
    assert not check["ok"] and check["missing_write"] == ["email_status"], check
    assert not check["warnings"], check["warnings"]
    check = recipe_mod.check_against_sheet(r, headers + ["email_status"])
    assert check["ok"], check["blocking"]


def check_search_once_off_means_no_memory_at_all():
    from webapp import server as S
    rec = recipe_mod.Recipe(recipe1(limits={"per_run": 30, "search_same_person_once": False}))
    seen, remember, flush = S._person_memory(rec, test_mode=False)
    assert seen is None and remember is None
    flush()                      # must not blow up
    assert S._person_memory(None, test_mode=False)[0] is None, "no recipe = no memory"


CHECKS = [
    # the recipe
    check_valid_recipe_has_no_complaints, check_validate_catches_every_problem_at_once,
    check_empty_recipe_needs_a_person, check_missing_write_column_is_blocking,
    check_missing_read_column_is_only_a_warning, check_write_targets_are_only_four,
    # the plan
    check_plan_lists_his_three_people_in_order, check_name_falls_through_to_the_next_column,
    check_the_leaver_is_dropped_whatever_the_name_order, check_only_if_drops_the_row_address,
    check_skip_row_if_skips_the_whole_row, check_no_website_greys_out_guessing_and_says_why,
    check_a_person_named_twice_is_tried_once, check_estimate_is_a_ceiling_not_a_bill,
    check_a_rung_that_cannot_run_does_not_reserve_its_person,
    check_the_full_name_pattern_set_is_offered_to_a_recipe,
    check_the_two_extra_write_columns_are_opt_in,
    check_person_cache_key_ignores_name_order,
    # which name out of a cell that holds several (the CH tabs' comma lists)
    check_the_whole_cell_is_the_default_and_unchanged,
    check_one_name_is_taken_out_of_a_comma_list,
    check_a_rung_with_no_name_left_falls_to_the_next_column,
    check_the_leaver_is_caught_inside_a_list,
    check_a_bad_which_name_value_is_refused,
    # reuse the address already on the row, but only when it is a director's
    check_only_if_same_as_keeps_a_directors_own_address,
    check_only_if_same_as_drops_somebody_elses_address,
    check_only_if_same_as_reads_a_comma_cell_both_ways,
    check_already_contacted_still_blocks_the_reuse,
    check_reusing_the_address_stops_the_director_being_searched_again,
    check_a_person_test_with_no_name_column_is_refused,
    check_the_two_person_tests_cannot_disagree,
    check_the_shipped_recipe_one_matches_the_real_ch_tabs,
    # files
    check_save_load_round_trip_and_campaign_lookup, check_blank_recipe_is_valid_shape,
    # the ladder
    check_second_director_wins_when_the_first_fails,
    check_first_pass_stops_and_never_pays_for_the_rest,
    check_the_row_address_is_used_when_no_director_is_named,
    check_a_row_with_nobody_is_skipped_not_failed, check_skip_row_if_spends_nothing,
    check_the_security_guard_still_runs_first,
    # the no-website lane
    check_no_website_asks_icypeas_by_company_name,
    check_a_foreign_domain_is_found_but_marked_for_a_human,
    check_the_firms_own_domain_is_not_nagged_about,
    check_the_real_icypeas_test_mode_still_fits_the_recipe_path,
    # the stop rules
    check_nothing_passed_and_last_resort_off_writes_no_address,
    check_last_resort_writes_a_real_address_marked_and_unsendable,
    check_a_failed_guess_is_never_the_last_resort,
    check_write_but_mark_as_failed_keeps_a_guess,
    check_no_check_is_accepted_but_still_cannot_be_sent,
    check_try_everyone_keeps_the_best_not_the_first,
    check_the_same_person_is_searched_once_across_firms,
    # the old lanes
    check_no_recipe_is_untouched, check_a_legacy_row_grows_no_new_keys,
    check_an_empty_recipe_key_still_means_no_recipe,
    # the wiring
    check_writeback_touches_only_the_four_columns,
    check_a_row_that_found_nothing_writes_only_its_status,
    check_only_when_something_is_found_writes_nothing,
    check_a_campaign_can_point_at_a_recipe,
    check_validate_reports_a_missing_or_broken_recipe,
    check_the_ledger_knows_the_new_outcomes,
    check_every_recipe_status_has_a_tally_bucket,
    check_a_free_test_never_writes_the_person_memory,
    check_search_once_off_means_no_memory_at_all,
    check_a_campaign_can_be_saved_while_its_recipe_is_still_blank,
]


def test_valid(): check_valid_recipe_has_no_complaints()
def test_validate_all(): check_validate_catches_every_problem_at_once()
def test_empty_people(): check_empty_recipe_needs_a_person()
def test_write_col_missing(): check_missing_write_column_is_blocking()
def test_read_col_missing(): check_missing_read_column_is_only_a_warning()
def test_four_columns(): check_write_targets_are_only_four()
def test_plan_order(): check_plan_lists_his_three_people_in_order()
def test_name_fallthrough(): check_name_falls_through_to_the_next_column()
def test_leaver(): check_the_leaver_is_dropped_whatever_the_name_order()
def test_only_if(): check_only_if_drops_the_row_address()
def test_skip_row(): check_skip_row_if_skips_the_whole_row()
def test_no_website_greyed(): check_no_website_greys_out_guessing_and_says_why()
def test_dupe_person(): check_a_person_named_twice_is_tried_once()
def test_estimate(): check_estimate_is_a_ceiling_not_a_bill()
def test_cache_key(): check_person_cache_key_ignores_name_order()
def test_files(): check_save_load_round_trip_and_campaign_lookup()
def test_blank(): check_blank_recipe_is_valid_shape()
def test_ladder(): check_second_director_wins_when_the_first_fails()
def test_first_pass(): check_first_pass_stops_and_never_pays_for_the_rest()
def test_row_address(): check_the_row_address_is_used_when_no_director_is_named()
def test_nobody(): check_a_row_with_nobody_is_skipped_not_failed()
def test_skip_spends_nothing(): check_skip_row_if_spends_nothing()
def test_gateway_first(): check_the_security_guard_still_runs_first()
def test_company_search(): check_no_website_asks_icypeas_by_company_name()
def test_mismatch(): check_a_foreign_domain_is_found_but_marked_for_a_human()
def test_own_domain(): check_the_firms_own_domain_is_not_nagged_about()
def test_real_finder(): check_the_real_icypeas_test_mode_still_fits_the_recipe_path()
def test_last_resort_off(): check_nothing_passed_and_last_resort_off_writes_no_address()
def test_last_resort_on(): check_last_resort_writes_a_real_address_marked_and_unsendable()
def test_failed_guess(): check_a_failed_guess_is_never_the_last_resort()
def test_write_failed(): check_write_but_mark_as_failed_keeps_a_guess()
def test_no_check(): check_no_check_is_accepted_but_still_cannot_be_sent()
def test_keep_best(): check_try_everyone_keeps_the_best_not_the_first()
def test_same_person_once(): check_the_same_person_is_searched_once_across_firms()
def test_legacy_suite(): check_no_recipe_is_untouched()
def test_no_leaked_keys(): check_a_legacy_row_grows_no_new_keys()
def test_empty_recipe_key(): check_an_empty_recipe_key_still_means_no_recipe()
def test_writeback_four(): check_writeback_touches_only_the_four_columns()
def test_writeback_status_only(): check_a_row_that_found_nothing_writes_only_its_status()
def test_write_on_find(): check_only_when_something_is_found_writes_nothing()
def test_campaign_recipe_key(): check_a_campaign_can_point_at_a_recipe()
def test_campaign_validate(): check_validate_reports_a_missing_or_broken_recipe()
def test_ledger_terminal(): check_the_ledger_knows_the_new_outcomes()
def test_tally(): check_every_recipe_status_has_a_tally_bucket()
def test_person_memory(): check_a_free_test_never_writes_the_person_memory()
def test_person_memory_off(): check_search_once_off_means_no_memory_at_all()
def test_blank_recipe_attachable(): check_a_campaign_can_be_saved_while_its_recipe_is_still_blank()


def main() -> int:
    failed = 0
    for c in CHECKS:
        try:
            c(); print(f"PASS  {c.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {c.__name__}: {e}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
