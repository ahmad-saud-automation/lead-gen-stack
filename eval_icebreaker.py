"""
eval_icebreaker.py - offline test for the V7 icebreaker builder.
    python eval_icebreaker.py   /   pytest eval_icebreaker.py
"""
from __future__ import annotations

import sys

from core import icebreaker


def check_offer_default():
    styles = set()
    for c in ["Alpha Ltd", "Beta & Co", "Gamma LLP", "Delta Advisers", "Epsilon Tax", "Zeta Group", "Harris & Co"]:
        r = icebreaker.build({"Company Name": c})
        assert r["text"], c
        assert r["style"] in ("O1a", "O1b", "O2a", "O2b", "O3")
        if r["style"] != "O3":
            assert c in r["text"], (c, r)     # O3 is the only company-free variant
        styles.add(r["style"])
    assert len(styles) >= 2, styles           # rotation actually varies


def check_deterministic():
    a = icebreaker.build({"Company Name": "Acme", "found_email": "a.b@acme.com"})
    b = icebreaker.build({"Company Name": "Acme", "found_email": "a.b@acme.com"})
    assert a == b


def check_delivered_mode():
    r = icebreaker.build({"Company Name": "Acme", "audit_mode": "delivered",
                          "audit_opener_data": "your site is very slow to load on mobile"})
    assert r["style"] in ("D1", "D2")
    assert "slow" in r["text"] or "load" in r["text"] or "60 seconds" in r["text"]


def check_clean_mode():
    r = icebreaker.build({"Company Name": "Acme", "audit_mode": "clean", "audit_perf_score": "95"})
    assert r["style"] == "CLEAN" and "95" in r["text"]


def check_custom_templates_override():
    custom = {"O1a": "custom line for {company}", "O1b": "custom line for {company}",
              "O2a": "custom line for {company}", "O2b": "custom line for {company}",
              "O3": "custom line for {company}"}
    r = icebreaker.build({"Company Name": "Acme"}, "a@acme.com", custom)
    assert r["text"] == "custom line for Acme", r
    # defaults still apply to any key the user didn't edit
    r2 = icebreaker.build({"Company Name": "Acme", "audit_mode": "clean", "audit_perf_score": "91"},
                          "a@acme.com", {"O1a": "x {company}"})
    assert "91" in r2["text"] and r2["style"] == "CLEAN"


def check_validate_templates():
    ok = icebreaker.validate_templates(icebreaker.DEFAULT_TEMPLATES)
    assert ok == [], ok
    bad = icebreaker.validate_templates({**icebreaker.DEFAULT_TEMPLATES,
                                         "O1a": "", "O1b": "hi {nonsense}", "D1": "no placeholder here"})
    joined = " ".join(bad)
    assert "O1a: empty" in joined, bad
    assert "unknown placeholder {nonsense}" in joined, bad
    assert "D1" in joined and "{plain}" in joined, bad


def check_stray_brace_does_not_crash():
    r = icebreaker.build({"Company Name": "Acme"}, "a@acme.com",
                         {k: "50% off {company} {" for k in icebreaker.OFFER_STYLES})
    assert "Acme" in r["text"], r


CHECKS = [check_offer_default, check_deterministic, check_delivered_mode, check_clean_mode,
          check_custom_templates_override, check_validate_templates, check_stray_brace_does_not_crash]

def test_offer(): check_offer_default()
def test_deterministic(): check_deterministic()
def test_delivered(): check_delivered_mode()
def test_clean(): check_clean_mode()
def test_custom(): check_custom_templates_override()
def test_validate(): check_validate_templates()
def test_brace(): check_stray_brace_does_not_crash()


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
