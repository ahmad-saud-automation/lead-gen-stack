"""
eval_runner.py - offline test for campaign -> exact leads (no network, no keys).
    python eval_runner.py   /   pytest eval_runner.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core import runner
from core.campaigns import Campaign
from core.fieldmap import FieldMap
from core.ledger import Ledger

NORTHWIND_MAP = FieldMap({
    "row_key": "lead_id", "company_name": "Company Name", "status": "Status",
    "send_gate": "send_ready", "website": "Website", "contact_name": "Contact Name",
    "contact_first": "First Name", "contact_last": "Last Name", "job_title": "Job Title",
    "seniority_rank": "seniority_label", "employees": "Employees",
    "found_email": "Found Email", "icebreaker": "Ice Breaker", "phone": "Telephone",
})


def _row(i, **kw):
    r = {"lead_id": f"P-{i}", "Company Name": f"Firm {i}", "Website": f"firm{i}.co.uk",
         "Status": "", "send_ready": "yes", "Contact Name": f"Person {i}",
         "First Name": "Person", "Last Name": str(i),
         "Job Title": "Owner", "seniority_label": "owner", "Employees": "5",
         "Telephone": "020", "Found Email": "", "Ice Breaker": "",
         "trigger_family": "A5_departure", "Intent": "capacity"}
    r.update(kw)
    return r


def _camp(**kw):
    base = {"id": "micro", "name": "micro", "enabled": True, "tab": "Practices",
            "limits": {"per_run": 3, "per_day": 100},
            "rules": {"all": [{"field": "send_gate", "op": "equals", "value": "yes"}]},
            "writeback": {"campaign_type": "Northwind-1"}}
    base.update(kw)
    return Campaign(base)


def _ledger():
    return Ledger(Path(tempfile.mkdtemp()) / "ledger.db")


def check_headers_are_read_from_the_rows():
    rows = [{"a": 1, "b": 2}, {"a": 1, "c": 3}]
    assert runner.headers_of(rows) == ["a", "b", "c"], runner.headers_of(rows)


def check_a_bad_map_blocks_the_run_before_it_spends():
    bad = FieldMap({"row_key": "lead_id", "company_name": "Company Name",
                    "status": "Status", "icebreaker": "Not A Column"})
    out = runner.check_fieldmap(bad, list(_row(0)))
    assert out["ok"] is False
    assert any("silently discarded" in b for b in out["blocking"]), out["blocking"]

    ok = runner.check_fieldmap(NORTHWIND_MAP, list(_row(0)))
    assert ok["ok"] is True, ok["blocking"]


def check_prepare_selects_caps_and_labels():
    rows = [_row(i) for i in range(10)] + [_row(90 + i, send_ready="no") for i in range(3)]
    out = runner.prepare(_camp(), rows, NORTHWIND_MAP)
    assert out["matched"] == 10, out
    assert out["selected"] == 3, out                  # per_run
    assert len(out["firms"]) == 3
    f = out["firms"][0]
    assert f["campaign"] == "micro" and f["campaign_type"] == "Northwind-1", f
    assert f["row_key"] == f["lead_id"] != "", f
    assert f["_raw"]["Intent"] == "capacity", "the raw row must ride along for the labels"


def check_the_ledger_removes_leads_already_done():
    rows = [_row(i) for i in range(6)]
    led = _ledger()
    led.record({"row_key": "p-0", "status": "email_found"})
    led.record({"row_key": "p-1", "status": "no_website"})
    out = runner.prepare(_camp(), rows, NORTHWIND_MAP, ledger=led)
    assert out["matched"] == 6 and out["blocked_by_ledger"] == 2, out
    assert out["available"] == 4
    keys = [f["row_key"] for f in out["firms"]]
    assert "p-0" not in keys and "p-1" not in keys, keys


def check_the_daily_limit_caps_the_second_run_of_the_day():
    rows = [_row(i) for i in range(20)]
    led = _ledger()
    camp = _camp(limits={"per_run": 10, "per_day": 12})
    first = runner.prepare(camp, rows, NORTHWIND_MAP, ledger=led)
    assert first["selected"] == 10, first
    for f in first["firms"]:                       # the run records what it worked on
        led.record({"row_key": f["row_key"], "status": "email_found"}, campaign="micro")
    second = runner.prepare(camp, rows, NORTHWIND_MAP, ledger=led)
    assert second["day_remaining"] == 2, second
    assert second["selected"] == 2, second         # not 10 - the day's budget is spent


def check_the_sheets_own_seniority_beats_our_title_guess():
    """The P4 fix. V1 re-ranked with its own list against Job Title (23% filled) and threw
    away seniority_label (100% filled), so it picked worse contacts than the sheet had."""
    # one row, two people: the sheet says the second is the owner, the titles say nothing
    rows = [_row(1, **{"Contact Name": "Junior Person", "Job Title": "",
                       "seniority_label": "statutory_director"}),
            _row(2, **{"lead_id": "P-1", "Contact Name": "Real Owner", "Job Title": "",
                       "seniority_label": "owner"})]
    # same lead_id -> one firm, two candidate people
    rows[0]["lead_id"] = "P-1"
    out = runner.prepare(_camp(limits={"per_run": 5, "per_day": 50}), rows, NORTHWIND_MAP)
    assert len(out["firms"]) == 1, out["firms"]
    assert out["firms"][0]["lead_director"] == "Real Owner", out["firms"][0]["lead_director"]
    assert out["firms"][0]["seniority_label"] == "owner"


def check_an_email_already_on_the_row_reaches_the_pipeline():
    """⛔ THE 2026-09-06 OVERSPEND BUG. The campaign path never passed the sheet's own
    `Found Email` into the pipeline, so step 2 was skipped and every lead went straight to
    pattern guessing — re-buying addresses that had already been paid for.

    9 MillionVerifier checks were burned on 5 leads that mostly already had emails."""
    rows = [_row(1, **{"Found Email": "already@known.co.uk"}),
            _row(2, **{"Found Email": ""}),
            _row(3, **{"Found Email": "info@generic.co.uk"})]
    out = runner.prepare(_camp(limits={"per_run": 9, "per_day": 9}), rows, NORTHWIND_MAP)
    by = {f["row_key"]: f for f in out["firms"]}
    assert by["P-1"]["lead_endole_email"] == "already@known.co.uk", by["P-1"]
    assert by["P-1"]["endole_generic"] is False
    assert by["P-2"]["lead_endole_email"] == "", by["P-2"]
    # a role mailbox is carried but flagged, so the pipeline skips it instead of sending
    assert by["P-3"]["lead_endole_email"] == "info@generic.co.uk"
    assert by["P-3"]["endole_generic"] is True, by["P-3"]


def check_the_existing_email_is_used_before_any_guessing():
    """End to end: with an address on the row and re-verification OFF, the pipeline must
    accept it and spend NOTHING."""
    from core import pipeline as pipeline_mod
    rows = [_row(1, **{"Found Email": "real@firm.co.uk"})]
    out = runner.prepare(_camp(), rows, NORTHWIND_MAP)
    spent = []

    def verify(email):
        spent.append(email)
        return {"accepted": False, "verification": "bad", "tier": "fail"}

    cfg = {"use_endole": True, "verify_endole_with_mf": False, "use_patterns": True,
           "use_icebreaker": False}
    res = pipeline_mod.process_firm(out["firms"][0], cfg, verify, lambda *a, **k: None)
    assert res["status"] == "email_found", res
    assert res["found_email"] == "real@firm.co.uk", res
    assert res["email_source"] == "endole", res
    assert spent == [], f"it verified anyway and spent money: {spent}"


def check_label_source_row_merges_raw_and_result():
    firm = {"_raw": {"Intent": "capacity", "Company Name": "Old"}, "company": "New",
            "found_email": "a@b.com"}
    m = runner.label_source_row(firm)
    assert m["Intent"] == "capacity"        # only in the sheet row
    assert m["company"] == "New"            # from the result
    assert "_raw" not in m


def check_push_options_never_leak_the_campaign_id():
    c = _camp(instantly={"campaign_id": "X", "blocklist_id": "bl-1",
                         "skip_if_in_list": True})
    o = runner.push_options(c)
    assert "campaign_id" not in o, o
    assert o == {"blocklist_id": "bl-1", "skip_if_in_list": True}, o


def check_a_lane_reads_icebreaker_studios_line_from_the_sheet():
    firm = {"_raw": _row(1, **{"Ice Breaker": "  saw your new Leeds office  "}), "company": "Firm 1"}
    assert runner.sheet_icebreaker(firm, NORTHWIND_MAP) == "saw your new Leeds office"
    assert runner.sheet_icebreaker({"_raw": _row(2)}, NORTHWIND_MAP) == ""


def check_a_push_uses_the_line_the_sheet_holds_now():
    # the run saw no line; Studio wrote one afterwards; the push must send Studio's
    results = [{"row_key": "P-1", "company": "Firm 1", "icebreaker": ""},
               {"row_key": "P-2", "company": "Firm 2", "icebreaker": "old line"},
               {"row_key": "P-9", "company": "Gone", "icebreaker": "kept"}]
    sheet_now = [_row(1, **{"Ice Breaker": "written later by Studio"}), _row(2)]
    out = runner.refresh_icebreakers(results, sheet_now, NORTHWIND_MAP)
    assert out[0]["icebreaker"] == "written later by Studio" and out[0]["ice_style"] == "studio"
    assert out[1]["icebreaker"] == "", "the sheet's current (empty) line wins over the run's"
    assert out[2]["icebreaker"] == "kept", "a lead no longer on the sheet keeps the run's line"
    ready, waiting = runner.split_by_icebreaker(out)
    assert [r["company"] for r in ready] == ["Firm 1", "Gone"]
    assert [r["company"] for r in waiting] == ["Firm 2"]


def check_loading_the_shipped_config_gives_maps_and_lanes():
    # Checks YOUR live config/campaigns.json (gitignored). A fresh clone has none.
    if not (Path(__file__).parent / "config" / "campaigns.json").exists():
        print("  skipped: no live config/campaigns.json (copy campaigns.example.json to make one)")
        return
    loaded = runner.load_config_dir(Path(__file__).parent / "config")
    # 4 old NORTHWIND Leads lanes + the 5 Companies House trigger lanes added 2026-10-08
    # + the 9 "Organized" C-tab lanes added 2026-10-13. A count, not a list, so adding a
    # lane is one number here — but it IS asserted, because a lane that vanishes from the
    # shipped config is a bug, not a tidy-up.
    assert len(loaded["campaigns"]) == 18, len(loaded["campaigns"])
    assert "fieldmap.northwind.json" in loaded["fieldmaps"], loaded["fieldmaps"].keys()
    # the Organized sheet is a THIRD document, so it brings its own map and its own URL
    assert "fieldmap.northwind-organized.json" in loaded["fieldmaps"], loaded["fieldmaps"].keys()
    org = next(c for c in loaded["campaigns"] if c.id == "northwind-p1-c1-hiring")
    assert org.sheet_url, org.sheet_url
    assert next(c for c in loaded["campaigns"] if c.id == "ch-hiring-linkedin").sheet_url == ""
    fm = loaded["fieldmaps"]["fieldmap.northwind.json"]
    assert fm.header("row_key") == "lead_id"
    assert fm.header("seniority_rank") == "seniority_label"
    # the CH tabs are a different sheet with different headers — one map cannot cover both
    assert "fieldmap.ch-tabs.json" in loaded["fieldmaps"], loaded["fieldmaps"].keys()
    ch = loaded["fieldmaps"]["fieldmap.ch-tabs.json"]
    assert ch.header("row_key") == "lead_id"
    assert ch.header("seniority_rank") == "Seniority"
    assert ch.header("found_email") == "Found Email"


CHECKS = [check_headers_are_read_from_the_rows, check_a_bad_map_blocks_the_run_before_it_spends,
          check_prepare_selects_caps_and_labels, check_the_ledger_removes_leads_already_done,
          check_the_daily_limit_caps_the_second_run_of_the_day,
          check_the_sheets_own_seniority_beats_our_title_guess,
          check_an_email_already_on_the_row_reaches_the_pipeline,
          check_the_existing_email_is_used_before_any_guessing,
          check_label_source_row_merges_raw_and_result,
          check_push_options_never_leak_the_campaign_id,
          check_a_lane_reads_icebreaker_studios_line_from_the_sheet,
          check_a_push_uses_the_line_the_sheet_holds_now,
          check_loading_the_shipped_config_gives_maps_and_lanes]


def test_existing_email_reaches_pipeline(): check_an_email_already_on_the_row_reaches_the_pipeline()
def test_existing_email_used_first(): check_the_existing_email_is_used_before_any_guessing()


def test_headers(): check_headers_are_read_from_the_rows()
def test_badmap(): check_a_bad_map_blocks_the_run_before_it_spends()
def test_prepare(): check_prepare_selects_caps_and_labels()
def test_ledger(): check_the_ledger_removes_leads_already_done()
def test_daily(): check_the_daily_limit_caps_the_second_run_of_the_day()
def test_seniority(): check_the_sheets_own_seniority_beats_our_title_guess()
def test_labelrow(): check_label_source_row_merges_raw_and_result()
def test_options(): check_push_options_never_leak_the_campaign_id()
def test_config(): check_loading_the_shipped_config_gives_maps_and_lanes()


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
