"""
stack_run.py — runs a chain of steps by itself (build session 3).

A chain run is one row in `stack_runs`: which steps, the trigger that started it, where it
is, and an activity log the screen reads every second. The steps themselves are the real
step code (research, find email, ice breakers, cold email, sending, replies), handed in by
the server as plain functions, so this file knows nothing about sheets or services.

Each step gets a store wrapped by the health agent (core/health.py): a known write error is
fixed inside the step; any error that escapes a step stops the chain and is escalated.

Pure apart from the store and the `sleep` it is given: tests pass sleep=lambda s: None.
"""
from __future__ import annotations

import random
import time
from datetime import datetime

from .health import Agent


def new_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"S{now:%Y%m%d-%H%M%S}-{random.randint(1000, 9999)}"


def logger(store, run_id: str, now=datetime.now):
    def log(text: str, tone: str = "") -> None:
        store.add_event(run_id, {"t": now().strftime("%H:%M:%S"), "text": text, "tone": tone})
    return log


def run_chain(store, source: str, run_id: str, steps: list[tuple], *, pace: float = 0.0,
              sleep=time.sleep, stop=None, wrap=None, waits=None, finish=None, now=datetime.now) -> dict:
    """Run `steps` in order. Each step is (index, key, label, fn); fn(store) returns
    {"summary": str, "lines": [(text, tone)], ...}.

    pace    seconds spread over each step's activity lines, so a person can watch (0 in tests)
    stop()  True once the run should end between steps (Reset)
    wrap    wraps the real store for the steps (the demo's stand-in write limit)
    finish  called after the last step, before the run is marked done (health check, summary)
    """
    stop = stop or (lambda: False)
    log = logger(store, run_id, now)
    kw = {"waits": waits} if waits is not None else {}
    agent = Agent(store, source, sleep=sleep, now=now, run_id=run_id, log=log, **kw)
    stamp = lambda: now().strftime("%Y-%m-%d %H:%M:%S")           # noqa: E731
    store.update_run(run_id, state="running", started=store.run(run_id).get("started") or stamp())
    results = {}
    for idx, key, label, fn in steps:
        if stop():
            store.update_run(run_id, state="stopped", finished=stamp(), message="Stopped.")
            return store.run(run_id)
        store.update_run(run_id, step=idx)
        log(f"Step {idx + 1} · {label} started")
        inner = wrap(store) if wrap else store
        try:
            out = fn(agent.guard(inner, label)) or {}
        except Exception as e:  # noqa: BLE001 - any error that escapes a step is escalated
            inc = agent.on_error(label, e)
            store.update_run(run_id, state="waiting", finished=stamp(),
                             message=f"{inc['issue']}. Step {idx + 1} is paused and waits for you.")
            return store.run(run_id)
        results[key] = {k: v for k, v in out.items() if k not in ("lines",)}
        lines = list(out.get("lines") or [])
        gap = pace / (len(lines) + 1) if pace else 0
        for text, tone in lines:
            log(text, tone)
            if gap:
                sleep(gap)
        if out.get("summary"):
            log(f"{label}: {out['summary']}")
        if gap:
            sleep(gap)
        store.update_run(run_id, step=idx + 1, result=results)
    if finish:
        finish(agent, log)
    log("Pipeline completed.", "good")
    store.update_run(run_id, state="done", finished=stamp(), result=results)
    return store.run(run_id)
