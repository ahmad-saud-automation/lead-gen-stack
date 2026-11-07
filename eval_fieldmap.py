"""
eval_fieldmap.py - offline test for the column-name translator (no network, no keys).
    python eval_fieldmap.py   /   pytest eval_fieldmap.py
"""
from __future__ import annotations

import sys

from core.fieldmap import FieldMap, suggest, REQUIRED

# the real NORTHWIND Leads header, verified against leads/google-sheet/Practices.csv 2026-09-04
NORTHWIND_HEADERS = [
    "lead_id", "campaign", "Status", "Final Status", "send_ready", "Company Name", "Website",
    "Address", "Region", "Telephone", "Employees", "Industry", "Trading Years", "Reg Number",
    "Contact Name", "First Name", "Last Name", "Job Title", "seniority_label",
    "Contact 2 Name", "Contact 2 First Name", "Contact 2 Last Name", "Contact 2 Job Title",
    "Contact 2 Email", "verify_contact_2", "Found Email", "Email Source", "Email Type",
    "Verification Status", "Alternate Emails", "mv_date", "Company Email", "Ice Breaker",
    "Campaign Type", "trigger_family", "evidence_source", "evidence_strength",
    "contact_source", "verify_status", "Intent", "evidence_ref", "fabrikam_contacted",
]

# a V7-shaped Endole sheet: none of Northwind's names, all of V1's
V7_HEADERS = ["Company Name", "Website", "Director Names", "Director's Age", "Status",
              "Telephone", "Address", "Reg Number"]

NORTHWIND_ROW = {"lead_id": "P-abc123", "Company Name": "Smith & Co", "Website": "smithco.co.uk",
           "Contact Name": "Ian Smith", "Job Title": "Owner", "seniority_label": "owner",
           "Status": "", "send_ready": "yes", "Employees": "7", "Telephone": "020 1234",
           "Ice Breaker": "", "Found Email": ""}


def check_explicit_mapping_wins():
    """A mapped header beats an alias, even when both columns exist."""
    row = {"Contact Name": "Alias Person", "Owner Name": "Mapped Person"}
    fm = FieldMap({"contact_name": "Owner Name"})
    assert fm.get(row, "contact_name") == "Mapped Person", fm.get(row, "contact_name")


def check_mapped_but_blank_stays_blank():
    """THE anti-guessing rule. If you mapped it and the cell is empty, the answer is
    empty - the engine must never quietly fall back to some other column."""
    row = {"Owner Name": "", "Contact Name": "Someone Else"}
    fm = FieldMap({"contact_name": "Owner Name"})
    assert fm.get(row, "contact_name") == "", fm.get(row, "contact_name")


def check_unmapped_falls_back_to_v1_aliases():
    """No map at all must behave exactly like V1, or every existing sheet breaks."""
    fm = FieldMap({})
    row = {"Company Name": "Acme", "Director Names": "A B", "Telephone": "0207"}
    assert fm.get(row, "company_name") == "Acme"
    assert fm.get(row, "contact_name") == "A B"
    assert fm.get(row, "phone") == "0207"


def check_suggest_matches_the_real_northwind_sheet():
    s = suggest(NORTHWIND_HEADERS)
    assert s["row_key"] == "lead_id", s.get("row_key")
    assert s["contact_name"] == "Contact Name"
    assert s["seniority_rank"] == "seniority_label"
    assert s["send_gate"] == "send_ready"
    assert s["job_title"] == "Job Title"
    assert s["icebreaker"] == "Ice Breaker"
    for f in REQUIRED:
        assert f in s, f"required field {f} not auto-matched"


def check_suggest_ignores_case_and_punctuation():
    s = suggest(["LEAD_ID", "company name", "  Status  "])
    assert s["row_key"] == "LEAD_ID", s
    assert s["company_name"] == "company name", s
    assert s["status"] == "Status", s          # header is stripped


def check_validate_flags_missing_required():
    v = FieldMap({}).validate(["Website", "Telephone"])
    assert v["ok"] is False
    assert "company_name" in v["missing_required"], v
    assert "status" in v["missing_required"], v


def check_validate_flags_a_header_that_does_not_exist():
    """The silent-discard trap: Google Sheets throws no error when you write to a column
    that is not there, it just leaves the cell blank. It has to be caught here."""
    fm = FieldMap({"row_key": "lead_id", "company_name": "Company Name",
                   "status": "Status", "icebreaker": "Icebreaker Line"})
    v = fm.validate(NORTHWIND_HEADERS)
    assert v["ok"] is False
    bad = [b["field"] for b in v["bad_targets"]]
    assert bad == ["icebreaker"], v["bad_targets"]


def check_validate_passes_on_the_real_northwind_map():
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / "config" / "fieldmap.northwind.json")
                     .read_text(encoding="utf-8"))
    v = FieldMap(raw["mapping"]).validate(NORTHWIND_HEADERS)
    assert v["ok"] is True, v
    assert v["bad_targets"] == [], v["bad_targets"]


def check_completed_fills_gaps_without_overriding():
    fm = FieldMap({"contact_name": "Contact 2 Name"}).completed(NORTHWIND_HEADERS)
    assert fm.header("contact_name") == "Contact 2 Name"   # explicit choice survives
    assert fm.header("row_key") == "lead_id"               # gap auto-filled
    assert fm.header("employees") == "Employees"


def check_resolve_reads_engine_fields_and_raw_headers():
    fm = FieldMap({"employees": "Employees"})
    row = {"Employees": "7", "trigger_family": "A5_departure"}
    assert fm.resolve(row, "employees") == "7"            # engine field
    assert fm.resolve(row, "trigger_family") == "A5_departure"   # raw header
    assert fm.resolve(row, "nope", "dflt") == "dflt"


def check_v7_sheet_still_resolves_with_no_map():
    v = FieldMap({}).validate(V7_HEADERS)
    assert v["ok"] is True, v
    assert v["resolved"]["contact_name"] == "Director Names", v["resolved"]
    assert v["resolved"]["row_key"] == "Reg Number", v["resolved"]


CHECKS = [check_explicit_mapping_wins, check_mapped_but_blank_stays_blank,
          check_unmapped_falls_back_to_v1_aliases, check_suggest_matches_the_real_northwind_sheet,
          check_suggest_ignores_case_and_punctuation, check_validate_flags_missing_required,
          check_validate_flags_a_header_that_does_not_exist,
          check_validate_passes_on_the_real_northwind_map,
          check_completed_fills_gaps_without_overriding,
          check_resolve_reads_engine_fields_and_raw_headers,
          check_v7_sheet_still_resolves_with_no_map]


def test_explicit(): check_explicit_mapping_wins()
def test_blank(): check_mapped_but_blank_stays_blank()
def test_aliases(): check_unmapped_falls_back_to_v1_aliases()
def test_suggest_northwind(): check_suggest_matches_the_real_northwind_sheet()
def test_suggest_norm(): check_suggest_ignores_case_and_punctuation()
def test_required(): check_validate_flags_missing_required()
def test_bad_target(): check_validate_flags_a_header_that_does_not_exist()
def test_northwind_map(): check_validate_passes_on_the_real_northwind_map()
def test_completed(): check_completed_fills_gaps_without_overriding()
def test_resolve(): check_resolve_reads_engine_fields_and_raw_headers()
def test_v7(): check_v7_sheet_still_resolves_with_no_map()


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
