"""
eval_cost.py - offline test for the savings math.
    python eval_cost.py   /   pytest eval_cost.py
"""
from __future__ import annotations

import sys

from core.cost import summarize, summarize_results


def check_savings_with_rate():
    s = summarize(firms_total=100, emails_found=70, verifications_used=180,
                  apollo_credit_usd=0.50, mv_per_verification_usd=0.0005)
    assert s["credits_avoided"] == 70
    assert s["apollo_cost_usd"] == 35.00, s["apollo_cost_usd"]
    assert s["mv_cost_usd"] == 0.09, s["mv_cost_usd"]          # 180 * 0.0005
    assert s["savings_usd"] == 34.91, s["savings_usd"]
    assert s["apollo_rate_known"] is True
    assert s["verifications_per_found"] == round(180 / 70, 2)


def check_unknown_rate_shows_credits():
    s = summarize(firms_total=100, emails_found=70, verifications_used=180)  # apollo rate unknown
    assert s["apollo_rate_known"] is False
    assert s["savings_usd"] is None and s["apollo_cost_usd"] is None
    assert s["credits_avoided"] == 70
    assert "kept 70 Apollo credits" in s["headline"]


def check_zero_found_no_div_error():
    s = summarize(firms_total=5, emails_found=0, verifications_used=12, apollo_credit_usd=0.4)
    assert s["cost_per_found_usd"] == 0.0 and s["verifications_per_found"] == 0.0
    assert s["mv_cost_usd"] == round(12 * 0.0005, 4)


def check_summarize_results():
    results = [
        {"found_email": "a@x.com", "verifications_used": 2},
        {"found_email": "", "verifications_used": 3},          # not found
        {"found_email": "c@z.com", "verifications_used": 1},
    ]
    s = summarize_results(results, apollo_credit_usd=1.0)
    assert s["firms_total"] == 3 and s["emails_found"] == 2
    assert s["verifications_used"] == 6
    assert s["apollo_cost_usd"] == 2.00 and s["savings_usd"] == round(2.0 - 6 * 0.0005, 2)


CHECKS = [check_savings_with_rate, check_unknown_rate_shows_credits,
          check_zero_found_no_div_error, check_summarize_results]

def test_savings(): check_savings_with_rate()
def test_unknown(): check_unknown_rate_shows_credits()
def test_zero(): check_zero_found_no_div_error()
def test_results(): check_summarize_results()


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
