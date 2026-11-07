"""
eval_emailgen.py - offline test for the email-pattern generator (matches V7).
    python eval_emailgen.py   /   pytest eval_emailgen.py
No network, no keys, no cost.
"""
from __future__ import annotations

import sys

from core import emailgen
from core.emailgen import (generate, candidates_for_firm, derive_name,
                          clean_local_part, matches_generated_pattern)


def check_lean_order():
    c = generate("Ian", "Smith", "smithco.co.uk", mode="lean")
    emails = [x["email"] for x in c]
    assert emails == ["ian@smithco.co.uk", "ian.smith@smithco.co.uk", "i.smith@smithco.co.uk"], emails
    assert [x["pattern"] for x in c] == ["first", "first.last", "f.last"]


def check_plus_mode():
    c = generate("Ian", "Smith", "smithco.co.uk", mode="plus", middle="Hamish")
    emails = [x["email"] for x in c]
    # first, middle, first.last, f.last, firstlast, flast
    assert "hamish@smithco.co.uk" in emails
    assert "iansmith@smithco.co.uk" in emails      # firstlast
    assert "ismith@smithco.co.uk" in emails        # flast
    assert len(emails) == len(set(emails))         # deduped


def check_derive_name():
    d = derive_name("MR Ian Hamish Smith")
    assert d["first"] == "ian" and d["middle"] == "hamish" and d["last"] == "smith", d
    d2 = derive_name("Jane Doe")
    assert d2["first"] == "jane" and d2["middle"] == "" and d2["last"] == "doe"


def check_short_local_skipped():
    # single-letter first with no last: 'first' -> 'i' (len 1) is skipped
    c = generate("I", "", "x.co.uk", mode="lean")
    assert all(len(x["email"].split("@")[0]) >= 2 for x in c)


def check_clean_local():
    assert clean_local_part("John..Smith") == "john.smith"
    assert clean_local_part(".jsmith-") == "jsmith"
    assert clean_local_part("O'Brien") == "obrien"


def check_no_domain():
    assert generate("Ian", "Smith", "") == []


def check_candidates_for_firm():
    firm = {"lead_director": "MR Ian Hamish Smith", "lead_firstname": "ian",
            "lead_lastname": "smith", "lead_domain": "smithco.co.uk"}
    c = candidates_for_firm(firm, mode="lean")
    assert c[0]["email"] == "ian@smithco.co.uk"
    assert c[1]["email"] == "ian.smith@smithco.co.uk"


def check_matches_pattern():
    assert matches_generated_pattern("ian.smith@smithco.co.uk", "Ian", "Smith", "smithco.co.uk")
    assert not matches_generated_pattern("info@smithco.co.uk", "Ian", "Smith", "smithco.co.uk")
    assert not matches_generated_pattern("ian.smith@other.com", "Ian", "Smith", "smithco.co.uk")


def check_fullname_mode_never_guesses_a_bare_first_name():
    """His set for the Organized tabs: three guesses, every one first AND last.

    `first@` is dropped on purpose — on a two-partner practice john@ is as likely to be
    the other John, and it would pass the check while being the wrong person."""
    pats = emailgen.PATTERN_LIBRARY["fullname"]
    assert pats == ["first.last", "firstlast", "flast"], pats
    assert len(pats) == len(emailgen.PATTERN_LIBRARY["lean"]), "same price as lean"
    got = [c["email"] for c in emailgen.generate("Ian", "Smith", "smithco.co.uk", mode="fullname")]
    assert got == ["ian.smith@smithco.co.uk", "iansmith@smithco.co.uk",
                   "ismith@smithco.co.uk"], got
    assert not any(e.startswith("ian@") for e in got), got


def check_firstfull_leads_with_the_format_most_firms_actually_use():
    """⛔ Measured, not guessed: of 1,531 addresses the firms in his own sheet use,
    `first@` is 38.6% - more than every other guessable shape put together. It has to be
    tried FIRST, because the run stops at the first address that passes."""
    pats = emailgen.PATTERN_LIBRARY["firstfull"]
    assert pats == ["first", "first.last", "firstlast", "flast"], pats
    assert pats[0] == "first", "the 38.6% case must be the first check, not the last"
    got = [c["email"] for c in emailgen.generate("Ian", "Smith", "smithco.co.uk", mode="firstfull")]
    assert got == ["ian@smithco.co.uk", "ian.smith@smithco.co.uk",
                   "iansmith@smithco.co.uk", "ismith@smithco.co.uk"], got
    # it is a superset of the set he first asked for, so it can only find more
    assert set(emailgen.PATTERN_LIBRARY["fullname"]) < set(pats)


def check_a_title_is_stripped_from_a_spoken_name():
    assert emailgen.spoken_words("MR Sumit Agarwal") == ["Sumit", "Agarwal"]
    assert emailgen.spoken_words("Dr. Jane O'Neill") == ["Jane", "O'Neill"]   # case kept
    assert emailgen.spoken_words("Ian Smith") == ["Ian", "Smith"]
    assert emailgen.spoken_words("   ") == []
    # and it agrees with the address builder about who the person is
    assert emailgen.derive_name("MR Sumit Agarwal")["first"] == "sumit"


CHECKS = [check_lean_order, check_plus_mode, check_derive_name, check_short_local_skipped,
          check_clean_local, check_no_domain, check_candidates_for_firm, check_matches_pattern,
          check_fullname_mode_never_guesses_a_bare_first_name,
          check_firstfull_leads_with_the_format_most_firms_actually_use,
          check_a_title_is_stripped_from_a_spoken_name]

def test_firstfull(): check_firstfull_leads_with_the_format_most_firms_actually_use()
def test_fullname_mode(): check_fullname_mode_never_guesses_a_bare_first_name()
def test_spoken_words(): check_a_title_is_stripped_from_a_spoken_name()

def test_lean_order(): check_lean_order()
def test_plus_mode(): check_plus_mode()
def test_derive_name(): check_derive_name()
def test_short_local(): check_short_local_skipped()
def test_clean_local(): check_clean_local()
def test_no_domain(): check_no_domain()
def test_candidates_for_firm(): check_candidates_for_firm()
def test_matches_pattern(): check_matches_pattern()


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
