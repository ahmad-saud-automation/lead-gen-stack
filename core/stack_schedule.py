"""
stack_schedule.py — when each step of the stack starts by itself (build session 3).

Every job has ONE trigger:

    time   a set time or interval, in the same shape core/schedules.py already uses for a
           lane ({kind, every, start, end, days}) — so the same slot maths and the same
           "a missed slot is skipped, never fired late" rule apply
    after  starts as soon as the step before it completes (steps 2–6 only)

Firing a time step runs that step and then every following step whose trigger is "after"
and which is switched on: a chain. The chain stops at the first step that has its own time,
or is switched off.

Pure: no clock is read here. The caller passes `now`, which is what makes it testable. The
app clock (webapp/server.py) calls `due_jobs`; it is switched off in the test engine, so a
test never fires a step by itself.
"""
from __future__ import annotations

from datetime import datetime

from . import schedules as schedules_mod

# Find email comes first (2026-11-07, his order): every lead is searched, then only the leads
# that got an email have their website read, then every lead with an email gets an ice breaker.
STEPS = [("find", "Find email"), ("research", "Website research"), ("ice", "Ice breakers"),
         ("email", "Email template"), ("send", "Sending"), ("replies", "Replies")]
EXTRA = [("health", "Health check"), ("summary", "Daily summary")]
JOBS = [k for k, _ in STEPS + EXTRA]
LABEL = dict(STEPS + EXTRA)
STEP_KEYS = [k for k, _ in STEPS]

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI"]
# the day "every N days / weeks" counts from when none is given (a Monday). Counting from
# the day of saving would give a daily job no slot before that day.
ANCHOR = "2026-01-05"

# the approved sample's table
DEFAULTS = {
    "find": {"trigger": "time", "enabled": True,
             "schedule": {"kind": "weekly", "every": 1, "start": "07:00", "days": WEEKDAYS}},
    "research": {"trigger": "after", "enabled": True},
    "ice": {"trigger": "after", "enabled": True},
    "email": {"trigger": "after", "enabled": True},
    "send": {"trigger": "time", "enabled": True,
             "schedule": {"kind": "weekly", "every": 1, "start": "09:00", "days": WEEKDAYS}},
    "replies": {"trigger": "time", "enabled": True,
                "schedule": {"kind": "minute", "every": 30, "start": "00:00", "end": "23:59"}},
    "health": {"trigger": "time", "enabled": True,
               "schedule": {"kind": "minute", "every": 5, "start": "00:00", "end": "23:59"}},
    "summary": {"trigger": "time", "enabled": True,
                "schedule": {"kind": "daily", "every": 1, "start": "18:00"}},
}


class ScheduleError(ValueError):
    pass


def can_follow(job: str) -> bool:
    """Only steps 2–6 can start after the step before them."""
    return job in STEP_KEYS and STEP_KEYS.index(job) > 0


def clean(job: str, raw: dict | None) -> dict:
    """One job's trigger, checked. Raises ScheduleError in words a person can act on."""
    if job not in JOBS:
        raise ScheduleError(f"There is no step '{job}'.")
    raw = dict(raw or {})
    trigger = str(raw.get("trigger") or "time").strip().lower()
    if trigger not in ("time", "after"):
        raise ScheduleError("Choose a trigger: Time, or After previous step.")
    if trigger == "after" and not can_follow(job):
        first = "Step 1 has no step before it" if job == STEP_KEYS[0] else f"{LABEL[job]} is not a pipeline step"
        raise ScheduleError(f"{first}, so it needs a set time.")
    out = {"trigger": trigger, "enabled": bool(raw.get("enabled", True))}
    if trigger == "time":
        sched = {"anchor": ANCHOR, **(DEFAULTS[job].get("schedule") or {}), **(raw.get("schedule") or {})}
        s, problems = schedules_mod.normalize({**sched, "enabled": True, "via": "app"})
        if problems:
            text = "; ".join(problems)
            raise ScheduleError(text[0].upper() + text[1:] + ".")
        out["schedule"] = {k: s[k] for k in ("kind", "every", "start", "end", "days", "anchor")}
    return out


def all_jobs(saved: dict | None) -> dict[str, dict]:
    """Every job's trigger: what was saved, else the default. A saved value that no longer
    checks out falls back to the default rather than stopping the clock."""
    saved = saved or {}
    out = {}
    for job in JOBS:
        try:
            out[job] = clean(job, saved.get(job) or DEFAULTS[job])
        except ScheduleError:
            out[job] = clean(job, DEFAULTS[job])
    return out


def _norm(s: dict) -> dict:
    return schedules_mod.normalize({**s, "enabled": True, "via": "app"})[0]


def words(job: dict) -> str:
    """'Weekdays at 07:00', 'Every 30 minutes', 'Daily at 18:00' — or '—' for an after step."""
    if job["trigger"] == "after":
        return "—"
    s = job["schedule"]
    kind, n = s["kind"], s["every"]
    if kind == "minute":
        whole_day = s["start"] == "00:00" and s["end"] in ("23:59", "")
        return f"Every {n} minutes" + ("" if whole_day else f", {s['start']} to {s['end']}")
    if kind == "hourly":
        return f"Every {n} hour{'s' if n > 1 else ''} from {s['start']}"
    if kind == "daily":
        return f"Daily at {s['start']}" if n == 1 else f"Every {n} days at {s['start']}"
    days = s["days"]
    when = ("Weekdays" if days == WEEKDAYS else "Every day" if len(days) == 7
            else ", ".join(d.title() for d in days))
    return f"{when} at {s['start']}" + (f", every {n} weeks" if n > 1 else "")


def next_run(job_key: str, job: dict, now: datetime) -> datetime | None:
    if job["trigger"] != "time" or not job["enabled"]:
        return None
    return schedules_mod.next_after(_norm(job["schedule"]), now)


def next_words(job_key: str, job: dict, now: datetime) -> str:
    if not job["enabled"]:
        return "Off"
    if job["trigger"] == "after":
        return f"After step {STEP_KEYS.index(job_key)}"
    t = next_run(job_key, job, now)
    if t is None:
        return "Not planned"
    mins = int((t - now).total_seconds() // 60)
    if t.date() == now.date():
        return f"In {mins} minutes" if mins < 60 else f"Today {t:%H:%M}"
    if (t.date() - now.date()).days == 1:
        return f"Tomorrow {t:%H:%M}"
    return f"{t:%a %d %b} {t:%H:%M}"


def chain(jobs: dict[str, dict], start: str) -> list[str]:
    """The steps one firing of `start` runs: itself, then each following 'after' step that is
    switched on."""
    if start not in STEP_KEYS:
        return [start]
    i = STEP_KEYS.index(start)
    out = [start]
    for k in STEP_KEYS[i + 1:]:
        j = jobs[k]
        if j["trigger"] != "after" or not j["enabled"]:
            break
        out.append(k)
    return out


def due_jobs(jobs: dict[str, dict], last_fire: dict[str, str], now: datetime) -> list[tuple[str, datetime]]:
    """[(job, slot)] whose time slot has come since it last fired. A job that never fired
    starts counting from `now` (saving a schedule must not fire a slot from a minute ago)."""
    out = []
    for key in JOBS:
        j = jobs[key]
        if not j["enabled"] or j["trigger"] != "time":
            continue
        last = last_fire.get(key)
        if not last:
            continue
        slot, _missed = schedules_mod.due(_norm(j["schedule"]), datetime.fromisoformat(last), now)
        if slot is not None:
            out.append((key, slot))
    return out
