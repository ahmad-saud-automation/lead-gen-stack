"""
eval_labels.py - offline test for dynamic Instantly labels + the wider payload.
    python eval_labels.py   /   pytest eval_labels.py

V1 hard-coded five labels in a Python tuple and sent 12 of the API's 19 fields. Instantly
allows any custom-variable key as long as the value is a string, number, boolean or null
(no objects, no arrays). These checks hold that line.
"""
from __future__ import annotations

import sys

from core import instantly
from core.fieldmap import FieldMap

CAMPAIGN = "camp-123"

ROW = {"company": "Smith & Co", "found_email": "ian@smithco.co.uk",
       "contact_name": "ian smith", "domain": "smithco.co.uk", "city": "London",
       "icebreaker": "nice site", "Job Title": "Managing Partner",
       "Employees": "7", "seniority_label": "owner",
       "trigger_family": "A5_departure", "evidence_source": "companies_house",
       "Intent": "capacity", "lead_id": "P-abc"}


def check_default_labels_are_v7_exactly():
    """No label table configured must mean no change from V7's payload."""
    cv = instantly.build_payload(ROW, CAMPAIGN)["custom_variables"]
    assert cv["Address"] == "London"
    assert cv["trigger_family"] == "A5_departure"
    assert cv["evidence_source"] == "companies_house"
    assert cv["evidence_strength"] == "unlabelled"      # blank -> the fallback, never ""
    assert cv["seniority_tier"] == "owner"
    assert cv["size_band"] == "micro_1_10"
    assert cv["lead_id"] == "P-abc"
    assert "campaign" not in cv                          # omit_if_blank


def check_a_custom_table_sends_exactly_what_you_asked_for():
    specs = [{"send_as": "Intent", "type": "column", "source": "Intent", "fallback": "none"},
             {"send_as": "test_arm", "type": "fixed", "value": "size_2_10"},
             {"send_as": "size_band", "type": "derived", "source": "size_band"}]
    cv = instantly.build_custom_variables(ROW, specs)
    assert cv == {"Intent": "capacity", "test_arm": "size_2_10",
                  "size_band": "micro_1_10"}, cv


def check_a_blank_label_becomes_its_fallback_never_empty():
    """A blank vanishes out of every GROUP BY without anyone noticing; 'unlabelled' is a
    group you can actually see."""
    specs = [{"send_as": "verify_status", "type": "column", "source": "verify_status",
              "fallback": "unlabelled"}]
    assert instantly.build_custom_variables({}, specs) == {"verify_status": "unlabelled"}


def check_omit_if_blank_drops_the_key_entirely():
    specs = [{"send_as": "evidence_ref", "type": "column", "source": "evidence_ref",
              "omit_if_blank": True}]
    assert instantly.build_custom_variables({}, specs) == {}
    assert instantly.build_custom_variables({"evidence_ref": "CH-1"}, specs) == \
        {"evidence_ref": "CH-1"}


def check_a_fixed_null_is_sent_not_dropped():
    """null is a legal Instantly value and means something different from 'absent'."""
    specs = [{"send_as": "x", "type": "fixed", "value": None}]
    assert instantly.build_custom_variables({}, specs) == {"x": None}


def check_a_source_may_be_a_list_of_candidates():
    specs = [{"send_as": "Address", "type": "column", "source": ["region", "city", "City"],
              "fallback": ""}]
    assert instantly.build_custom_variables({"City": "Leeds"}, specs) == {"Address": "Leeds"}
    assert instantly.build_custom_variables({}, specs) == {"Address": ""}


def check_labels_read_through_the_field_map():
    fm = FieldMap({"seniority_rank": "My Seniority", "employees": "Headcount"})
    row = {"My Seniority": "partner", "Headcount": "30"}
    cv = instantly.build_custom_variables(row, [
        {"send_as": "seniority_tier", "type": "derived", "source": "seniority_tier"},
        {"send_as": "size_band", "type": "derived", "source": "size_band"}], fm)
    assert cv == {"seniority_tier": "partner_director", "size_band": "small_11_plus"}, cv


def check_an_object_value_is_coerced_never_sent_raw():
    """Instantly rejects objects and arrays. Sending one would fail the whole lead."""
    cv = instantly.build_custom_variables({"x": {"a": 1}},
                                          [{"send_as": "x", "type": "column", "source": "x"}])
    assert isinstance(cv["x"], str), cv


def check_validate_label_specs_catches_bad_tables():
    issues = instantly.validate_label_specs([
        {"type": "column", "source": "a"},                       # no send_as
        {"send_as": "dup", "type": "column", "source": "a"},
        {"send_as": "dup", "type": "column", "source": "b"},      # duplicate
        {"send_as": "x", "type": "banana"},                       # unknown type
        {"send_as": "y", "type": "derived", "source": "nope"},    # unknown derived
        {"send_as": "z", "type": "fixed", "value": {"nested": 1}},   # object value
        {"send_as": "w", "type": "column", "source": "a", "fallback": ["list"]},
    ])
    j = " | ".join(issues)
    assert "needs 'send_as'" in j, j
    assert "duplicate variable name" in j, j
    assert "unknown type" in j, j
    assert "unknown derived source" in j, j
    assert "rejects objects and lists" in j, j
    assert "'fallback' must be" in j, j
    assert instantly.validate_label_specs(None) == []
    assert instantly.validate_label_specs(instantly.DEFAULT_LABELS) == []


def check_job_title_is_sent():
    """A first-class Instantly field the sheet has and V1 never sent."""
    p = instantly.build_payload(ROW, CAMPAIGN)
    assert p["job_title"] == "Managing Partner", p["job_title"]
    fm = FieldMap({"job_title": "Role"})
    p2 = instantly.build_payload({**ROW, "Role": "Owner"}, CAMPAIGN, fm=fm)
    assert p2["job_title"] == "Owner", p2["job_title"]


def check_optional_api_fields_only_appear_when_configured():
    p = instantly.build_payload(ROW, CAMPAIGN)
    for f in ("list_id", "blocklist_id", "assigned_to", "verify_leads_on_import"):
        assert f not in p, f

    p = instantly.build_payload(ROW, CAMPAIGN, options={
        "blocklist_id": "bl-1", "list_id": "ls-1", "verify_leads_on_import": True,
        "skip_if_in_workspace": True})
    assert p["blocklist_id"] == "bl-1" and p["list_id"] == "ls-1"
    assert p["verify_leads_on_import"] is True
    assert p["skip_if_in_workspace"] is True
    assert p["skip_if_in_list"] is True          # V7 default still holds


def check_push_lead_carries_the_table_through():
    specs = [{"send_as": "test_arm", "type": "fixed", "value": "arm_a"}]
    r = instantly.push_lead(ROW, CAMPAIGN, test_mode=True, labels=specs,
                            options={"blocklist_id": "bl-9"})
    assert r["ok"] is True
    assert r["payload"]["custom_variables"] == {"test_arm": "arm_a"}, r["payload"]
    assert r["payload"]["blocklist_id"] == "bl-9"


CHECKS = [check_default_labels_are_v7_exactly,
          check_a_custom_table_sends_exactly_what_you_asked_for,
          check_a_blank_label_becomes_its_fallback_never_empty,
          check_omit_if_blank_drops_the_key_entirely, check_a_fixed_null_is_sent_not_dropped,
          check_a_source_may_be_a_list_of_candidates, check_labels_read_through_the_field_map,
          check_an_object_value_is_coerced_never_sent_raw,
          check_validate_label_specs_catches_bad_tables, check_job_title_is_sent,
          check_optional_api_fields_only_appear_when_configured,
          check_push_lead_carries_the_table_through]


def test_defaults(): check_default_labels_are_v7_exactly()
def test_custom(): check_a_custom_table_sends_exactly_what_you_asked_for()
def test_fallback(): check_a_blank_label_becomes_its_fallback_never_empty()
def test_omit(): check_omit_if_blank_drops_the_key_entirely()
def test_null(): check_a_fixed_null_is_sent_not_dropped()
def test_candidates(): check_a_source_may_be_a_list_of_candidates()
def test_fieldmap(): check_labels_read_through_the_field_map()
def test_coerce(): check_an_object_value_is_coerced_never_sent_raw()
def test_validate(): check_validate_label_specs_catches_bad_tables()
def test_job_title(): check_job_title_is_sent()
def test_optional(): check_optional_api_fields_only_appear_when_configured()
def test_push(): check_push_lead_carries_the_table_through()


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
