"""
eval_net.py - every real HTTP transport must send a User-Agent.
    python eval_net.py   /   pytest eval_net.py
No network: urlopen is swapped for a capture stub, so nothing leaves the machine.

Why this file exists: urllib's default `Python-urllib/3.x` is blocked by
Cloudflare on MillionVerifier with 403 "error code: 1010". The run doesn't
crash - every verification just returns `error`, so a perfectly good key with
47,712 credits produced three runs of 0 emails found. Cheap to reintroduce,
expensive to notice, so it gets a test.
"""
from __future__ import annotations

import sys
import urllib.request

from core import finders, instantly, net, sheets, verify


class _Captured(Exception):
    """Thrown by the stub to stop the call once we've seen the request."""

    def __init__(self, req):
        self.req = req


def _capture(monkey_target=urllib.request):
    def fake_urlopen(req, *a, **kw):
        raise _Captured(req)
    monkey_target.urlopen = fake_urlopen


def _headers_of(call) -> dict:
    real = urllib.request.urlopen
    _capture()
    try:
        call()
    except _Captured as c:
        req = c.req
        return {k.lower(): v for k, v in (req.headers or {}).items()} if hasattr(req, "headers") else {}
    finally:
        urllib.request.urlopen = real
    raise AssertionError("transport never called urlopen")


def _assert_ua(name, call):
    h = _headers_of(call)
    ua = h.get("User-agent".lower()) or h.get("user-agent", "")
    assert ua, f"{name} sent no User-Agent - Cloudflare will 403 it"
    assert not ua.lower().startswith("python-urllib"), f"{name} sent the default UA: {ua}"


def check_millionverifier_ua():
    _assert_ua("verify._http_transport", lambda: verify._http_transport("a@x.com", "key"))


def check_instantly_ua():
    _assert_ua("instantly._http_push", lambda: instantly._http_push({"email": "a@x.com"}, "key"))


def check_icypeas_ua():
    _assert_ua("finders._http_icypeas",
               lambda: finders._http_icypeas("ian", "smith", "x.com", "key", 15, 0))


def check_anymail_ua():
    _assert_ua("finders._http_anymail",
               lambda: finders._http_anymail("x.com", "Ian Smith", "X Ltd", "key", 15))


def check_sheets_ua():
    _assert_ua("sheets.read_via_csv_export", lambda: sheets.read_via_csv_export("docid"))


def check_headers_helper():
    assert net.headers()["User-Agent"] == net.USER_AGENT
    h = net.headers({"Authorization": "Bearer k"})
    assert h["Authorization"] == "Bearer k" and h["User-Agent"] == net.USER_AGENT
    # an explicit UA wins, so a caller can still override
    assert net.headers({"User-Agent": "custom"})["User-Agent"] == "custom"


CHECKS = [check_millionverifier_ua, check_instantly_ua, check_icypeas_ua,
          check_anymail_ua, check_sheets_ua, check_headers_helper]

def test_mv_ua(): check_millionverifier_ua()
def test_instantly_ua(): check_instantly_ua()
def test_icypeas_ua(): check_icypeas_ua()
def test_anymail_ua(): check_anymail_ua()
def test_sheets_ua(): check_sheets_ua()
def test_headers_helper(): check_headers_helper()


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
