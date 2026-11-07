"""
eval_instantly.py - offline test for the Instantly payload + push (no network, no keys).
    python eval_instantly.py   /   pytest eval_instantly.py
Nothing is ever sent: the push uses the no-spend stub transport.
"""
from __future__ import annotations

import sys

from core import instantly

CAMPAIGN = "00000000-1111-2222-3333-444444444444"
ROW = {
    "company": "Smith & Co", "selected_director": "ian hamish smith",
    "found_email": "ian.smith@smithco.co.uk", "email_source": "pattern_first.last",
    "domain": "smithco.co.uk", "phone": "020 7946 0001", "city": "London",
    "icebreaker": '  "know you guys are crushing it at Smith & Co,\nso this is a bit out of the blue."  ',
}


def check_clean_icebreaker():
    c = instantly.clean_icebreaker(ROW["icebreaker"])
    assert not c.startswith('"') and '"' not in c, c
    assert "\n" not in c and "  " not in c, repr(c)
    assert c.endswith("out of the blue."), c            # NOT truncated
    assert c.startswith("know you guys"), c


def check_display_name():
    n = instantly.split_display_name("ian hamish smith")
    assert n == {"first": "Ian", "last": "Smith", "full": "Ian Smith"}, n
    assert instantly.split_display_name("madonna")["last"] == ""
    assert instantly.split_display_name("")["full"] == ""


def check_payload_shape():
    p = instantly.build_payload(ROW, CAMPAIGN)
    assert p["campaign"] == CAMPAIGN
    assert p["email"] == "ian.smith@smithco.co.uk"
    assert p["first_name"] == "Ian" and p["last_name"] == "Smith"
    assert p["company_name"] == "Smith & Co"
    assert p["website"] == "smithco.co.uk"
    assert p["personalization"].startswith("know you guys")
    # V7's exact skip flags
    assert p["skip_if_in_workspace"] is False
    assert p["skip_if_in_campaign"] is False
    assert p["skip_if_in_list"] is True
    # Address, as V7 sent it, plus the five decision-agent labels. A row with no
    # labels must still send a value for every one of them: the agent counts
    # 'unlabelled' as a real group but a blank silently vanishes from every GROUP BY.
    assert p["custom_variables"] == {
        "Address": "London",
        "trigger_family": "V0_volume",
        "evidence_source": "unlabelled",
        "evidence_strength": "unlabelled",
        "contact_source": "unlabelled",
        "verify_status": "unlabelled",
        "seniority_tier": "unknown",
        "size_band": "unknown",
    }, p["custom_variables"]


def check_labels_travel_to_instantly():
    """The five labels + lead_id + campaign must reach Instantly, or the decision
    agent cannot tell a working trigger from a working list."""
    row = dict(ROW, trigger_family="A1_hiring", evidence_source="beacon",
               evidence_strength="strong", contact_source="pattern_mv",
               verify_status="valid", lead_id="P-abc1234567",
               campaign="Northwind-P2-find-email")
    cv = instantly.build_payload(row, CAMPAIGN)["custom_variables"]
    assert cv["trigger_family"] == "A1_hiring", cv
    assert cv["evidence_source"] == "beacon", cv
    assert cv["evidence_strength"] == "strong", cv
    assert cv["contact_source"] == "pattern_mv", cv
    assert cv["verify_status"] == "valid", cv
    assert cv["lead_id"] == "P-abc1234567", cv
    assert cv["campaign"] == "Northwind-P2-find-email", cv


def check_derived_labels():
    """seniority_tier and size_band are DERIVED at push time, never stored as sheet
    columns, so the same fact is not written twice."""
    r = dict(ROW, seniority_label="leadership", Employees="6")
    cv = instantly.build_payload(r, CAMPAIGN)["custom_variables"]
    assert cv["seniority_tier"] == "owner", cv
    assert cv["size_band"] == "micro_1_10", cv
    r = dict(ROW, seniority_label="statutory_director", Employees="35")
    cv = instantly.build_payload(r, CAMPAIGN)["custom_variables"]
    assert cv["seniority_tier"] == "partner_director", cv
    assert cv["size_band"] == "small_11_plus", cv
    assert instantly.size_band("") == "unknown"
    assert instantly.seniority_tier("do_not_contact") == "other"


def check_contact_name_is_read():
    """The sheet renamed Selected Director -> Contact Name. If this ever stops working
    every push loses the greeting name."""
    r = {k: v for k, v in ROW.items() if k != "selected_director"}
    r["Contact Name"] = "ian hamish smith"
    p = instantly.build_payload(r, CAMPAIGN)
    assert p["first_name"] == "Ian" and p["last_name"] == "Smith", p


def check_recipe_row_greets_the_winner():
    """Found on C1, 2026-10-13: the field map points contact_name at contact 1, so a lead
    found for contact 3 was greeted with contact 1's name. A recipe row carries the winner
    in contact_name, and wins over the map; a legacy row (no found_for) is untouched."""
    from core.fieldmap import FieldMap
    fm = FieldMap({"contact_name": "contact_1_name"})
    base = {**ROW, "contact_1_name": "Mark Robert"}
    rec = {**base, "found_for": "Mr. Richard Howarth (enriched contact 3)",
           "contact_name": "Mr. Richard Howarth"}
    p = instantly.build_payload(rec, CAMPAIGN, fm=fm)
    assert (p["first_name"], p["last_name"]) == ("Richard", "Howarth"), p
    p = instantly.build_payload({**base, "contact_name": "Richard Howarth"}, CAMPAIGN, fm=fm)
    assert p["first_name"] == "Mark", p                  # legacy row: the map still decides
    p = instantly.build_payload({**base, "found_for": "as-is contact 1", "contact_name": ""},
                                CAMPAIGN, fm=fm)
    assert p["first_name"] == "Mark", p                  # no winner name: old fallback


def check_pushed_status():
    assert instantly.pushed_status("pattern_first.last") == "pushed_to_instantly_pattern_first.last"
    assert instantly.pushed_status("") == "pushed_to_instantly_selected"


def check_push_test_mode():
    r = instantly.push_lead(ROW, CAMPAIGN, test_mode=True)
    assert r["ok"] and r["response"].get("simulated") is True, r
    assert r["status"] == "pushed_to_instantly_pattern_first.last", r


def check_push_needs_email_and_campaign():
    assert instantly.push_lead({**ROW, "found_email": ""}, CAMPAIGN, test_mode=True)["skipped"] is True
    assert instantly.push_lead(ROW, "", test_mode=True)["ok"] is False      # no campaign id


def check_push_error_is_non_fatal():
    def boom(payload, key, timeout=30):
        raise RuntimeError("instantly down")
    r = instantly.push_lead(ROW, CAMPAIGN, "k", transport=boom)
    assert r["ok"] is False and "instantly down" in r["error"]


CHECKS = [check_clean_icebreaker, check_display_name, check_payload_shape,
          check_labels_travel_to_instantly, check_derived_labels,
          check_contact_name_is_read, check_recipe_row_greets_the_winner, check_pushed_status,
          check_push_test_mode, check_push_needs_email_and_campaign, check_push_error_is_non_fatal]

def test_clean(): check_clean_icebreaker()
def test_name(): check_display_name()
def test_payload(): check_payload_shape()
def test_labels(): check_labels_travel_to_instantly()
def test_derived(): check_derived_labels()
def test_contact_name(): check_contact_name_is_read()
def test_status(): check_pushed_status()
def test_push(): check_push_test_mode()
def test_guards(): check_push_needs_email_and_campaign()
def test_error(): check_push_error_is_non_fatal()


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
