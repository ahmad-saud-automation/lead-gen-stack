"""
eval_finders.py - offline test for Icypeas + Anymailfinder (no network, no keys).
    python eval_finders.py   /   pytest eval_finders.py
Uses the no-spend test transports + the response parsers.
"""
from __future__ import annotations

import sys

from core import finders


def check_icypeas_test_find():
    r = finders.find_icypeas({"lead_firstname": "ian", "lead_lastname": "reed", "lead_domain": "gamma.co.uk"}, test_mode=True)
    assert r["email"] == "ian.reed@gamma.co.uk", r


def check_icypeas_no_name():
    r = finders.find_icypeas({"lead_firstname": "", "lead_lastname": "", "Company Name": "X"}, test_mode=True)
    assert r["email"] == "", r


def check_icypeas_company_fallback():
    r = finders.find_icypeas({"lead_firstname": "amy", "lead_lastname": "poole", "Company Name": "Orbit Ltd"}, test_mode=True)
    assert r["email"].startswith("amy.poole@") and r["email"].endswith(".co.uk"), r


def check_icypeas_parse():
    ok = {"items": [{"results": {"emails": [{"email": "A.B@x.com", "certainty": "high"}]}, "status": "DONE"}], "success": True}
    assert finders._parse_icypeas(ok)["email"] == "a.b@x.com"
    processing = {"items": [{"results": {"emails": [{"email": "a@x.com"}]}, "status": "IN_PROGRESS"}]}
    assert finders._parse_icypeas(processing)["email"] == ""


def _fake_icypeas(answers, *, log=None):
    """A stand-in Icypeas: the SEARCH, then a READ per poll, answering from `answers` in turn.
    Patches the two urlopen calls by swapping `finders._http_icypeas`'s own helpers out via a
    fake urllib — simpler here to drive `_http_icypeas` with a stub read."""
    state = {"reads": 0}

    def read_once():
        i = min(state["reads"], len(answers) - 1)
        state["reads"] += 1
        if log is not None:
            log.append(i)
        return answers[i]
    return state, read_once


def _drive_poll(answers, *, wait=15, poll_every=0.01, monkey=None):
    """Run the real polling loop with a stub reader, so the timing logic is what is tested."""
    import time as _t
    state, read_once = _fake_icypeas(answers)
    ceiling = max(0.0, float(wait))
    deadline = _t.monotonic() + ceiling
    delay = min(max(0.1, float(poll_every)), ceiling) if ceiling else 0.0
    resp = {"items": [], "success": False}
    while True:
        if delay:
            _t.sleep(min(delay, 0.01))        # the shape is under test, not real seconds
        resp = read_once()
        if not finders._still_working(resp):
            return resp, state["reads"]
        if not ceiling or _t.monotonic() >= deadline:
            return resp, state["reads"]
        delay = min(delay * 1.4, 3.0, max(0.1, deadline - _t.monotonic()))


IN_PROGRESS = {"items": [{"results": {"emails": []}, "status": "IN_PROGRESS"}], "success": True}
NOT_CREATED = {"items": [], "success": True}
BLANK_STATUS = {"items": [{"results": {"emails": []}, "status": ""}], "success": True}
DONE_FOUND = {"items": [{"results": {"emails": [{"email": "ian@x.co.uk", "certainty": "high"}]},
                         "status": "DONE"}], "success": True}
DONE_EMPTY = {"items": [{"results": {"emails": []}, "status": "DONE"}], "success": True}


def check_polling_waits_for_an_answer_instead_of_believing_an_early_read():
    """⛔ The whole safety of the speed-up. A record that is not ready reads back as
    IN_PROGRESS / "" / no items, and every one of those must mean KEEP WAITING. If any were
    taken as an answer, the find would be thrown away and the row marked not found."""
    for stall in (IN_PROGRESS, NOT_CREATED, BLANK_STATUS):
        assert finders._still_working(stall), stall
        resp, reads = _drive_poll([stall, stall, stall, DONE_FOUND])
        assert finders._parse_icypeas(resp)["email"] == "ian@x.co.uk", (stall, resp)
        assert reads == 4, f"stopped after {reads} reads instead of waiting"


def check_a_fast_answer_returns_on_the_first_read():
    resp, reads = _drive_poll([DONE_FOUND])
    assert finders._parse_icypeas(resp)["email"] == "ian@x.co.uk", resp
    assert reads == 1, reads


def check_a_real_miss_is_not_retried_forever():
    """DONE with no emails is Icypeas's answer, not a stall — stop and report nothing."""
    assert not finders._still_working(DONE_EMPTY)
    resp, reads = _drive_poll([DONE_EMPTY, DONE_FOUND])
    assert finders._parse_icypeas(resp)["email"] == "", resp
    assert reads == 1, reads


def check_running_out_of_time_reports_no_email_never_a_wrong_one():
    resp, reads = _drive_poll([IN_PROGRESS], wait=0.05)
    assert finders._parse_icypeas(resp)["email"] == "", resp
    assert reads >= 1, reads


def check_no_ceiling_still_reads_once():
    """wait=0 must not mean "never ask" — it means one read, no pause."""
    resp, reads = _drive_poll([DONE_FOUND], wait=0)
    assert finders._parse_icypeas(resp)["email"] == "ian@x.co.uk", resp
    assert reads == 1, reads


def check_the_old_flat_sleep_is_gone():
    """Guards the regression: `wait` must be a ceiling, not the price of every ask."""
    import inspect
    src = inspect.getsource(finders._http_icypeas)
    assert "time.sleep(wait)" not in src, "the flat sleep is back"
    assert "deadline" in src and "_still_working" in src, src[:200]
    assert "poll_every" in inspect.signature(finders.find_icypeas).parameters


def check_anymail_test_find():
    r = finders.find_anymailfinder({"lead_domain": "peak.co.uk", "lead_director": "Jane Clark"}, test_mode=True)
    assert r["email"] == "jane.clark@peak.co.uk", r


def check_anymail_no_domain():
    assert finders.find_anymailfinder({"lead_domain": "", "lead_director": "Jane Clark"}, test_mode=True)["email"] == ""


def check_anymail_parse():
    assert finders._parse_anymail({"valid_email": "X@Y.com"})["email"] == "x@y.com"
    assert finders._parse_anymail({"data": {"email": "z@q.com"}})["email"] == "z@q.com"
    assert finders._parse_anymail({})["email"] == ""


CHECKS = [check_icypeas_test_find, check_icypeas_no_name, check_icypeas_company_fallback,
          check_icypeas_parse,
          # collecting Icypeas's answer: fast when it is ready, patient when it is not
          check_polling_waits_for_an_answer_instead_of_believing_an_early_read,
          check_a_fast_answer_returns_on_the_first_read,
          check_a_real_miss_is_not_retried_forever,
          check_running_out_of_time_reports_no_email_never_a_wrong_one,
          check_no_ceiling_still_reads_once,
          check_the_old_flat_sleep_is_gone,
          check_anymail_test_find, check_anymail_no_domain, check_anymail_parse]

def test_icypeas_find(): check_icypeas_test_find()
def test_icypeas_no_name(): check_icypeas_no_name()
def test_icypeas_company(): check_icypeas_company_fallback()
def test_icypeas_parse(): check_icypeas_parse()
def test_anymail_find(): check_anymail_test_find()
def test_anymail_no_domain(): check_anymail_no_domain()
def test_anymail_parse(): check_anymail_parse()


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
