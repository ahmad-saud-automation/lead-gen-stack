"""
eval_backlog.py - offline test for "send all waiting leads" (no network, no keys, no sends).
    python eval_backlog.py   /   pytest eval_backlog.py

Runs against a throwaway runs folder and ledger, never the real ones.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "webapp"))
import server as S                                  # noqa: E402
from core import ledger as L                        # noqa: E402

CAMP = "lane-a"


def _sandbox():
    tmp = Path(tempfile.mkdtemp(prefix="backlog-"))
    (tmp / "runs").mkdir()
    S.RUNS_DIR, S.LEDGER_FILE = tmp / "runs", tmp / "ledger.db"
    return tmp


def _run(run_id, results, *, campaign=CAMP, test_mode=False, status="finished", mtime=0):
    fp = S.RUNS_DIR / f"{run_id}.json"
    fp.write_text(json.dumps({"run_id": run_id, "kind": "run", "status": status, "test_mode": test_mode,
                              "campaign": campaign, "results": results}), encoding="utf-8")
    if mtime:
        import os
        os.utime(fp, (mtime, mtime))


def _lead(lid, email, **kw):
    return {"row_key": lid, "lead_id": lid, "company": lid.upper(), "found_email": email,
            "send_ready": "yes", "verification": "good", **kw}


def check_gate_lets_unchecked_sheet_emails_through_only_when_on():
    r = _lead("x", "a@x.com", send_ready="no", verification="accepted_no_check")
    assert not S._is_send_ready(r)
    assert S._is_send_ready(r, send_unchecked=True)
    probable = _lead("y", "b@y.com", send_ready="no", verification="probable")
    assert not S._is_send_ready(probable, send_unchecked=True)       # a finder's guess never goes
    assert len(S._send_gate([r, probable], {"send_unchecked_sheet_emails": True})) == 1
    assert len(S._send_gate([r, probable], {"send_unchecked_sheet_emails": False})) == 0


def check_backlog_spans_runs_and_keeps_the_newest_copy():
    _sandbox()
    _run("r1", [_lead("p1", "old@p1.com"), _lead("p2", "a@p2.com")], mtime=1_000)
    _run("r2", [_lead("p1", "new@p1.com"), _lead("p3", "")], mtime=2_000)   # p3: no email
    rows, n = S.campaign_backlog(CAMP)
    assert sorted(r["found_email"] for r in rows) == ["a@p2.com", "new@p1.com"], rows
    assert n == 2


def check_backlog_skips_pushed_test_running_and_other_lanes():
    _sandbox()
    _run("r1", [_lead("p1", "a@p1.com"), _lead("p2", "a@p2.com")], mtime=1_000)
    _run("t1", [_lead("p3", "made@up.com")], test_mode=True, mtime=1_100)
    _run("r2", [_lead("p4", "a@p4.com")], status="running", mtime=1_200)
    _run("o1", [_lead("p5", "a@p5.com")], campaign="lane-b", mtime=1_300)
    led = L.Ledger(S.LEDGER_FILE)
    led.record_push(_lead("p1", "a@p1.com"), campaign=CAMP)
    led.close()
    rows, n = S.campaign_backlog(CAMP)
    assert [r["found_email"] for r in rows] == ["a@p2.com"], rows
    assert n == 1


def check_a_single_run_send_skips_leads_already_in_instantly():
    _sandbox()
    led = L.Ledger(S.LEDGER_FILE)
    led.record_push(_lead("p1", "a@p1.com"), campaign=CAMP)
    led.close()
    found = [_lead("p1", "a@p1.com"), _lead("p2", "a@p2.com")]
    rows, already = S._drop_already_pushed(found, None, {})
    assert [r["lead_id"] for r in rows] == ["p2"] and already == 1, (rows, already)
    # a free test's made-up leads are left alone, and so is everything with the ledger off
    assert S._drop_already_pushed(found, None, {}, test_run=True) == (found, 0)
    assert S._drop_already_pushed(found, None, {"use_ledger": False}) == (found, 0)


def check_backlog_push_refuses_without_confirm_or_a_campaign():
    assert "not confirmed" in S.start_backlog_push(CAMP, confirm=False)["error"]
    assert "No campaign" in S.start_backlog_push("no-such-lane-xyz", confirm=True)["error"]


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_")]

if __name__ == "__main__":
    ok = 0
    for fn in CHECKS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{ok}/{len(CHECKS)} checks passed")
    sys.exit(0 if ok == len(CHECKS) else 1)
