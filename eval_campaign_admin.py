"""
eval_campaign_admin.py - offline test for adding, copying and removing campaign lanes.
    python eval_campaign_admin.py   /   pytest eval_campaign_admin.py

Pure functions only (core/campaigns.py): nothing here reads or writes config/campaigns.json.
"""
from __future__ import annotations

import sys

from core import campaigns as C

LIVE = {
    "id": "northwind-size-micro", "name": "Practices 2-10 staff", "enabled": True, "priority": 10,
    "tab": "Practices", "fieldmap": "fieldmap.northwind.json", "auto_push": True,
    "note": "about this lane",
    "limits": {"per_run": 5, "per_day": 0, "max_spend_usd": 0.25},
    "rules": {"all": [{"field": "employees", "op": "between", "value": [2, 10]}]},
    "order": [{"field": "seniority_rank", "dir": "asc"}],
    "labels": [{"send_as": "size", "type": "fixed", "value": "micro"}],
    "instantly": {"campaign_id": "dcc4072c", "blocklist_id": "bl-1", "list_id": "ls-1",
                  "skip_if_in_workspace": True},
    "writeback": {"enabled": True, "campaign_type": "northwind-size-micro"},
}
OTHER = {"id": "northwind-sen-owner", "name": "Owners", "priority": 20, "tab": "Practices"}


def check_slug_is_plain_and_stable():
    assert C.slug("Owners — London 2") == "owners-london-2"
    assert C.slug("  ") == ""


def check_a_new_lane_starts_off_and_last():
    row, probs = C.new_campaign([LIVE, OTHER], name="New lane", tab="Practices")
    assert not probs, probs
    assert row["id"] == "new-lane"
    assert row["enabled"] is False and row["auto_push"] is False
    assert row["priority"] == 30, "must be checked after every existing lane"
    assert row["limits"]["per_run"] > 0
    assert row["writeback"]["campaign_type"] == "new-lane"


def check_a_new_lane_validates():
    row, _ = C.new_campaign([LIVE], name="New lane", tab="Practices")
    assert C.validate([C.Campaign(LIVE), C.Campaign(row)]) == []


def check_a_copy_keeps_the_logic_but_not_the_target():
    row, probs = C.new_campaign([LIVE, OTHER], name="Micro copy", tab="", copy_from=LIVE)
    assert not probs, probs
    assert row["rules"] == LIVE["rules"] and row["order"] == LIVE["order"]
    assert row["labels"] == LIVE["labels"] and row["limits"] == LIVE["limits"]
    assert row["tab"] == "Practices" and row["fieldmap"] == "fieldmap.northwind.json"
    assert "campaign_id" not in row["instantly"], "two lanes on one Instantly campaign are refused"
    assert row["instantly"]["blocklist_id"] == "bl-1", "the suppression gate is shared on purpose"
    assert row["enabled"] is False and row["auto_push"] is False, "a copy is a draft"
    assert row["writeback"]["campaign_type"] == "micro-copy"
    assert "note" not in row
    assert LIVE["instantly"]["campaign_id"] == "dcc4072c", "the source must not be touched"
    assert C.validate([C.Campaign(LIVE), C.Campaign(row)]) == []


def check_bad_input_is_refused_with_a_reason():
    _, probs = C.new_campaign([LIVE], name="", tab="Practices")
    assert any("name" in p for p in probs)
    _, probs = C.new_campaign([LIVE], name="x", cid="Bad Id!", tab="Practices")
    assert any("id must be" in p for p in probs)
    _, probs = C.new_campaign([LIVE], name="Clash", cid="northwind-size-micro", tab="Practices")
    assert any("already" in p for p in probs)
    _, probs = C.new_campaign([LIVE], name="No tab")
    assert any("tab" in p for p in probs)


def check_remove_takes_only_that_lane():
    rows, problem = C.remove_campaign([LIVE, OTHER], "northwind-sen-owner")
    assert not problem and [r["id"] for r in rows] == ["northwind-size-micro"]
    rows, problem = C.remove_campaign([LIVE], "nope")
    assert problem and rows == [LIVE]


CHECKS = [
    check_slug_is_plain_and_stable,
    check_a_new_lane_starts_off_and_last,
    check_a_new_lane_validates,
    check_a_copy_keeps_the_logic_but_not_the_target,
    check_bad_input_is_refused_with_a_reason,
    check_remove_takes_only_that_lane,
]


def test_slug(): check_slug_is_plain_and_stable()
def test_new(): check_a_new_lane_starts_off_and_last()
def test_new_valid(): check_a_new_lane_validates()
def test_copy(): check_a_copy_keeps_the_logic_but_not_the_target()
def test_refused(): check_bad_input_is_refused_with_a_reason()
def test_remove(): check_remove_takes_only_that_lane()


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
