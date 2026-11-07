"""
eval_gateway.py - offline test for the Security Gateway Guard (matches V7).
    python eval_gateway.py   /   pytest eval_gateway.py
"""
from __future__ import annotations

import sys

from core.gateway import guard


def check_blocks_aggressive():
    for p in ["mimecast", "Proofpoint Essentials", "pphosted.com", "MXLogic", "messagelabs", "mailcontrol"]:
        g = guard(p)
        assert g["held"] and g["status"] == "hold_security_gateway", (p, g)


def check_lenient_pass():
    for p in ["Cisco", "Sophos", "Trend Micro", "Fortinet", "Microsoft Defender", "Google"]:
        assert guard(p)["held"] is False, p


def check_blank_or_safe_pass():
    for p in ["", "  ", "not found", "none", "N/A", "na"]:
        assert guard(p)["held"] is False, repr(p)


def check_toggle_off_never_holds():
    assert guard("mimecast", block=False)["held"] is False
    assert guard("mimecast", block=False)["blocked"] is True   # still detected, just not held


CHECKS = [check_blocks_aggressive, check_lenient_pass, check_blank_or_safe_pass, check_toggle_off_never_holds]

def test_blocks(): check_blocks_aggressive()
def test_lenient(): check_lenient_pass()
def test_blank(): check_blank_or_safe_pass()
def test_toggle(): check_toggle_off_never_holds()


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
