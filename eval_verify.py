"""
eval_verify.py - offline test for MillionVerifier verification (matches V7 tiers).
    python eval_verify.py   /   pytest eval_verify.py
No network, no key, no cost - uses canned responses + the no-spend test transport.
"""
from __future__ import annotations

import sys

from core.verify import classify_response, verify_email, find_verified_email, test_transport
from core.emailgen import generate


def check_pass_tier():
    for r in ({"email": "a@x.com", "result": "ok"}, {"email": "a@x.com", "quality": "good"},
              {"email": "a@x.com", "result": "deliverable"}):
        v = classify_response(r)
        assert v["accepted"] and v["tier"] == "pass", (r, v)


def check_bad_tier_always_rejected():
    for r in ({"email": "a@x.com", "result": "invalid"},
              {"email": "a@x.com", "result": "disposable"},
              {"email": "a@x.com", "resultcode": "6"},
              {"email": "a@x.com", "result": "ok", "subresult": "no_mailbox"}):
        v = classify_response(r, accept_catchall=True)   # even with catch-all on
        assert not v["accepted"], (r, v)


def check_catchall_toggle():
    r = {"email": "a@x.com", "result": "catch_all"}
    assert classify_response(r, accept_catchall=False)["accepted"] is False
    v = classify_response(r, accept_catchall=True)
    assert v["accepted"] is True and v["tier"] == "catch_all"


def check_unknown_not_accepted_by_default():
    v = classify_response({"email": "a@x.com", "result": "unknown"})
    assert not v["accepted"] and v["tier"] == "catch_all"


def check_no_email_not_accepted():
    assert classify_response({"result": "ok"})["accepted"] is False


def check_find_stops_at_first_valid():
    cands = generate("Ian", "Smith", "smithco.co.uk", mode="lean")  # ian@, ian.smith@, i.smith@
    r = find_verified_email(cands, test_mode=True)
    assert r["found_email"] == "ian.smith@smithco.co.uk", r["found_email"]
    assert r["verifications_used"] == 2, r["verifications_used"]     # stopped, didn't check 3rd
    assert r["tier"] == "pass"


def check_find_none():
    # bare-first only → test transport marks 'unknown' → nothing accepted
    r = find_verified_email([{"email": "ian@x.com", "source": "guess_first"}], test_mode=True)
    assert r["found_email"] == "" and r["verification"] == "not_found"


def check_verify_email_error_path():
    def boom(email, key, timeout=10):
        raise RuntimeError("network down")
    v = verify_email("a@x.com", "k", transport=boom)
    assert v["accepted"] is False and v["tier"] == "error"


def check_test_transport_shape():
    assert test_transport("a.b@x.com")["result"] == "ok"
    assert test_transport("a@x.com")["result"] == "unknown"


CHECKS = [check_pass_tier, check_bad_tier_always_rejected, check_catchall_toggle,
          check_unknown_not_accepted_by_default, check_no_email_not_accepted,
          check_find_stops_at_first_valid, check_find_none,
          check_verify_email_error_path, check_test_transport_shape]

def test_pass(): check_pass_tier()
def test_bad(): check_bad_tier_always_rejected()
def test_catchall(): check_catchall_toggle()
def test_unknown(): check_unknown_not_accepted_by_default()
def test_no_email(): check_no_email_not_accepted()
def test_stop_first(): check_find_stops_at_first_valid()
def test_find_none(): check_find_none()
def test_error(): check_verify_email_error_path()
def test_transport_shape(): check_test_transport_shape()


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
