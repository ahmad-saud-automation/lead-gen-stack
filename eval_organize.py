"""
eval_organize.py - offline test for the organize step (matches V7 rules).
    python eval_organize.py     # prints PASS/FAIL
    pytest eval_organize.py
No network, no keys, no cost.
"""
from __future__ import annotations

import sys

from core.organize import (organize, clean_domain, name_parts, split_people,
                           parse_ages, is_generic_email, is_processable)


def check_directors_sorted_oldest_first():
    rows = [{
        "Company Name": "Smith & Co",
        "Website": "https://www.smithco.co.uk/about",
        "Director Names": "MR Ian Hamish Smith, Sarah O'Brien; John Doe",
        "Director's Age": "65, 40, 52",
    }]
    r = organize(rows)
    f = r["firms"][0]
    # oldest-first: Ian(65) > John(52) > Sarah(40)
    assert f["Director 1 Name"] == "MR Ian Hamish Smith", f["Director 1 Name"]
    assert f["Director 2 Name"] == "John Doe", f["Director 2 Name"]
    assert f["Director 3 Name"] == "Sarah O'Brien", f["Director 3 Name"]
    assert f["Oldest Director Name"] == "MR Ian Hamish Smith"
    assert f["Youngest Director Name"] == "Sarah O'Brien"
    # primary (oldest) parsed, title prefix stripped, 3-word name -> first + last
    assert f["lead_firstname"] == "ian", f["lead_firstname"]
    assert f["lead_lastname"] == "smith", f["lead_lastname"]
    assert f["lead_domain"] == "smithco.co.uk", f["lead_domain"]
    assert f["total_directors_available"] == 3


def check_seniority_then_age():
    # Apollo person-rows: seniority wins; among same seniority, OLDEST wins.
    rows = [
        {"Company Name": "Vertex Ltd", "Domain": "vertex.co.uk", "Name": "Bob Young", "Title": "Owner", "Age": "45"},
        {"Company Name": "Vertex Ltd", "Domain": "vertex.co.uk", "Name": "Alice Old", "Title": "Director", "Age": "70"},
        {"Company Name": "Vertex Ltd", "Domain": "vertex.co.uk", "Name": "Carl Elder", "Title": "Owner", "Age": "60"},
    ]
    f = organize(rows)["firms"][0]
    assert f["Director 1 Name"] == "Carl Elder", f["Director 1 Name"]   # oldest Owner
    assert f["Director 2 Name"] == "Bob Young", f["Director 2 Name"]    # younger Owner
    assert f["Director 3 Name"] == "Alice Old", f["Director 3 Name"]    # Director loses to Owners
    assert f["lead_firstname"] == "carl" and f["lead_lastname"] == "elder"
    assert f["primary_title"] == "Owner"


def check_dedupe_across_rows():
    rows = [
        {"Company Name": "Orbit Ltd", "Website": "orbit.co.uk", "Director Names": "Amy Poole", "Director's Age": "50"},
        {"Company Name": "Orbit Ltd", "Website": "orbit.co.uk", "Director Names": "Amy Poole", "Director's Age": "50"},
    ]
    r = organize(rows)
    assert r["count"] == 1, r["count"]
    assert r["skipped"]["duplicate"] == 1


def check_blocked_status_skipped():
    rows = [
        {"Company Name": "Done Ltd", "Status": "pushed_to_instantly_guess", "Director Names": "X Y"},
        {"Company Name": "New Ltd", "Status": "new", "Director Names": "A B"},
        {"Company Name": "Blank Ltd", "Director Names": "C D"},
    ]
    r = organize(rows)
    names = {f["Company Name"] for f in r["firms"]}
    assert names == {"New Ltd", "Blank Ltd"}, names
    assert r["skipped"]["already_processed"] == 1


def check_suppression():
    rows = [{"Company Name": "Owned Ltd", "Website": "owned.co.uk", "Director Names": "A B"}]
    r = organize(rows, owned_companies=["owned ltd"])
    assert r["count"] == 0
    assert r["skipped"]["suppressed"] == 1
    r2 = organize(rows, owned_domains=["https://owned.co.uk/"])
    assert r2["count"] == 0 and r2["skipped"]["suppressed"] == 1


def check_no_company_skipped():
    r = organize([{"Website": "x.co.uk", "Director Names": "A B"}])
    assert r["count"] == 0 and r["skipped"]["no_company"] == 1


def check_apollo_person_row_fallback():
    # Apollo-style: person rows with a single Name field, no Director Names
    rows = [{"Company Name": "Peak Advisers", "Domain": "peak.co.uk", "Name": "Dr Jane A Clark"}]
    r = organize(rows)
    f = r["firms"][0]
    assert f["lead_firstname"] == "jane" and f["lead_lastname"] == "clark", f
    assert f["lead_domain"] == "peak.co.uk"


def check_helpers():
    assert clean_domain("https://www.X.CO.UK/page?a=1") == "x.co.uk"
    assert clean_domain("=https://foo.com") == "foo.com"
    assert split_people("A B, C D; E F") == ["A B", "C D", "E F"]
    assert parse_ages("65, 40, x, 200") == [65, 40, None]
    assert name_parts("MR John Smith")["first"] == "john"
    assert is_generic_email("info@x.com") is True
    assert is_generic_email("john.smith@x.com") is False
    assert is_processable("new") and is_processable("")
    assert not is_processable("no_website")


def check_strict_status_rule():
    # strict (default): blank/new = process, ANYTHING written = already done
    assert is_processable("") and is_processable("   ") and is_processable("new")
    for s in ["pushed_to_instantly_endole", "email_not_found", "no_website", "whatever", "done", "x"]:
        assert not is_processable(s), s
    # loose (v7): only recognised blocked statuses are skipped
    assert is_processable("whatever", strict=False)
    assert not is_processable("no_website", strict=False)
    # organize honours it - a row with an unrecognised status is skipped in strict mode
    rows = [{"Company Name": "A Ltd", "Website": "a.co.uk", "Director Names": "X Y", "Status": "whatever"}]
    assert organize(rows)["count"] == 0, "strict mode should skip any non-blank status"
    assert organize(rows, strict_status=False)["count"] == 1


CHECKS = [check_directors_sorted_oldest_first, check_seniority_then_age,
          check_dedupe_across_rows, check_blocked_status_skipped, check_suppression,
          check_no_company_skipped, check_apollo_person_row_fallback,
          check_strict_status_rule, check_helpers]

def test_directors_sorted(): check_directors_sorted_oldest_first()
def test_seniority(): check_seniority_then_age()
def test_dedupe(): check_dedupe_across_rows()
def test_blocked(): check_blocked_status_skipped()
def test_suppression(): check_suppression()
def test_no_company(): check_no_company_skipped()
def test_apollo_fallback(): check_apollo_person_row_fallback()
def test_strict_status(): check_strict_status_rule()
def test_helpers(): check_helpers()


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
