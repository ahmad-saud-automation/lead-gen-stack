"""
eval_lead_record.py — the shared lead record (core/lead_record.py), build session 1.

The trap: Find email wrote `email_found` / `no_website` into `Status`, and Icebreaker
Studio reads any text there as "finished". Every check here failed on the code before
2026-11-06 (the module did not exist, and both write paths wrote `Status`).

Run:  python eval_lead_record.py
"""
from __future__ import annotations

import sys

from core import fieldmap as fieldmap_mod
from core import lead_record as LR
from core import organize
from core import recipe as recipe_mod
from core import sheets


def _refused(fn) -> bool:
    try:
        fn()
    except LR.WriteRefused:
        return True
    return False


def check_each_step_owns_exactly_one_column():
    owned = [c for s in LR.STAGES for c in LR.allowed(s)]
    assert sorted(owned) == sorted(set(owned)), "two steps share a column"
    assert set(owned) == {"website_status", "email_status", "icebreaker_status",
                          "push_status", "reply_status"}, owned
    assert "Status" not in owned


def check_the_three_values_he_approved_exist():
    for v in ("check_by_hand", "held", "skipped"):
        assert v in LR.VALUES["email_status"], v
    for col, vals in LR.VALUES.items():
        assert set(vals) == set(LR.LABELS[col]), f"{col}: every value needs a screen label"


def check_no_step_may_write_status_or_another_steps_column():
    for stage in LR.STAGES:
        assert _refused(lambda s=stage: LR.guard(s, {"Status": "x"})), stage
        for col, owner in LR.OWNER.items():
            if owner != stage:
                assert _refused(lambda s=stage, c=col: LR.stage_update(s, {c: LR.VALUES[c][0]})), (stage, col)
                assert _refused(lambda s=stage, c=col: LR.guard(s, {c: "x"})), (stage, col)
    # its own column, an allowed value: fine
    assert LR.stage_update("find_email", {"email_status": "enriched"}) == {"email_status": "enriched"}
    # its own column, a made-up value: refused
    assert _refused(lambda: LR.stage_update("find_email", {"email_status": "email_found"}))


def check_organized_sheets_map_through_their_field_map():
    fm = fieldmap_mod.load("config/fieldmap.northwind-organized.json")
    assert LR.header(fm, "email_status") == "enrich_status"
    assert LR.header(fm, "push_status") == "status"
    # on that sheet the lowercase `status` is Sending's: Find email may not touch it
    assert _refused(lambda: LR.guard("find_email", {"status": "x"}, fm))
    assert LR.guard("sending", {"status": "pushed"}, fm) == {"status": "pushed"}


def check_push_status_never_aliases_his_status_column():
    """`status` and `Status` compare equal once case is ignored — no alias may reach it."""
    empty = fieldmap_mod.FieldMap({})
    assert LR.header(empty, "push_status", headers=["Status", "Company Name"]) == ""
    assert LR.header(empty, "email_status", headers=["Status", "enrich_status"]) == "enrich_status"


def check_engine_outcomes_map_to_stored_values():
    cases = [
        ({"status": "email_found", "found_email": "a@b.co", "email_source": "endole"}, "as-is"),
        ({"status": "email_found", "found_email": "a@b.co", "email_source": "pattern_first"}, "enriched"),
        ({"status": "email_found", "found_email": "a@b.co", "found_rung": "fallback email column",
          "email_source": "endole"}, "fallback"),
        ({"status": "email_found", "found_email": "a@b.co", "found_rung": "1st director",
          "email_source": "icypeas_domain"}, "enriched"),
        ({"status": "email_not_found"}, "no_email"),
        ({"status": "email_failed_check", "found_email": "a@b.co"}, "no_email"),
        ({"status": "no_website"}, "no_website"),
        ({"status": "skipped_no_person"}, "no_person"),
        ({"status": "check_by_hand", "found_email": "a@b.co"}, "check_by_hand"),
        ({"status": "hold_security_gateway"}, "held"),
        ({"status": "skipped_by_rule"}, "skipped"),
        ({"status": "something new"}, "error"),
    ]
    for result, want in cases:
        got = LR.email_status_for(result)
        assert got == want, (result, got, want)
        assert got in LR.VALUES["email_status"]


def check_the_fixed_path_writes_email_status_not_status():
    up = sheets.build_writeback_row({"company": "Acme", "row_key": "P-1"}, "no_website",
                                    stage="find_email")
    assert "Status" not in up and "Final Status" not in up, up
    assert up["email_status"] == "no_website", up
    # through an Organized field map it lands in enrich_status, never the push column
    fm = fieldmap_mod.load("config/fieldmap.northwind-organized.json")
    mapped = sheets.to_sheet_row(up, fm)
    assert mapped.get("enrich_status") == "no_website", mapped
    assert "status" not in mapped, mapped
    # the push's write is untouched until session 2
    push = sheets.build_writeback_row({"company": "Acme"}, "pushed_to_instantly_x")
    assert push["Status"] == "pushed_to_instantly_x"


def check_the_recipe_path_writes_email_status_not_status():
    r = recipe_mod.Recipe({"id": "t", "name": "t",
                           "people": [{"label": "1st director", "name_from": ["Contact Name"],
                                       "how": [{"method": "guess_patterns"}]}]})
    assert r.write_targets()["status_to"] == "email_status"
    row = sheets.build_recipe_writeback_row(
        {"lead_id": "x", "found_email": "a@b.co", "found_rung": "1st director",
         "email_source": "pattern_first.last", "contact_name": "Ian Smith",
         "status": "email_found"}, r, key_header="lead_id")
    assert "Status" not in row and row["email_status"] == "enriched", row


def check_a_recipe_that_names_status_is_refused():
    bad = recipe_mod.Recipe({"id": "t", "name": "t",
                             "people": [{"label": "p", "name_from": ["Contact Name"],
                                         "how": [{"method": "guess_patterns"}]}],
                             "write": {"status_to": "Status"}})
    issues = recipe_mod.validate(bad)
    assert any("notes column" in i for i in issues), issues
    assert _refused(lambda: sheets.build_recipe_writeback_row(
        {"lead_id": "x", "status": "email_not_found"}, bad, key_header="lead_id"))


def check_the_shipped_ch_recipe_no_longer_writes_status():
    import json
    raw = json.loads(open("config/recipes/director-waterfall.json", encoding="utf-8").read())
    r = recipe_mod.Recipe(raw)
    assert "Status" not in r.write_columns(), r.write_columns()
    # a CH tab has no email_status column yet: the pre-run check must BLOCK, not write nowhere
    ch_headers = ["lead_id", "Company Name", "Status", "Found Email", "Found For", "Found By",
                  "Contact Name", "Endole director", "Apollo director", "Contact 2", "Email",
                  "Email Person", "Already Contacted", "Director Who Left", "Seniority", "Website"]
    out = recipe_mod.check_against_sheet(r, ch_headers)
    assert not out.get("ok", True), out


def check_a_row_with_email_status_is_not_searched_again():
    fm = fieldmap_mod.FieldMap({"row_key": "lead_id", "company_name": "Company Name"})
    rows = [{"lead_id": "1", "Company Name": "A Ltd", "Status": "", "email_status": "enriched"},
            {"lead_id": "2", "Company Name": "B Ltd", "Status": "", "email_status": ""},
            {"lead_id": "3", "Company Name": "C Ltd", "Status": "", "email_status": "error"},
            {"lead_id": "4", "Company Name": "D Ltd", "Status": "email_not_found", "email_status": ""}]
    firms, skipped = _organize(rows, fm)
    names = sorted(f.get("Company Name") for f in firms)
    assert names == ["B Ltd", "C Ltd"], (names, skipped)   # error is retried; old Status honoured


def _organize(rows, fm):
    import inspect
    fn = organize.organize
    params = inspect.signature(fn).parameters
    kw = {"fm": fm} if "fm" in params else {}
    out = fn(rows, **kw)
    if isinstance(out, tuple):
        return out[0], out[1] if len(out) > 1 else {}
    return out.get("firms", out), out.get("skipped", {})


CHECKS = [check_each_step_owns_exactly_one_column,
          check_the_three_values_he_approved_exist,
          check_no_step_may_write_status_or_another_steps_column,
          check_organized_sheets_map_through_their_field_map,
          check_push_status_never_aliases_his_status_column,
          check_engine_outcomes_map_to_stored_values,
          check_the_fixed_path_writes_email_status_not_status,
          check_the_recipe_path_writes_email_status_not_status,
          check_a_recipe_that_names_status_is_refused,
          check_the_shipped_ch_recipe_no_longer_writes_status,
          check_a_row_with_email_status_is_not_searched_again]


def test_all():
    for c in CHECKS:
        c()


def main() -> int:
    failed = 0
    for c in CHECKS:
        try:
            c(); print(f"PASS  {c.__name__}")
        except Exception as e:  # noqa: BLE001 - a crash is a failure too
            failed += 1; print(f"FAIL  {c.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
