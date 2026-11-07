"""
eval_pipeline.py - offline test for the Phase-1 cascade (no network, no keys, no cost).
    python eval_pipeline.py   /   pytest eval_pipeline.py
Uses a stub verifier: dotted person-patterns (first.last) verify good; bare guesses don't.
"""
from __future__ import annotations

import sys

from core import pipeline

CFG = {"use_endole": True, "verify_endole_with_mf": True, "use_patterns": True,
       "pattern_mode": "lean", "block_security_gateways": True}


def vmock(email):
    local = email.split("@")[0]
    ok = "." in local
    return {"accepted": ok, "verification": "good" if ok else "unknown",
            "tier": "pass" if ok else "catch_all"}


def _emit_collector():
    events = []
    return events, (lambda company, stage, status, detail, email="":
                    events.append({"company": company, "stage": stage, "status": status,
                                   "detail": detail, "email": email}))


def _firm(**over):
    base = {"Company Name": "Smith & Co", "company_key": "Smith & Co",
            "lead_domain": "smithco.co.uk", "lead_director": "Ian Smith",
            "lead_firstname": "ian", "lead_lastname": "smith",
            "Oldest Director Name": "Ian Smith", "is_no_website_path": False,
            "lead_endole_email": "", "endole_generic": False,
            "email_security_gateway_provider": ""}
    base.update(over)
    return base


def check_pattern_found():
    events, emit = _emit_collector()
    r = pipeline.process_firm(_firm(), CFG, vmock, emit)
    assert r["status"] == "email_found", r["status"]
    assert r["found_email"] == "ian.smith@smithco.co.uk", r["found_email"]
    assert r["email_source"] == "pattern_first.last", r["email_source"]
    assert r["verifications_used"] == 2, r["verifications_used"]      # bare failed, dotted passed
    assert any(e["stage"] == "verify" and e["status"] == "success" for e in events)


def check_no_website():
    events, emit = _emit_collector()
    r = pipeline.process_firm(_firm(lead_domain="", is_no_website_path=True), CFG, vmock, emit)
    assert r["status"] == "no_website" and r["found_email"] == ""
    assert any(e["status"] == "skip" for e in events)


def check_gateway_hold():
    events, emit = _emit_collector()
    r = pipeline.process_firm(_firm(email_security_gateway_provider="Mimecast"), CFG, vmock, emit)
    assert r["status"] == "hold_security_gateway", r["status"]
    assert r["found_email"] == "" and r["verifications_used"] == 0    # held before any spend
    assert events[0]["status"] == "held"


def check_endole_before_patterns():
    events, emit = _emit_collector()
    r = pipeline.process_firm(_firm(lead_endole_email="jane.doe@smithco.co.uk"), CFG, vmock, emit)
    assert r["status"] == "email_found" and r["email_source"] == "endole", r
    assert r["found_email"] == "jane.doe@smithco.co.uk"
    assert r["verifications_used"] == 1                               # stopped at endole, never tried patterns


def check_generic_endole_falls_through():
    events, emit = _emit_collector()
    r = pipeline.process_firm(_firm(lead_endole_email="info@smithco.co.uk", endole_generic=True), CFG, vmock, emit)
    assert r["email_source"] == "pattern_first.last", r["email_source"]   # generic skipped, pattern used
    assert any(e["stage"] == "endole" and e["status"] == "skip" for e in events)


def check_not_found():
    events, emit = _emit_collector()
    # a one-word director yields only bare-local guesses, which vmock never accepts
    r = pipeline.process_firm(_firm(lead_director="Madonna", lead_firstname="madonna", lead_lastname="",
                                    Oldest_Director_Name="Madonna"), CFG, vmock, emit)
    assert r["status"] == "email_not_found", r["status"]


def check_icypeas_fallback():
    from core import finders
    events, emit = _emit_collector()
    fi = lambda firm: finders.find_icypeas(firm, test_mode=True)
    cfg = {**CFG, "use_icypeas": True, "verify_icypeas_with_mf": False}
    # no-website lead: patterns skipped -> Icypeas finds by name+company, icebreaker built
    r = pipeline.process_firm(_firm(lead_domain="", is_no_website_path=True,
                                    lead_firstname="tom", lead_lastname="reed", lead_director="Tom Reed"),
                              cfg, vmock, emit, find_icypeas=fi)
    assert r["status"] == "email_found" and r["email_source"] == "icypeas_director", r
    assert r["found_email"].startswith("tom.reed@")
    assert r["icebreaker"], "icebreaker should be built on a hit"
    assert any(e["stage"] == "icypeas" and e["status"] == "success" for e in events)


CHECKS = [check_pattern_found, check_no_website, check_gateway_hold,
          check_endole_before_patterns, check_generic_endole_falls_through, check_not_found,
          check_icypeas_fallback]

def test_pattern(): check_pattern_found()
def test_no_website(): check_no_website()
def test_gateway(): check_gateway_hold()
def test_endole(): check_endole_before_patterns()
def test_generic(): check_generic_endole_falls_through()
def test_not_found(): check_not_found()
def test_icypeas_fallback(): check_icypeas_fallback()


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
