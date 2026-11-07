"""
eval_lane_schedules.py - offline test for per-campaign schedules (V4 G).
    python eval_lane_schedules.py   /   pytest eval_lane_schedules.py

core/schedules.py maths, plus the engine's clock and trigger switching with every side effect
faked: config and state live in a temp folder, schtasks is a fake, and no run is started.
"""
from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from core import schedules as Sch

MON = date(2026, 10, 5)          # a Monday


def _s(**kw):
    s, probs = Sch.normalize({"enabled": True, "anchor": MON.isoformat(), **kw})
    assert not probs, probs
    return s


def at(d: date, hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def check_minute_slots_stay_inside_the_window():
    s = _s(kind="minute", every=30, start="08:00", end="17:30")
    assert Sch.next_after(s, at(MON, "07:00")) == at(MON, "08:00")
    assert Sch.next_after(s, at(MON, "08:00")) == at(MON, "08:30"), "strictly after"
    assert Sch.next_after(s, at(MON, "17:30")) == at(MON + timedelta(days=1), "08:00")


def check_hourly_with_and_without_end():
    s = _s(kind="hourly", every=2, start="09:00", end="13:00")
    assert Sch.next_after(s, at(MON, "11:00")) == at(MON, "13:00")
    assert Sch.next_after(s, at(MON, "13:00")) == at(MON + timedelta(days=1), "09:00")
    s2 = _s(kind="hourly", every=6, start="09:00")
    assert Sch.next_after(s2, at(MON, "15:00")) == at(MON, "21:00")


def check_daily_every_n_days_counts_from_the_anchor():
    s = _s(kind="daily", every=2, start="07:00")
    assert Sch.next_after(s, at(MON, "06:00")) == at(MON, "07:00")
    assert Sch.next_after(s, at(MON, "07:00")) == at(MON + timedelta(days=2), "07:00")


def check_weekly_days_and_every_n_weeks():
    s = _s(kind="weekly", every=2, start="10:00", days=["fri", "MON"])
    assert s["days"] == ["MON", "FRI"]
    assert Sch.next_after(s, at(MON, "11:00")) == at(MON + timedelta(days=4), "10:00")
    # the week after is skipped (every 2 weeks)
    assert Sch.next_after(s, at(MON + timedelta(days=4), "10:00")) == at(MON + timedelta(days=14), "10:00")


def check_minute_on_chosen_days_only():
    s = _s(kind="minute", every=60, start="09:00", end="10:00", days=["TUE"])
    assert Sch.next_after(s, at(MON, "08:00")) == at(MON + timedelta(days=1), "09:00")


def check_bad_input_is_refused_with_a_reason():
    for raw, word in (({"kind": "weekly"}, "weekday"), ({"kind": "minute", "end": ""}, "end time"),
                      ({"start": "25:00"}, "HH:MM"), ({"via": "cron"}, "trigger"),
                      ({"kind": "hourly", "start": "10:00", "end": "09:00"}, "after")):
        _s2, probs = Sch.normalize(raw)
        assert any(word in p for p in probs), (raw, probs)
    s, _ = Sch.normalize({"kind": "minute", "every": 99999, "end": "10:00"})
    assert s["every"] == 1439, "clamped like the Windows trigger"


def check_due_fires_once_and_skips_missed():
    s = _s(kind="minute", every=30, start="08:00", end="17:30")
    slot, missed = Sch.due(s, None, at(MON, "08:01"))
    assert slot == at(MON, "08:00") and missed == 0
    again, _ = Sch.due(s, slot, at(MON, "08:02"))
    assert again is None, "a slot fires once"
    # the engine was off from 08:00 to 10:01: 08:30..09:30 are missed, 10:00 fires
    slot2, missed2 = Sch.due(s, at(MON, "08:00"), at(MON, "10:01"))
    assert slot2 == at(MON, "10:00") and missed2 == 3, (slot2, missed2)
    # nothing due when the latest slot is older than the grace window
    assert Sch.due(s, None, at(MON, "08:20"))[0] is None


def check_summary_reads_like_the_windows_trigger():
    assert Sch.summary(_s(kind="minute", every=30, start="08:00", end="17:30")) == "every 30 min, 08:00–17:30"
    assert Sch.summary(_s(kind="daily", start="07:00")) == "daily at 07:00"


# ───────── the engine's clock and trigger switching, with every side effect faked ─────────

_FAKED = ("CONFIG_DIR", "SCHEDULE_STATE", "SCHEDULE_LOG", "TASKS_DIR", "_schtasks",
          "_task_allow_battery", "windows_available", "fire_lane")


@contextmanager
def engine(lanes: list[dict]):
    """The server module with its files in a temp folder and its side effects faked; put
    back afterwards so other test files in the same pytest process see the real one."""
    from webapp import server as S
    saved = {k: getattr(S, k) for k in _FAKED}
    with tempfile.TemporaryDirectory() as d:
        try:
            yield _engine(S, Path(d), lanes)
        finally:
            for k, v in saved.items():
                setattr(S, k, v)


def _engine(S, tmp: Path, lanes: list[dict]):
    (tmp / "config").mkdir()
    (tmp / "config" / "campaigns.json").write_text(json.dumps({"globals": {}, "campaigns": lanes}))
    S.CONFIG_DIR = tmp / "config"
    S.SCHEDULE_STATE = tmp / "state.json"
    S.SCHEDULE_LOG = tmp / "schedule.log"
    S.TASKS_DIR = tmp / "tasks"
    fired, tasks = [], {}

    def fake_schtasks(args):
        name = args[args.index("/tn") + 1]
        if args[0] == "/create":
            tasks[name] = args
            return {"ok": True, "out": "", "err": ""}
        if args[0] == "/delete":
            tasks.pop(name, None)
            return {"ok": True, "out": "", "err": ""}
        return {"ok": name in tasks, "out": "Next Run Time: soon" if name in tasks else "", "err": ""}

    S._schtasks = fake_schtasks
    S._task_allow_battery = lambda name: {"ok": True, "err": ""}
    S.windows_available = lambda: True
    S.fire_lane = lambda camp, **kw: fired.append(camp.id) or {"run_id": f"r{len(fired)}"}
    return S, fired, tasks


LANE = {"id": "lane-a", "name": "Lane A", "enabled": True, "tab": "Practices",
        "schedule": {"enabled": True, "via": "app", "kind": "minute", "every": 30,
                     "start": "08:00", "end": "17:30"}}


def check_no_double_fire_across_a_restart():
    with engine([LANE]) as (S, fired, _t):
        S.scheduler_tick(at(MON, "08:01"))
        S.scheduler_tick(at(MON, "08:01"))
        assert fired == ["lane-a"], fired
        # a restart keeps nothing in memory: the clock reads only the state file, so a tick
        # after it sees exactly what this one sees
        S.scheduler_tick(at(MON, "08:03"))
        assert fired == ["lane-a"], "the 08:00 slot was already fired before the restart"
        S.scheduler_tick(at(MON, "08:31"))
        assert fired == ["lane-a", "lane-a"]
        assert json.loads(S.SCHEDULE_STATE.read_text())["lane-a"]["last_fire"] == "2026-10-05T08:30:00"


def check_disabled_lane_or_windows_lane_is_not_fired_by_the_app():
    off = {**LANE, "id": "off", "enabled": False}
    win = {**LANE, "id": "win", "schedule": {**LANE["schedule"], "via": "windows"}}
    with engine([off, win]) as (S, fired, _t):
        S.scheduler_tick(at(MON, "08:01"))
        assert fired == [], fired


def check_switching_via_removes_the_other_trigger():
    with engine([{**LANE, "schedule": {}}]) as (S, _f, tasks):
        r =S.save_lane_schedule("lane-a", {**LANE["schedule"], "via": "windows"})
        assert r["ok"], r
        assert "LeadGen-lane-a" in tasks and (S.TASKS_DIR / "LeadGen-lane-a.bat").exists()
        bat = (S.TASKS_DIR / "LeadGen-lane-a.bat").read_text()
        assert "--campaign lane-a --test" in bat, bat
        r2 = S.save_lane_schedule("lane-a", {**LANE["schedule"], "via": "app"})
        assert r2["ok"] and "LeadGen-lane-a" not in tasks, "moving to the app removes the task"
        saved = json.loads((S.CONFIG_DIR / "campaigns.json").read_text())["campaigns"][0]["schedule"]
        assert saved["via"] == "app" and saved["kind"] == "minute"
        # Windows cannot do minute-on-days; refused, nothing created
        r3 = S.save_lane_schedule("lane-a", {**LANE["schedule"], "via": "windows", "days": ["MON"]})
        assert not r3["ok"] and "LeadGen-lane-a" not in tasks, r3
        # deleting the lane removes its task
        S.save_lane_schedule("lane-a", {**LANE["schedule"], "via": "windows"})
        assert "LeadGen-lane-a" in tasks
        assert S.delete_campaign("lane-a")["ok"]
        assert "LeadGen-lane-a" not in tasks


def check_windows_lane_on_a_linux_server_is_flagged():
    win = {**LANE, "schedule": {**LANE["schedule"], "via": "windows"}}
    with engine([win]) as (S, fired, _t):
        S.windows_available = lambda: False          # the app moved to a Linux server
        view = S.campaigns_view()["campaigns"][0]["schedule"]
        assert view["problems"] and "not Windows" in view["problems"][0], view
        assert not view["active"], "a lane nothing can fire must not show a next run"
        S.scheduler_tick(at(MON, "08:01"))
        assert fired == [], "the app clock never fires a Windows lane — the warning is the fix"


CHECKS = [
    check_minute_slots_stay_inside_the_window,
    check_hourly_with_and_without_end,
    check_daily_every_n_days_counts_from_the_anchor,
    check_weekly_days_and_every_n_weeks,
    check_minute_on_chosen_days_only,
    check_bad_input_is_refused_with_a_reason,
    check_due_fires_once_and_skips_missed,
    check_summary_reads_like_the_windows_trigger,
    check_no_double_fire_across_a_restart,
    check_disabled_lane_or_windows_lane_is_not_fired_by_the_app,
    check_switching_via_removes_the_other_trigger,
    check_windows_lane_on_a_linux_server_is_flagged,
]


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
