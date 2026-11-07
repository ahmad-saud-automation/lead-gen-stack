"""
eval_ledger.py - offline test for the processed ledger (no network, temp file only).
    python eval_ledger.py   /   pytest eval_ledger.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core.ledger import Ledger


def _fresh() -> Ledger:
    return Ledger(Path(tempfile.mkdtemp()) / "ledger.json")


FIRMS = [{"company_key": "Alpha Ltd", "Company Name": "Alpha Ltd"},
         {"company_key": "Beta Ltd", "Company Name": "Beta Ltd"},
         {"company_key": "Gamma Ltd", "Company Name": "Gamma Ltd"}]


def check_records_and_skips():
    led = _fresh()
    led.record({"company_key": "Alpha Ltd", "company": "Alpha Ltd",
                "status": "email_found", "found_email": "a@alpha.co.uk"})
    pending, skipped = led.filter_pending(FIRMS)
    assert skipped == 1 and len(pending) == 2, (skipped, pending)
    assert pending[0]["company_key"] == "Beta Ltd"


def check_every_terminal_status_sticks():
    led = _fresh()
    for i, st in enumerate(["email_found", "email_not_found", "no_website", "hold_security_gateway"]):
        led.record({"company_key": f"C{i}", "company": f"C{i}", "status": st})
    firms = [{"company_key": f"C{i}"} for i in range(4)]
    pending, skipped = led.filter_pending(firms)
    assert skipped == 4 and pending == [], (skipped, pending)   # none get re-charged


def check_retry_not_found():
    led = _fresh()
    led.record({"company_key": "A", "status": "email_not_found"})
    led.record({"company_key": "B", "status": "no_website"})
    firms = [{"company_key": "A"}, {"company_key": "B"}]
    assert led.filter_pending(firms)[1] == 2                        # both skipped by default
    pending, skipped = led.filter_pending(firms, retry_not_found=True)
    assert [p["company_key"] for p in pending] == ["A"], pending    # only not_found comes back
    assert skipped == 1


def check_pushed_never_retried():
    led = _fresh()
    led.record({"company_key": "A", "status": "email_not_found"}, pushed=True)
    pending, _ = led.filter_pending([{"company_key": "A"}], retry_not_found=True)
    assert pending == [], "a pushed lead must never be reprocessed"


def check_persists_and_key_is_normalised():
    path = Path(tempfile.mkdtemp()) / "ledger.json"
    led = Ledger(path)
    led.record({"company_key": "  Alpha   LTD ", "status": "email_found"})
    led.save()
    again = Ledger(path)                                            # reloaded from disk
    assert again.is_done({"company_key": "alpha ltd"}), again.entries
    assert again.is_done({"Company Name": "ALPHA LTD"})


def check_stats_and_clear():
    led = _fresh()
    led.record({"company_key": "A", "status": "email_found"}, pushed=True)
    led.record({"company_key": "B", "status": "no_website"})
    s = led.stats()
    assert s["total"] == 2 and s["pushed"] == 1, s
    assert s["by_status"]["no_website"] == 1
    led.clear()
    assert led.stats()["total"] == 0


# ── V2: two stages, and a key that survives duplicate company names ──

def check_two_firms_with_the_same_name_do_not_block_each_other():
    """THE V1 BUG. The key was the company name, and the Northwind sheet has 132 duplicate
    names over 264 rows, so one firm permanently blocked a different firm."""
    led = _fresh()
    a = {"lead_id": "P-aaa", "Company Name": "Smith & Co", "status": "email_found"}
    b = {"lead_id": "P-bbb", "Company Name": "Smith & Co", "status": ""}
    led.record(a)
    assert led.is_done(a) is True
    assert led.is_done(b) is False, "a different firm with the same name must NOT be blocked"


def check_enriched_is_not_pushed():
    """THE OTHER V1 BUG. A lead that found an email but ran out of quota was marked
    terminal and never sent. Enrich and push are separate stages now."""
    led = _fresh()
    row = {"lead_id": "P-1", "company": "A", "status": "email_found",
           "found_email": "a@a.com"}
    led.record(row)
    assert led.is_done(row, stage="enrich") is True      # never re-verify: no double spend
    assert led.is_done(row, stage="push") is False       # but it is still owed a send
    pend = led.pending_push()
    assert len(pend) == 1 and pend[0]["email"] == "a@a.com", pend
    led.record_push(row)
    assert led.is_done(row, stage="push") is True
    assert led.pending_push() == []


def check_daily_counts_are_per_stage_and_per_campaign():
    led = _fresh()
    for i in range(3):
        led.record({"lead_id": f"P-{i}", "status": "email_found"}, campaign="micro")
    for i in range(2):
        led.record({"lead_id": f"Q-{i}", "status": "email_found"}, campaign="small")
    led.record_push({"lead_id": "P-0", "status": "pushed"}, campaign="micro")
    assert led.count_today("enrich") == 5
    assert led.count_today("enrich", campaign="micro") == 3
    assert led.count_today("enrich", campaign="small") == 2
    assert led.count_today("push") == 1
    assert led.count_today("push", day="1999-01-01") == 0


def check_key_prefers_lead_id_over_company_name():
    from core.ledger import key_of
    from core.fieldmap import FieldMap
    row = {"lead_id": "P-xyz", "Company Name": "Smith & Co"}
    assert key_of(row) == "p-xyz"
    fm = FieldMap({"row_key": "Reg Number"})
    assert key_of({"Reg Number": "  12345678 ", "Company Name": "X"}, fm) == "12345678"
    assert key_of({"Company Name": "Only Name"}) == "only name"   # V1 rows still work
    assert key_of({}) == ""


def check_a_v1_json_ledger_is_migrated_not_lost():
    import json
    from pathlib import Path
    import tempfile
    from core.ledger import Ledger
    d = Path(tempfile.mkdtemp())
    old = d / "ledger.json"
    old.write_text(json.dumps({
        "alpha ltd": {"company": "Alpha Ltd", "status": "email_found",
                      "email": "a@alpha.co.uk", "pushed": True},
        "beta ltd": {"company": "Beta Ltd", "status": "email_not_found", "pushed": False},
    }), encoding="utf-8")
    led = Ledger(old)                                  # .json path -> .db, migrate once
    assert led.path.suffix == ".db", led.path
    assert led.is_done({"row_key": "alpha ltd"}, stage="push") is True
    assert led.is_done({"row_key": "beta ltd"}, stage="enrich") is True
    assert not old.exists() and (d / "ledger.json.migrated").exists()


def check_a_test_run_records_nothing():
    """Found while driving the UI: a test-mode run was writing its SIMULATED results into
    the ledger, which would have skipped 50 real firms forever behind an address nobody
    ever checked. The guard lives here so no call site can forget it."""
    led = _fresh()
    row = {"lead_id": "P-1", "company": "A", "status": "email_found", "found_email": "a@a.com"}
    assert led.record(row, test_mode=True) == ""
    assert led.record(row, pushed=True, test_mode=True) == ""
    assert led.is_done(row, stage="enrich") is False
    assert led.is_done(row, stage="push") is False
    assert led.stats()["total"] == 0
    led.record(row)                                    # a real run still records
    assert led.is_done(row, stage="enrich") is True


def check_clear_can_target_one_stage():
    led = _fresh()
    row = {"lead_id": "P-1", "status": "email_found"}
    led.record(row, pushed=True)
    assert led.is_done(row, stage="push") is True
    led.clear(stage="push")
    assert led.is_done(row, stage="push") is False
    assert led.is_done(row, stage="enrich") is True     # enrichment untouched


CHECKS = [check_records_and_skips, check_every_terminal_status_sticks, check_retry_not_found,
          check_pushed_never_retried, check_persists_and_key_is_normalised, check_stats_and_clear,
          check_two_firms_with_the_same_name_do_not_block_each_other,
          check_enriched_is_not_pushed, check_daily_counts_are_per_stage_and_per_campaign,
          check_key_prefers_lead_id_over_company_name,
          check_a_v1_json_ledger_is_migrated_not_lost, check_a_test_run_records_nothing,
          check_clear_can_target_one_stage]


def test_test_mode_records_nothing(): check_a_test_run_records_nothing()


def test_same_name(): check_two_firms_with_the_same_name_do_not_block_each_other()
def test_stages(): check_enriched_is_not_pushed()
def test_daily(): check_daily_counts_are_per_stage_and_per_campaign()
def test_key(): check_key_prefers_lead_id_over_company_name()
def test_migrate(): check_a_v1_json_ledger_is_migrated_not_lost()
def test_clear_stage(): check_clear_can_target_one_stage()

def test_records(): check_records_and_skips()
def test_terminal(): check_every_terminal_status_sticks()
def test_retry(): check_retry_not_found()
def test_pushed(): check_pushed_never_retried()
def test_persist(): check_persists_and_key_is_normalised()
def test_stats(): check_stats_and_clear()


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
