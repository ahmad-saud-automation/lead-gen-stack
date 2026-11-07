"""
eval_stack_schedule.py — per-step triggers (build session 3): core/stack_schedule.py and the
Schedules APIs.

Failed before 2026-11-06: core/stack_schedule.py, /api/stack/schedules*, /api/stack/approvals
and the app clock's stack_tick did not exist.

All against a throwaway database and a fixed clock. Nothing here starts the real app clock.

Run:  python eval_stack_schedule.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))
from core import stack_schedule as SS               # noqa: E402
import server as S                                  # noqa: E402

# a fixed Thursday morning, two minutes before step 1's 07:00 slot
THU =datetime(2026, 11, 5, 6, 58, 0)


def _sandbox():
    tmp = Path(tempfile.mkdtemp(prefix="sched-"))
    S.STACK_DB = tmp / "stack.db"
    return tmp


def check_defaults_match_the_sample_table():
    jobs = SS.all_jobs(None)
    got = [(k, jobs[k]["trigger"], SS.words(jobs[k])) for k in SS.JOBS]
    # Find email is step 1 since 2026-11-07 (his order), so it owns the 07:00 time
    assert got == [("find", "time", "Weekdays at 07:00"), ("research", "after", "—"), ("ice", "after", "—"),
                   ("email", "after", "—"), ("send", "time", "Weekdays at 09:00"),
                   ("replies", "time", "Every 30 minutes"), ("health", "time", "Every 5 minutes"),
                   ("summary", "time", "Daily at 18:00")], got


def check_next_run_words():
    jobs = SS.all_jobs(None)
    assert SS.next_words("find", jobs["find"], THU) == "In 2 minutes"
    assert SS.next_words("research", jobs["research"], THU) == "After step 1"
    assert SS.next_words("summary", jobs["summary"], THU) == "Today 18:00"
    fri_eve = datetime(2026, 11, 6, 19, 0)
    assert SS.next_words("find", jobs["find"], fri_eve) == "Mon 09 Nov 07:00", \
        SS.next_words("find", jobs["find"], fri_eve)
    off = {**jobs["send"], "enabled": False}
    assert SS.next_words("send", off, THU) == "Off"


def check_after_only_for_steps_2_to_6():
    for job in ("find", "health", "summary"):
        try:
            SS.clean(job, {"trigger": "after"})
        except SS.ScheduleError as e:
            assert "set time" in str(e), e
        else:
            raise AssertionError(f"{job} accepted 'after'")
    assert SS.clean("research", {"trigger": "after"})["trigger"] == "after"
    try:
        SS.clean("send", {"trigger": "time", "schedule": {"kind": "daily", "start": "25:00"}})
    except SS.ScheduleError as e:
        assert "HH:MM" in str(e), e
    else:
        raise AssertionError("a bad time was accepted")


def check_a_time_step_fires_once_and_chains_its_after_steps():
    jobs = SS.all_jobs(None)
    last = {k: THU.isoformat() for k in SS.JOBS}
    at = THU.replace(hour=7, minute=0, second=10)
    due = dict(SS.due_jobs(jobs, last, at))
    assert "find" in due and "send" not in due, due
    assert SS.chain(jobs, "find") == ["find", "research", "ice", "email"], SS.chain(jobs, "find")
    # the slot is recorded: the next look does not fire it again
    last["find"] = due["find"].isoformat()
    assert "find" not in dict(SS.due_jobs(jobs, last, at + timedelta(seconds=30)))
    # an "after" step switched off breaks the chain there
    jobs["ice"] = {**jobs["ice"], "enabled": False}
    assert SS.chain(jobs, "find") == ["find", "research"]
    # sending has its own time, so the chain never runs into it
    assert SS.chain(SS.all_jobs(None), "send") == ["send"]       # Replies has its own time too


def check_a_missed_slot_is_skipped_not_fired_late():
    jobs = SS.all_jobs(None)
    last = {k: THU.isoformat() for k in SS.JOBS}
    late = THU.replace(hour=8, minute=0)              # 07:00 was an hour ago (engine was off)
    assert "find" not in dict(SS.due_jobs(jobs, last, late))


def check_schedules_api_lists_eight_rows_and_saves():
    _sandbox()
    v = S.stack_schedules(now=THU)
    assert [r["job"] for r in v["rows"]] == SS.JOBS, v["rows"]
    assert v["rows"][0]["step"] == "1 · Find email" and v["rows"][1]["step"] == "2 · Website research"
    assert v["rows"][6]["step"] == "Health check"
    assert v["campaigns"][0] == {"id": "demo", "name": "Demo firms", "demo": True} and v["source"] == "demo", v["campaigns"]
    r = S.stack_schedules_save("research", {"trigger": "time", "enabled": True,
                                            "schedule": {"kind": "daily", "every": 1, "start": "07:30"}})
    assert r["ok"], r
    row = next(x for x in r["rows"] if x["job"] == "research")
    assert row["trigger"] == "time" and row["schedule"] == "Daily at 07:30", row
    bad = S.stack_schedules_save("find", {"trigger": "after"})
    assert not bad["ok"] and "set time" in bad["error"], bad
    off = S.stack_schedules_save("send", {"trigger": "time", "enabled": False})
    assert next(x for x in off["rows"] if x["job"] == "send")["next"] == "Off"


def check_clock_off_says_so():
    _sandbox()
    os.environ["LEADGEN_NO_SCHEDULER"] = "1"
    v = S.stack_schedules(now=THU)
    assert v["clock_on"] is False and "off" in v["clock_text"], v["clock_text"]


def check_tick_counts_from_the_first_look_then_fires_the_chain():
    _sandbox()
    S.stack_reset_demo()
    first = S.stack_tick(THU, wait=True)          # first look: start counting, fire nothing
    assert first == [], first
    fired = S.stack_tick(THU.replace(hour=7, minute=0, second=20), wait=True)
    assert {"find", "replies", "health"} <= set(fired) and "send" not in fired, fired
    st = S._stack_store()
    run = next(r for r in st.runs("demo") if r["trigger"].startswith("Schedule: Find email"))
    assert run["state"] == "done" and run["start_step"] == 0 and run["end_step"] == 3, run
    stat = st.statuses("demo")
    assert sum(1 for v in stat.values() if v.get("icebreaker_status") == "written") == 8
    assert not any(v.get("push_status") for v in stat.values()), "the chain ran into Sending"
    # the same slot never fires twice
    assert "find" not in S.stack_tick(THU.replace(hour=7, minute=1), wait=True)


def check_auto_approve_switch_reaches_the_template_queue():
    _sandbox()
    assert S.stack_approvals_get()["auto_approve"] is True
    r = S.stack_approvals_set({"auto_approve": False})
    assert r["ok"] and r["auto_approve"] is False, r
    got = S.stack_email_request("demo", "new", "Lead with month-end close")
    assert got["ok"] and got["auto_approved"] is False and got["state"] == "draft_ready", got
    S.stack_approvals_set({"auto_approve": True})
    got = S.stack_email_request("demo", "new", "Lead with month-end close")
    assert got["auto_approved"] is True, got
    locked = S.stack_approvals_set({"auto_reply": True})
    assert not locked["ok"] and "Locked" in locked["error"], locked
    assert S.stack_approvals_get()["auto_reply"] is False


CHECKS = [check_defaults_match_the_sample_table, check_next_run_words, check_after_only_for_steps_2_to_6,
          check_a_time_step_fires_once_and_chains_its_after_steps, check_a_missed_slot_is_skipped_not_fired_late,
          check_schedules_api_lists_eight_rows_and_saves, check_clock_off_says_so,
          check_tick_counts_from_the_first_look_then_fires_the_chain,
          check_auto_approve_switch_reaches_the_template_queue]


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
