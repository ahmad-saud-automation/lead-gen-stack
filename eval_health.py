"""
eval_health.py — the monitoring agent (build session 3): core/health.py.

Failed before 2026-11-06: core/health.py did not exist.

The rule under test: the agent fixes ONLY the kinds on its allowed list (write limit,
interrupted run, unsaved result, unreachable website). Spend, credits, sheet data, template
changes and anything unknown are escalated and never "fixed".

All against a throwaway database. `sleep` is recorded, never slept.

Run:  python eval_health.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from core import health as H                        # noqa: E402
from core import store as store_mod                 # noqa: E402
from core import stack_run as R                     # noqa: E402
from core.demo_services import DemoWriteLimit       # noqa: E402

SRC = "demo"
NOW = datetime(2026, 11, 6, 9, 12, 0)


def _store():
    return store_mod.Store(Path(tempfile.mkdtemp(prefix="health-")) / "stack.db")


def _agent(st, slept=None):
    slept = slept if slept is not None else []
    return H.Agent(st, SRC, sleep=slept.append, now=lambda: NOW), slept


class AlwaysLimited:
    """A sheet that refuses every write."""
    def __init__(self, inner):
        self._inner = inner

    def write_status(self, *a, **k):
        raise H.WriteLimit("write limit reached")

    def __getattr__(self, n):
        return getattr(self._inner, n)


def check_the_two_lists_are_the_sample_words():
    assert list(dict.fromkeys(H.ALLOWED.values())) == [
        "Sheet write limit: wait and retry", "Interrupted run: close and resume",
        "Unsaved result: save again at no cost", "Unreachable website: retry the next day"]
    assert H.ESCALATED_LIST == ["Extra spend or credit purchases", "Changes to existing sheet data",
                                "Template changes", "Any issue not on the automatic list"]
    for kind in ("spend", "credits", "sheet_change", "template_change", "unknown"):
        assert not H.is_allowed(kind), kind


def check_a_write_limit_is_waited_out_and_saved():
    st = _store()
    a, slept = _agent(st)
    g = a.guard(DemoWriteLimit(st, nth=1, times=1), "Find email")
    g.write_status("find_email", SRC, "DM-001", {"email_status": "enriched"})
    assert st.statuses(SRC)["DM-001"]["email_status"] == "enriched"
    assert slept == [2], slept
    inc = st.incidents(SRC)
    assert len(inc) == 1 and inc[0]["kind"] == "write_limit" and inc[0]["result"] == "resolved", inc
    assert "Waited 2 seconds" in inc[0]["action"], inc[0]


def check_a_write_that_never_succeeds_is_kept_then_saved_at_the_next_check():
    st = _store()
    a, slept = _agent(st)
    g = a.guard(AlwaysLimited(st), "Find email")
    g.write_status("find_email", SRC, "DM-002", {"email_status": "as-is"})
    assert slept == [2, 4, 8], slept
    assert "DM-002" not in st.statuses(SRC)
    assert len(st.pending(SRC)) == 1 and st.incidents(SRC)[0]["result"] == "open"
    a.check()
    assert st.statuses(SRC)["DM-002"]["email_status"] == "as-is"
    assert st.pending(SRC) == []
    inc = st.incidents(SRC)
    assert len(inc) == 1 and inc[0]["result"] == "resolved" and "no cost" in inc[0]["action"], inc


def check_a_kept_write_still_obeys_the_column_allow_list():
    st = _store()
    a, _ = _agent(st)
    g = a.guard(AlwaysLimited(st), "Find email")
    try:
        g.write_status("find_email", SRC, "DM-003", {"Status": "done"})
    except Exception as e:  # noqa: BLE001
        assert "Status" in str(e) or "not" in str(e).lower(), e
    else:
        raise AssertionError("a step wrote another column through the health agent")
    assert st.pending(SRC) == []


def check_an_interrupted_run_is_closed_and_resumed():
    st = _store()
    st.add_run({"id": "old", "source": SRC, "trigger": "Schedule", "state": "running", "step": 2,
                "start_step": 0, "end_step": 5})
    st.add_run({"id": "mine", "source": SRC, "trigger": "Schedule", "state": "running", "step": 1})
    a, _ = _agent(st)
    resumed = []
    a.check(alive=frozenset({"mine"}), resume=lambda r: resumed.append(r["step"]) or "new")
    assert st.run("old")["state"] == "interrupted" and st.run("mine")["state"] == "running"
    assert resumed == [2], resumed
    inc = st.incidents(SRC)
    assert len(inc) == 1 and inc[0]["kind"] == "interrupted_run" and inc[0]["result"] == "resolved"
    assert "resumed from step 3" in inc[0]["action"], inc[0]


def check_a_refused_website_is_retried_the_next_day_then_escalated():
    st = _store()
    a, _ = _agent(st)
    a.check(blocked_keys=["DM-009"], names={"DM-009": "Ridgeway"})
    a.check(blocked_keys=["DM-009"], names={"DM-009": "Ridgeway"})       # no second incident
    inc = st.incidents(SRC)
    assert len(inc) == 1 and inc[0]["kind"] == "site_unreachable" and "Ridgeway" in inc[0]["issue"], inc
    assert a.due_site_retries(date(2026, 11, 6)) == []                    # not today
    st.save_facts(SRC, "DM-009", {"website_status": "blocked", "researched_on": "2026-11-06"})
    for day in (7, 8, 9):
        assert a.due_site_retries(date(2026, 11, day)) == ["DM-009"]
        assert not st.researched_recently(SRC, "DM-009", today=date(2026, 11, day))
    a.check(blocked_keys=["DM-009"], names={"DM-009": "Ridgeway"})
    inc = st.incidents(SRC)
    assert len(inc) == 2 and inc[1]["result"] == "escalated" and "3 tries" in inc[1]["issue"], inc
    assert a.due_site_retries(date(2026, 11, 20)) == []


def check_escalated_kinds_are_never_fixed():
    for exc in (H.CreditsUsedUp("Add credits, then select Resume."), H.SpendLimit("over the daily limit"),
                H.SheetChange("row 12 differs"), H.TemplateChange("template A"), RuntimeError("boom")):
        st = _store()
        a, slept = _agent(st)
        out = a.on_error("Find email", exc)
        assert out["result"] == "escalated" and slept == [], (exc, out)
        assert st.incidents(SRC)[0]["result"] == "escalated"


def check_no_live_template_is_escalated_once():
    st = _store()
    a, _ = _agent(st)
    a.check(live_templates=0, waiting_leads=4)
    a.check(live_templates=0, waiting_leads=4)
    inc = st.incidents(SRC)
    assert len(inc) == 1 and inc[0]["kind"] == "template_change" and inc[0]["result"] == "escalated", inc
    assert H.tiles(inc, NOW.date()) == {"issues": 1, "resolved": 0, "waiting": 1}


def check_a_step_error_stops_the_chain_and_waits():
    st = _store()
    st.add_run({"id": "r1", "source": SRC, "trigger": "t", "state": "scheduled"})
    ran = []

    def ok(_s):
        ran.append("ok")
        return {"summary": "fine"}

    def credits(_s):
        raise H.CreditsUsedUp("Add credits, then select Resume.")

    out = R.run_chain(st, SRC, "r1", [(0, "a", "Website research", ok), (1, "b", "Find email", credits),
                                      (2, "c", "Ice breakers", ok)], sleep=lambda s: None)
    assert out["state"] == "waiting" and ran == ["ok"] and out["step"] == 1, out
    assert "paused" in out["message"] and st.incidents(SRC)[0]["kind"] == "credits"


def check_summary_lines():
    inc = [{"at": "2026-11-06 09:12:00", "result": "resolved", "issue": "x", "action": "y"},
           {"at": "2026-11-06 10:05:00", "result": "escalated", "issue": "Email finder credits used up",
            "action": "Paused Find email."}]
    s = H.summary(date(2026, 11, 6), inc, {"leads": 12, "emails": 8, "sent": 5, "replies": 5, "interested": 1},
                  [{"text": "1 interested reply (Harbour)"}])
    assert s["title"] == "Daily summary · Friday 6 November", s["title"]
    assert s["lines"][0] == "Issues: 2 · Resolved automatically: 1 · Waiting for you: 1", s["lines"]
    assert s["lines"][1].startswith("Action needed: Email finder credits used up")
    assert s["lines"][-1] == "Today: 12 leads · 8 emails found · 5 sent (test mode) · 5 replies (1 interested)"


CHECKS = [check_the_two_lists_are_the_sample_words, check_a_write_limit_is_waited_out_and_saved,
          check_a_write_that_never_succeeds_is_kept_then_saved_at_the_next_check,
          check_a_kept_write_still_obeys_the_column_allow_list, check_an_interrupted_run_is_closed_and_resumed,
          check_a_refused_website_is_retried_the_next_day_then_escalated, check_escalated_kinds_are_never_fixed,
          check_no_live_template_is_escalated_once, check_a_step_error_stops_the_chain_and_waits,
          check_summary_lines]


def main() -> int:
    failed = 0
    for c in CHECKS:
        try:
            c(); print(f"PASS  {c.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"FAIL  {c.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
