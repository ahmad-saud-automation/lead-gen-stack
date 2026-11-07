"""
schedules.py — when a campaign lane runs by itself.

Shape, stored on the lane as `schedule` in campaigns.json:

    {enabled, via: app|windows, kind: minute|hourly|daily|weekly, every,
     start: "HH:MM", end: "HH:MM", days: ["MON", ...], test_mode, anchor: "YYYY-MM-DD"}

ONE LANE = ONE TRIGGER. `via` says which trigger fires it — the engine's own clock ("app",
works on any server) or Windows Task Scheduler ("windows") — so a lane never runs twice.

The meaning of each kind matches the schtasks flags `server._schedule_args` builds, so a lane
moved from one trigger to the other keeps its times:

    minute  every N minutes from start to end, each day (or only `days`, when given)
    hourly  every N hours from start, until end (blank end = until midnight)
    daily   at start, every N days counted from `anchor`
    weekly  at start on `days`, every N weeks counted from `anchor`'s week

Pure: no clock is read here. The caller passes `now`, which is what makes it testable.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

KINDS = ("minute", "hourly", "daily", "weekly")
VIAS = ("app", "windows")
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LIMITS = {"minute": (1, 1439), "hourly": (1, 23), "daily": (1, 365), "weekly": (1, 52)}

# a slot more than this far in the past when the clock looks is MISSED, not late: a restart
# or a sleeping laptop must not fire a backlog of runs the moment it wakes
GRACE = timedelta(minutes=5)


def normalize(raw: dict | None, *, today: date | None = None) -> tuple[dict, list[str]]:
    """(clean schedule, problems). Problems are in words a person can act on."""
    raw = dict(raw or {})
    problems: list[str] = []
    kind = str(raw.get("kind") or "daily").strip().lower()
    if kind not in KINDS:
        problems.append(f"unknown schedule type '{kind}'")
        kind = "daily"
    via = str(raw.get("via") or "app").strip().lower()
    if via not in VIAS:
        problems.append(f"unknown trigger '{via}' — use app or windows")
        via = "app"
    lo, hi = _LIMITS[kind]
    try:
        every = int(raw.get("every") or 1)
    except (TypeError, ValueError):
        problems.append("'every' must be a whole number")
        every = 1
    every = max(lo, min(every, hi))
    start = str(raw.get("start") or "08:00").strip()
    if not _HHMM.match(start):
        problems.append("start time must be HH:MM (24h)")
    end = str(raw.get("end") or "").strip()
    if kind == "minute" and not end:
        problems.append("an every-N-minutes schedule needs an end time")
    if end and not _HHMM.match(end):
        problems.append("end time must be HH:MM (24h)")
    if end and _HHMM.match(start) and _HHMM.match(end) and end <= start and kind in ("minute", "hourly"):
        problems.append("end time must be after the start time")
    days = [d.strip().upper()[:3] for d in (raw.get("days") or []) if str(d).strip()]
    days = [d for d in WEEKDAYS if d in days]                 # known days, week order, no repeats
    if kind == "weekly" and not days:
        problems.append("pick at least one weekday")
    anchor = str(raw.get("anchor") or "").strip()
    try:
        date.fromisoformat(anchor)
    except ValueError:
        anchor = (today or date.today()).isoformat()
    clean = {"enabled": bool(raw.get("enabled", False)), "via": via, "kind": kind, "every": every,
             "start": start, "end": end if kind in ("minute", "hourly") else "", "days": days,
             "test_mode": bool(raw.get("test_mode", True)), "anchor": anchor}
    return clean, problems


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _day_slots(s: dict, day: date) -> list[datetime]:
    """Every time this schedule fires on `day`, in order."""
    kind, n = s["kind"], max(1, int(s["every"]))
    anchor = date.fromisoformat(s["anchor"])
    wd = WEEKDAYS[day.weekday()]
    sh, sm = _hm(s["start"])
    first = datetime(day.year, day.month, day.day, sh, sm)

    if kind == "daily":
        return [first] if (day - anchor).days % n == 0 and day >= anchor else []
    if kind == "weekly":
        week = ((day - timedelta(days=day.weekday())) - (anchor - timedelta(days=anchor.weekday()))).days // 7
        return [first] if wd in s["days"] and week >= 0 and week % n == 0 else []

    # minute / hourly: a run of times from start until end
    if s["days"] and wd not in s["days"]:
        return []
    eh, em = _hm(s["end"]) if s["end"] else (23, 59)
    last = datetime(day.year, day.month, day.day, eh, em)
    step = timedelta(minutes=n) if kind == "minute" else timedelta(hours=n)
    out, t = [], first
    while t <= last:
        out.append(t)
        t += step
    return out


def next_after(s: dict, t: datetime, *, horizon_days: int = 400) -> datetime | None:
    """The first slot strictly after `t`, or None if there is none within the horizon."""
    day = t.date()
    for _ in range(horizon_days):
        for slot in _day_slots(s, day):
            if slot > t:
                return slot
        day += timedelta(days=1)
    return None


def due(s: dict, last_fire: datetime | None, now: datetime) -> tuple[datetime | None, int]:
    """(slot to fire now or None, how many slots were missed since the last fire).

    A slot fires once: anything at or before `last_fire` is done. A slot older than GRACE is
    missed — counted so it can be logged, never replayed."""
    floor = now - GRACE
    since = max(last_fire, floor) if last_fire else floor
    missed = 0
    if last_fire and last_fire < floor:
        t = last_fire
        while missed < 1000:
            nxt = next_after(s, t)
            if nxt is None or nxt > floor:
                break
            missed += 1
            t = nxt
    slot = next_after(s, since)
    return (slot if slot is not None and slot <= now else None), missed


def summary(s: dict) -> str:
    """'every 30 min, 08:00–17:30' — the same words the Windows trigger uses."""
    n, kind = s["every"], s["kind"]
    days = f" on {', '.join(s['days'])}" if s["days"] and kind != "weekly" else ""
    if kind == "minute":
        return f"every {n} min, {s['start']}–{s['end']}{days}"
    if kind == "hourly":
        return f"every {n} hour{'s' if n > 1 else ''} from {s['start']}" + \
            (f" until {s['end']}" if s["end"] else "") + days
    if kind == "daily":
        return f"every {n} day{'s' if n > 1 else ''} at {s['start']}" if n > 1 else f"daily at {s['start']}"
    return f"{', '.join(s['days'])} at {s['start']}" + (f" every {n} weeks" if n > 1 else "")
