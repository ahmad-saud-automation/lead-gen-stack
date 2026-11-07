"""
eval_schedule.py - offline test for trigger translation (no scheduled task is created).
    python eval_schedule.py   /   pytest eval_schedule.py
Checks the n8n-style trigger choices become correct, validated schtasks flags.
"""
from __future__ import annotations

import sys

from webapp.server import _schedule_args


def _flags(kind, every=1, start="08:00", end="17:30", days=None):
    args, info, err = _schedule_args(kind, every, start, end, days or [])
    assert not err, err
    return " ".join(args), info["summary"]


def check_minute():
    f, s = _flags("minute", 30, "08:00", "17:30")
    assert f == "/sc minute /mo 30 /st 08:00 /et 17:30", f      # V7's own cadence
    assert "every 30 min" in s


def check_hourly():
    f, _ = _flags("hourly", 2, "09:00", "18:00")
    assert f == "/sc hourly /mo 2 /st 09:00 /et 18:00", f
    f2, s2 = _flags("hourly", 1, "09:00", "")                    # blank end = all day
    assert f2 == "/sc hourly /mo 1 /st 09:00", f2
    assert "until" not in s2


def check_daily():
    f, s = _flags("daily", 1, "07:30")
    assert f == "/sc daily /mo 1 /st 07:30", f
    assert "at 07:30" in s


def check_weekly():
    f, s = _flags("weekly", 1, "09:00", days=["mon", "wed", "fri"])
    assert f == "/sc weekly /mo 1 /d MON,WED,FRI /st 09:00", f
    assert "MON, WED, FRI" in s


def check_validation():
    for bad_start in ["25:00", "8:00", "", "abc", "08:99"]:
        _, _, err = _schedule_args("minute", 30, bad_start, "17:30", [])
        assert err, f"expected rejection for start={bad_start!r}"
    _, _, err = _schedule_args("minute", 30, "08:00", "nope", [])
    assert err and "End time" in err
    _, _, err = _schedule_args("weekly", 1, "09:00", "", [])       # no weekday picked
    assert err and "weekday" in err
    _, _, err = _schedule_args("nonsense", 1, "09:00", "", [])
    assert err and "Unknown trigger" in err


def check_intervals_clamped():
    f, _ = _flags("minute", 99999, "08:00", "17:30")
    assert "/mo 1439" in f, f                                      # minutes capped below a day
    f2, _ = _flags("hourly", 99, "08:00", "")
    assert "/mo 23" in f2, f2                                      # hours capped below a day
    f3, _ = _flags("minute", 0, "08:00", "17:30")
    assert "/mo 30" in f3, f3                       # 0 means "unset" -> the V7 default of 30
    f4, _ = _flags("hourly", 0, "08:00", "")
    assert "/mo 1" in f4, f4                        # unset hourly -> every hour
    f5, _ = _flags("minute", -5, "08:00", "17:30")
    assert "/mo 1" in f5, f5                                       # negatives floored at 1


def check_no_shell_injection():
    """Values reach schtasks as separate argv entries, so quotes/&& can't inject."""
    args, _, err = _schedule_args("weekly", 1, "09:00", "", ["MON", 'x" && calc', "FRI"])
    assert not err
    assert "/d MON,FRI" in " ".join(args)                           # junk day dropped, not passed on
    for a in args:
        assert "&&" not in a and '"' not in a


CHECKS = [check_minute, check_hourly, check_daily, check_weekly, check_validation,
          check_intervals_clamped, check_no_shell_injection]

def test_minute(): check_minute()
def test_hourly(): check_hourly()
def test_daily(): check_daily()
def test_weekly(): check_weekly()
def test_validation(): check_validation()
def test_clamp(): check_intervals_clamped()
def test_injection(): check_no_shell_injection()


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
