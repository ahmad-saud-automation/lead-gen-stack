"""
eval_retry.py - offline test for retry/backoff (no network, no real sleeping).
    python eval_retry.py   /   pytest eval_retry.py
"""
from __future__ import annotations

import sys
import urllib.error

from core import retry as R
from core import verify as verify_mod


def _http_error(code, headers=None):
    # `headers or {}` would drop an empty-but-meaningful header object - the exact
    # falsy-collection trap this module guards against.
    return urllib.error.HTTPError("http://x", code, "err",
                                  {} if headers is None else headers, None)


def check_transient_classification():
    for code in (408, 429, 500, 502, 503, 504):
        assert R.is_transient(_http_error(code)), code
    for code in (400, 401, 403, 404, 422):
        assert not R.is_transient(_http_error(code)), code      # our bug, not theirs
    assert R.is_transient(urllib.error.URLError("dns"))
    assert R.is_transient(TimeoutError())


def check_retries_then_succeeds():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return "ok"
    assert R.call(flaky, tries=3, wait=0) == "ok"
    assert calls["n"] == 3


def check_gives_up_after_tries():
    calls = {"n": 0}
    def always():
        calls["n"] += 1
        raise _http_error(503)
    try:
        R.call(always, tries=3, wait=0)
    except urllib.error.HTTPError:
        assert calls["n"] == 3, calls
        return
    raise AssertionError("should have raised after exhausting tries")


def check_permanent_error_not_retried():
    calls = {"n": 0}
    def bad_key():
        calls["n"] += 1
        raise _http_error(401)
    try:
        R.call(bad_key, tries=3, wait=0)
    except urllib.error.HTTPError:
        assert calls["n"] == 1, "a bad key must fail immediately, not retry 3x"
        return
    raise AssertionError("should have raised")


def check_retry_after_header_honoured():
    class H(dict):
        def get(self, k, d=None): return "7" if k == "Retry-After" else d
    assert R.retry_after_seconds(_http_error(429, H())) == 7.0
    assert R.retry_after_seconds(_http_error(500)) is None


def check_on_retry_callback():
    seen = []
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(500)
        return 1
    R.call(flaky, tries=3, wait=0, on_retry=lambda a, n, e, p: seen.append((a, n)))
    assert seen == [(1, 3)], seen


def check_verify_retries_and_recovers():
    calls = {"n": 0}
    def flaky(email, key, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return {"email": email, "result": "ok"}
    v = verify_mod.verify_email("a.b@x.com", "k", transport=flaky, tries=3, retry_wait=0)
    assert v["accepted"] and calls["n"] == 3, (v, calls)


def check_verify_test_mode_never_retries():
    calls = {"n": 0}
    def boom(email, key, timeout):
        calls["n"] += 1
        raise _http_error(500)
    v = verify_mod.verify_email("a.b@x.com", "", transport=boom, test_mode=True, tries=5, retry_wait=0)
    assert v["tier"] == "error" and calls["n"] == 1, calls   # the stub can't fail transiently


def check_test_mode_marks_simulated():
    v = verify_mod.verify_email("a.b@x.com", "", test_mode=True)
    assert v["accepted"] and v["simulated"] is True, v
    real = verify_mod.verify_email("a.b@x.com", "k",
                                   transport=lambda e, k, t: {"email": e, "result": "ok"})
    assert real["simulated"] is False, real


CHECKS = [check_transient_classification, check_retries_then_succeeds, check_gives_up_after_tries,
          check_permanent_error_not_retried, check_retry_after_header_honoured, check_on_retry_callback,
          check_verify_retries_and_recovers, check_verify_test_mode_never_retries,
          check_test_mode_marks_simulated]

def test_classify(): check_transient_classification()
def test_retries(): check_retries_then_succeeds()
def test_gives_up(): check_gives_up_after_tries()
def test_permanent(): check_permanent_error_not_retried()
def test_retry_after(): check_retry_after_header_honoured()
def test_callback(): check_on_retry_callback()
def test_verify_retry(): check_verify_retries_and_recovers()
def test_verify_test_mode(): check_verify_test_mode_never_retries()
def test_simulated(): check_test_mode_marks_simulated()


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
