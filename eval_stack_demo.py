"""
eval_stack_demo.py — the Live demo, Health page, Home decisions and Live demo mode
(build session 3).

Failed before 2026-11-06: /api/stack/demo/start, demo/status, health, decisions and
presenting did not exist, and the source pickers showed his campaign names in every mode.

Done means: ONE trigger runs steps 1–6 on the Demo firms by itself, $0, the same result
every run, and the health agent fixes the demo's one known write error on its own.

All against a throwaway database.

Run:  python eval_stack_demo.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "webapp"))
import server as S                                  # noqa: E402
import eval_icebreakers as EI                       # noqa: E402
import eval_replies as ER                           # noqa: E402
import eval_sending as ES                           # noqa: E402

BANNED = ["icypeas", "millionverifier", "million verifier", "anymailfinder", "instantly",
          "northwind outsourcing", "northwind –", "northwind -", "fabrikam", "contoso", "nick", "fieldmap.", ".json", "shaheryar"]
# 2026-11-07, his order: Find email on all 12, research only the 8 with an email (6 sites
# read), all 8 get an ice breaker (2 from the Default line), 7 sent, 1 held
EXPECT = {"leads": 12, "websites": 6, "emails": 8, "sent": 7, "interested": 1}
CHAIN = [("find", 12), ("research", 8), ("ice", 8), ("email", 8), ("send", 8), ("replies", 5)]


def _sandbox():
    tmp = Path(tempfile.mkdtemp(prefix="demo3-"))
    S.STACK_DB = tmp / "stack.db"
    return tmp


def _no_banned(obj, where):
    text = json.dumps(obj, ensure_ascii=False).lower()
    for w in BANNED:
        assert w not in text, (where, w)


def _run_now():
    slept = []
    r = S.stack_demo_start(countdown=0, pace=0, waits=(0, 0, 0), wait=True, sleep=slept.append)
    assert r["ok"], r
    return S.stack_demo_status()


def _fingerprint(d):
    return ([(c["key"], c["n"], c["state"]) for c in d["chain"]],
            [(x["key"], x["website"]["value"], x["email"]["value"], x["ice"]["value"], x["template"],
              x["sent"]["value"], x["reply"]["value"]) for x in d["leads"]],
            {k: d["result"][k] for k in EXPECT})


def check_status_before_any_run():
    _sandbox()
    d = S.stack_demo_status()
    assert d["run"] is None and d["total"] == 12 and all(c["state"] == "pending" for c in d["chain"]), d["chain"]


def check_one_trigger_runs_steps_1_to_6_and_reads_back_the_engine_values():
    _sandbox()
    d = _run_now()
    assert d["run"]["state"] == "done" and d["progress"] == 100, d["run"]
    assert [(c["key"], c["n"]) for c in d["chain"]] == CHAIN, d["chain"]
    assert {k: d["result"][k] for k in EXPECT} == EXPECT, d["result"]
    assert d["result"]["would_cost"] > 0          # what it WOULD cost; the demo itself is $0
    leads = {x["key"]: x for x in d["leads"]}
    assert {k: x["ice"]["value"] for k, x in leads.items() if x["ice"]["value"]} == EI.ICE_STATUS
    assert {k: x["sent"]["value"] for k, x in leads.items() if x["sent"]["value"]} == ES.PUSH_STATUS
    assert {k: x["template"] for k, x in leads.items() if x["template"]} == ES.TEMPLATE
    assert {k: x["reply"]["value"] for k, x in leads.items() if x["reply"]["value"]} == ER.REPLY_STATUS
    runs = S._stack_store().runs("demo")
    assert len(runs) == 1 and runs[0]["trigger"] == "Live demo", runs   # ONE trigger, one run


def check_the_same_result_every_run():
    _sandbox()
    a = _fingerprint(_run_now())
    b = _fingerprint(_run_now())
    assert a == b


def check_health_fixed_the_known_issues_by_itself():
    _sandbox()
    d = _run_now()
    texts = [e["text"] for e in reversed(d["run"]["events"])]
    i = texts.index("Find email: sheet write limit reached, result not saved yet")
    assert texts[i + 2] == "Health agent: result saved. Resolved automatically.", texts[i:i + 3]
    h = S.stack_health()
    assert h["tiles"] == {"issues": 2, "resolved": 2, "waiting": 0}, h["tiles"]
    assert sorted(x["step"] for x in h["log"]) == ["Find email", "Website research"], h["log"]
    assert all(x["result"] == "resolved" for x in h["log"])
    s = h["summary"]
    assert s and s["lines"][0] == "Issues: 2 · Resolved automatically: 2 · Waiting for you: 0", s
    assert "1 interested reply" in s["lines"][1] and "template" in s["lines"][1], s["lines"]


def check_home_decisions_list_the_interested_reply_and_the_draft():
    _sandbox()
    _run_now()
    d = S.stack_decisions()
    kinds = [x["kind"] for x in d["decisions"]]
    assert kinds == ["reply", "template"], d["decisions"]
    rep = d["decisions"][0]
    assert rep["text"].endswith("replied: interested") and rep["href"].startswith("/replies?open="), rep
    rid = int(rep["href"].split("=")[1])
    S.stack_replies_update("demo", rid, handled=True)
    assert [x["kind"] for x in S.stack_decisions()["decisions"]] == ["template"]


def check_the_trigger_waits_its_countdown_then_fires_by_itself():
    _sandbox()
    r = S.stack_demo_start(countdown=0.6, pace=0, waits=(0,))
    assert r["ok"], r
    d = S.stack_demo_status()
    assert d["run"]["state"] == "scheduled" and d["run"]["seconds_left"] >= 1, d["run"]
    rows = S.stack_schedules()["rows"]
    assert rows[0]["step"].startswith("Pipeline run") and rows[0]["schedule"].startswith("Once at "), rows[0]
    busy =S._start_chain(S._stack_store(), "x", ["research"])
    assert not busy["ok"] and "already" in busy["error"], busy
    end = time.time() + 15
    while time.time() < end and S.stack_demo_status()["run"]["state"] != "done":
        time.sleep(0.1)
    assert S.stack_demo_status()["run"]["state"] == "done"
    assert S.stack_schedules()["rows"][0]["step"] == "1 · Find email"


def check_reset_stops_a_countdown():
    _sandbox()
    S.stack_demo_start(countdown=5, pace=0, waits=(0,))
    S.stack_reset_demo()
    time.sleep(0.2)
    d = S.stack_demo_status()
    assert d["run"] is None and not S._STACK_ALIVE and not S._STACK_TIMERS, (d["run"], S._STACK_ALIVE)


def check_live_demo_mode_hides_real_names():
    _sandbox()
    assert S.stack_presenting_get()["on"] is False
    S.stack_presenting_set(True)
    try:
        # 2026-11-06: the switch is now "Privacy"; the pipeline campaigns (the showcase, real US
        # firms nobody targets) stay listed on purpose, every client campaign is hidden
        shown = ["demo"] + [f"campaign:{c.id}" for c in S._pipeline_camps()]
        p = S.stack_pickers()
        assert [x["id"] for x in p["pickers"]] == shown and "hidden" in p, p
        src = S.stack_sources()
        assert [x["id"] for x in src["sources"]] == shown and "hidden" in src, src
        r = S.stack_leads("campaign:anything")
        assert "Privacy" in r["error"], r
        S.stack_reset_demo()
        assert S.stack_presenting_get()["on"] is True       # a demo reset keeps the switch
    finally:
        S.stack_presenting_set(False)


def check_no_brand_or_service_name_on_the_new_screens():
    _sandbox()
    _run_now()
    for name, body in (("status", S.stack_demo_status()), ("health", S.stack_health()),
                       ("schedules", S.stack_schedules()), ("decisions", S.stack_decisions())):
        _no_banned(body, name)


CHECKS = [check_status_before_any_run, check_one_trigger_runs_steps_1_to_6_and_reads_back_the_engine_values,
          check_the_same_result_every_run, check_health_fixed_the_known_issues_by_itself,
          check_home_decisions_list_the_interested_reply_and_the_draft,
          check_the_trigger_waits_its_countdown_then_fires_by_itself, check_reset_stops_a_countdown,
          check_live_demo_mode_hides_real_names, check_no_brand_or_service_name_on_the_new_screens]


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
