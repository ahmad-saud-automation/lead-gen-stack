"""
eval_auth.py - offline test for the login (core/auth.py).
    python eval_auth.py   /   pytest eval_auth.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core import auth as A


def check_password_round_trip():
    rec = A.make("correct horse battery")
    assert A.is_set(rec)
    assert A.verify(rec, "correct horse battery")
    assert not A.verify(rec, "correct horse batterY")
    assert not A.verify(rec, "")
    assert "correct" not in str(rec), "the password itself is never stored"


def check_session_token():
    rec = A.make("correct horse battery")
    tok = A.issue(rec, now=1000)
    assert A.valid(rec, tok, now=1001)
    assert not A.valid(rec, tok, now=1000 + A.SESSION_SECONDS + 1), "expires"
    exp, _, sig = tok.partition(".")
    assert not A.valid(rec, f"{int(exp) + 999}.{sig}", now=1001), "expiry cannot be extended"
    assert not A.valid(rec, None) and not A.valid(rec, "junk") and not A.valid(rec, "1.2")
    rec2 = A.make("correct horse battery")
    assert not A.valid(rec2, tok, now=1001), "a new password signs everyone out"
    assert not A.valid({}, tok), "no password = no session"


def check_strength_rule():
    assert A.check_strength("short")
    assert A.check_strength(" padded-password ")
    assert A.check_strength("ten chars!") == ""


def check_throttle_is_per_address():
    t = A.Throttle(limit=3, window=600)
    for _ in range(3):
        t.miss("1.1.1.1", now=100)
    assert t.blocked("1.1.1.1", now=101) > 0
    assert t.blocked("2.2.2.2", now=101) == 0, "a stranger cannot lock the owner out"
    assert t.blocked("1.1.1.1", now=701) == 0, "the window passes"
    t.miss("3.3.3.3", now=100); t.clear("3.3.3.3")
    assert t.blocked("3.3.3.3", now=101) == 0


def check_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sub" / "auth.json"
        assert A.load(p) == {} and not A.is_set(A.load(p))
        A.save(p, A.make("correct horse battery"))
        assert A.verify(A.load(p), "correct horse battery")


CHECKS = [check_password_round_trip, check_session_token, check_strength_rule,
          check_throttle_is_per_address, check_save_and_load]


def test_all():
    for c in CHECKS:
        c()


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
