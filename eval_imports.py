"""
eval_imports.py - offline test for CSV import (core/imports.py).
    python eval_imports.py   /   pytest eval_imports.py

Writes only to a temp folder; never touches data/.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core import imports as I
from core import ledger as ledger_mod

CSV = (b"\xef\xbb\xbfCompany Name,Website,Contact Name,Ice Breaker\n"
       b"Smith & Co,https://smithco.co.uk,Ian Smith,Saw your new office\n"
       b"Jones Ltd,jones.co.uk,Ann Jones,\n"
       b"Smith & Co,smithco.co.uk,Bob Smith,\n"          # same firm again
       b"Owned Firm,owned.com,Me Myself,\n"              # on the suppression list
       b",nobody.com,No Company,\n"                      # no firm name
       b",,,\n")                                         # fully blank: skipped


def check_slug_is_plain_and_unique():
    assert I.slug_for("Leads — London (2).csv", []) == "leads-london-2"
    assert I.slug_for("a.csv", ["a"]) == "a-2"
    assert I.slug_for("a.csv", ["a", "a-2"]) == "a-3"
    assert I.slug_for(".csv", []) == "import"


def check_parse_drops_blank_rows_and_bom():
    heads, rows = I.parse_csv(CSV)
    assert heads[0] == "Company Name", heads
    assert len(rows) == 5, len(rows)


def check_status_column_is_added_only_when_missing():
    heads, rows = I.parse_csv(CSV)
    h2, r2, added = I.with_status(heads, rows)
    assert added and h2[-1] == "Status" and all(r["Status"] == "" for r in r2)
    h3, _r3, added2 = I.with_status(h2, r2)
    assert not added2 and h3 == h2


def check_stats_count_what_a_lane_would_skip():
    _h, rows = I.parse_csv(CSV)
    with tempfile.TemporaryDirectory() as d:
        led = ledger_mod.Ledger(Path(d) / "ledger.db")
        led.record({"row_key": "Jones Ltd", "company": "Jones Ltd", "status": "email_found",
                    "found_email": "ann@jones.co.uk"})
        st = I.stats(rows, owned_companies=["Owned Firm"], ledger=led)
        led.close()
    assert st["rows"] == 5
    assert st["duplicates"] == 1, st
    assert st["suppressed"] == 1, st
    assert st["no_company"] == 1, st
    assert st["in_ledger"] == 1, st
    assert st["with_icebreaker"] == 1 and st["has_icebreaker_column"], st


def check_upload_registers_a_tab_and_remove_unregisters():
    with tempfile.TemporaryDirectory() as d:
        rec = I.save_upload(d, "My Leads.csv", CSV)
        assert rec["tab"] == "import:my-leads" and rec["rows"] == 5 and rec["status_added"]
        p = I.path_for(d, rec["tab"])
        assert p is not None and p.exists()
        heads, rows = I.parse_csv(p.read_bytes())
        assert "Status" in heads and len(rows) == 5
        rec2 = I.save_upload(d, "My Leads.csv", CSV)
        assert rec2["slug"] == "my-leads-2", "a second upload of the same name must not overwrite"
        assert I.path_for(d, "Practices") is None, "a sheet tab is never an import"
        assert I.remove(d, "my-leads")["name"] == "My Leads.csv"
        assert I.path_for(d, "import:my-leads") is None
        assert p.exists(), "removing keeps the file unless asked"
        I.remove(d, "my-leads-2", delete_file=True)
        assert not (Path(d) / "my-leads-2.csv").exists()
        assert I.remove(d, "nope") is None


def check_bad_files_are_refused_with_a_reason():
    with tempfile.TemporaryDirectory() as d:
        for name, raw, why in (("x.xlsx", CSV, ".csv"), ("x.csv", b"", "header"),
                               ("x.csv", b"Company Name\n", "no data")):
            try:
                I.save_upload(d, name, raw)
            except ValueError as e:
                assert why in str(e), (name, str(e))
            else:
                raise AssertionError(f"{name} {raw[:20]!r} should be refused")


CHECKS = [
    check_slug_is_plain_and_unique,
    check_parse_drops_blank_rows_and_bom,
    check_status_column_is_added_only_when_missing,
    check_stats_count_what_a_lane_would_skip,
    check_upload_registers_a_tab_and_remove_unregisters,
    check_bad_files_are_refused_with_a_reason,
]


def test_slug(): check_slug_is_plain_and_unique()
def test_parse(): check_parse_drops_blank_rows_and_bom()
def test_status(): check_status_column_is_added_only_when_missing()
def test_stats(): check_stats_count_what_a_lane_would_skip()
def test_upload(): check_upload_registers_a_tab_and_remove_unregisters()
def test_refused(): check_bad_files_are_refused_with_a_reason()


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
