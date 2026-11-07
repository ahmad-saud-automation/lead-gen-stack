"""
eval_campaign_pipeline.py — a 6-step campaign is driven by ITS OWN campaign page (2026-11-07,
his words: "I make the campaign, set its lead sheet, set the leads per run, put it on a
schedule, and it follows the schedule. A lead that already has an email and an ice breaker
is not run through the pipeline: it is pushed directly.").

Failed before 2026-11-07:
  * the run took the RECIPE's per-run number; the page's "Leads per run" (shown as 50) and its
    per-day limit, spend limit and filters were ignored
  * the campaign's Run button started the OLD engine run, and its "Run by itself" schedule
    never started the 6 steps (the campaign was kept switched off on purpose)
  * a lead whose sheet already had an ice breaker was researched and given a new line

All offline: a throwaway database, stand-in chain starter, no sheet, no outside call.

Run:  python eval_campaign_pipeline.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))
import server as S                                  # noqa: E402
from core import campaigns as C                     # noqa: E402
from core import demo_services as D                 # noqa: E402
from core import fieldmap as FM                     # noqa: E402
from core import find_email as F                    # noqa: E402
from core import icebreakers as ICE                 # noqa: E402
from core import recipe as RC                       # noqa: E402
from core import sending as SEND                    # noqa: E402
from core import stack_view as SV                   # noqa: E402
from core import store as ST                        # noqa: E402

SRC = "campaign:t"


def _camp(**raw):
    base = {"id": "t", "name": "Test firms", "enabled": True, "pipeline": True, "tab": "Firms",
            "instantly": {"campaign_id": "draft-1"}, "limits": {"per_run": 3, "per_day": 0, "max_spend_usd": 1}}
    base.update(raw)
    return C.Campaign(base)


def _store():
    return ST.Store(Path(tempfile.mkdtemp(prefix="cpipe-")) / "stack.db")


def _capture(monkey: dict):
    """Swap the chain starter for a recorder; returns the list of calls."""
    calls = []

    def fake(st, trigger, keys, **kw):
        calls.append({"trigger": trigger, "keys": keys, **kw})
        return {"ok": True, "run_id": "r1"}
    monkey["_start_chain"] = S._start_chain
    S._start_chain = fake
    return calls


def _restore(monkey: dict):
    for k, v in monkey.items():
        setattr(S, k, v)


# ── the page's "How many" ──────────────────────────────────────────────

def check_leads_per_run_comes_from_the_campaign_page():
    st = _store()
    assert S._campaign_room(_camp(), st, SRC) == (3, "")
    assert S._campaign_room(_camp(limits={"per_run": 7, "per_day": 0}), st, SRC) == (7, "")
    n, why = S._campaign_room(_camp(limits={"per_run": 0}), st, SRC)
    assert n == 0 and "Leads per run" in why, why


def check_leads_per_day_counts_what_today_already_took():
    st = _store()
    for i in range(4):
        st.save_email_result(SRC, f"k{i}", {"company": f"F{i}"})
    camp = _camp(limits={"per_run": 3, "per_day": 5})
    assert S._campaign_room(camp, st, SRC) == (1, "")          # 5 a day, 4 done: room for 1
    st.save_email_result(SRC, "k9", {"company": "F9"})
    n, why = S._campaign_room(camp, st, SRC)
    assert n == 0 and "Today's limit is reached (5 of 5" in why, why
    assert S._campaign_room(camp, st, SRC, today=date(2000, 1, 1)) == (3, "")   # another day


def check_the_spend_limit_stops_before_the_next_lead():
    st = _store()
    fm = FM.load(D.DEMO_FIELDMAP)
    rows = st.overlay(D.demo_rows(), "demo", fm.header("row_key") or "lead_id")
    rec = RC.Recipe(json.loads(Path(D.DEMO_RECIPE).read_text(encoding="utf-8")))
    svc = D.DemoServices()
    r = F.run(rows, fm, rec, st, "demo", svc.verify, svc.find, budget=0.5, spent=lambda: 0.5)
    assert r["processed"] == 0 and r["stopped_at_budget"] is True, r
    r = F.run(rows, fm, rec, st, "demo", svc.verify, svc.find, limit=2, budget=0.5, spent=lambda: 0.0)
    assert r["processed"] == 2 and r["stopped_at_budget"] is False, r


def check_the_who_filters_apply_to_the_pipeline():
    fm = FM.FieldMap({"row_key": "lead_id", "company_name": "company"})
    rows = [{"lead_id": "1", "company": "Smith CPA", "town": "Miami"},
            {"lead_id": "2", "company": "Jones Tax", "town": "Boston"}]
    camp = _camp(rules={"all": [{"field": "town", "op": "equals", "value": "Miami"}]})
    got = S._campaign_filter(camp, rows, fm)
    assert [r["lead_id"] for r in got] == ["1"], got
    assert len(S._campaign_filter(_camp(), rows, fm)) == 2


# ── Run now and the campaign's own schedule ───────────────────────────

def check_run_now_starts_all_six_steps_on_the_campaign():
    m = {}
    calls = _capture(m)
    try:
        r = S.start_pipeline_campaign(_camp(), trigger=S.RUN_NOW_TRIGGER)
        assert r == {"run_id": "r1", "pipeline": True, "source": SRC}, r
        assert calls[0]["keys"] == list(S.ssched_mod.STEP_KEYS) and calls[0]["source"] == SRC, calls
        assert calls[0]["trigger"] == S.RUN_NOW_TRIGGER and S.RUN_NOW_TRIGGER in S.RUN_TRIGGERS
    finally:
        _restore(m)


def check_run_now_refuses_a_test_an_off_campaign_and_no_instantly():
    m = {}
    calls = _capture(m)
    try:
        assert "no free test" in S.start_pipeline_campaign(_camp(), trigger="x", test_mode=True)["error"]
        assert "switched off" in S.start_pipeline_campaign(_camp(enabled=False), trigger="x")["error"]
        assert "no Instantly campaign" in S.start_pipeline_campaign(_camp(instantly={}), trigger="x")["error"]
        assert not calls
    finally:
        _restore(m)


def check_the_campaign_schedule_runs_the_six_steps():
    """fire_lane is what the app clock and the Windows task call. A test-mode flag left on an
    old schedule does not matter: the pipeline only ever pushes to a Draft."""
    m = {}
    calls = _capture(m)
    m["_sched_log"] = S._sched_log
    S._sched_log = lambda *_a, **_k: None
    try:
        r = S.fire_lane(_camp(), test_mode=True)
        assert r.get("run_id") == "r1" and calls[0]["trigger"] == S.SCHEDULED_TRIGGER, (r, calls)
        assert S.SCHEDULED_TRIGGER in S.RUN_TRIGGERS
    finally:
        _restore(m)


def check_the_campaign_run_button_goes_to_the_pipeline():
    m = {"runner_mod": S.runner_mod}
    calls = _capture(m)

    class Loader:
        def load_config_dir(self, _d):
            return {"campaigns": [_camp()], "globals": {}, "fieldmaps": {}}

        def __getattr__(self, name):
            return getattr(m["runner_mod"], name)
    S.runner_mod = Loader()
    try:
        r = S.start_campaign_run("t", test_mode=False)
        assert r.get("pipeline") is True and calls and calls[0]["source"] == SRC, (r, calls)
    finally:
        _restore(m)


# ── a lead that already has everything goes straight to Sending ────────

def _ready_lead_store():
    st = _store()
    fm = FM.FieldMap({"row_key": "lead_id", "company_name": "company", "icebreaker": "Ice Breaker"})
    rows = [{"lead_id": "1", "company": "Smith CPA", "Ice Breaker": "Saw your new Miami office."},
            {"lead_id": "2", "company": "Jones Tax", "Ice Breaker": ""}]
    for k in ("1", "2"):
        st.write_status("find_email", SRC, k, {"email_status": "as-is"})
        st.save_email_result(SRC, k, {"company": "x", "email": f"owner{k}@firm{k}.com", "contact": "Sarah Jones"})
    return st, fm, rows


def check_a_sheet_ice_breaker_is_used_and_never_researched():
    st, fm, rows = _ready_lead_store()
    rs = json.loads(Path(D.RULESET_FILE).read_text(encoding="utf-8"))
    view = SV.research_view(rows, fm, st, SRC)
    assert view["to_research"] == 1, view["to_research"]          # only lead 2 waits for research
    r = ICE.run(rows, fm, st, SRC, rs)
    assert (r["written"], r["from_sheet"]) == (1, 1), r             # lead 2 is not researched yet
    line = st.icebreakers(SRC)["1"]
    assert line["line"] == "Saw your new Miami office." and line["rung_name"] == "From your sheet", line


def check_a_lead_with_email_and_ice_breaker_is_ready_to_push():
    st, fm, rows = _ready_lead_store()
    ICE.run(rows, fm, st, SRC, json.loads(Path(D.RULESET_FILE).read_text(encoding="utf-8")))
    plan = {x["key"]: x for x in SEND.plan(rows, fm, st, SRC)}
    assert plan["1"]["state"] == "queued" and plan["1"]["line"] == "Saw your new Miami office.", plan["1"]
    assert plan["2"]["state"] == "held", plan["2"]                  # no line yet: the pipeline runs for it


# ── results go back to the campaign's sheet (2026-11-07) ──────────────

def _wb_store():
    st, fm, rows = _ready_lead_store()
    ICE.run(rows, fm, st, SRC, json.loads(Path(D.RULESET_FILE).read_text(encoding="utf-8")))
    st.write_status("find_email", SRC, "3", {"email_status": "no_person"})
    st.save_push(SRC, "1", {"state": "pushed", "pushed_on": "2026-11-07 18:30:00", "email": "owner1@firm1.com"})
    st.write_status("sending", SRC, "1", {"push_status": "pushed"})
    return st, fm


def check_writeback_fills_empty_cells_and_adds_missing_columns():
    from core import sheet_writeback as W
    st, fm = _wb_store()
    header = ["lead_id", "company", "Ice Breaker", "Status"]
    rows = [{"lead_id": "1", "company": "Smith CPA", "Ice Breaker": "Saw your new Miami office.", "Status": ""},
            {"lead_id": "2", "company": "Jones Tax", "Ice Breaker": "", "Status": ""},
            {"lead_id": "3", "company": "Lee & Co", "Ice Breaker": "", "Status": ""},
            {"lead_id": "4", "company": "Never run", "Ice Breaker": "", "Status": ""}]
    p = W.plan(header, rows, fm, st, SRC)
    assert p["add"] == ["Found Email"], p["add"]
    cells = {(i, h): v for i, h, v in p["cells"]}
    assert cells[(0, "Found Email")] == "owner1@firm1.com"
    assert (0, "Ice Breaker") not in cells                       # his own line is never overwritten
    assert cells[(0, "Status")] == "Added to Instantly (Draft) 2026-11-07"
    assert cells[(1, "Found Email")] == "owner2@firm2.com" and (1, "Ice Breaker") not in cells   # no line yet
    assert cells[(2, "Status")] == "No email found"
    assert not any(i == 3 for i, _h in cells), cells             # a lead the pipeline never ran: untouched


def check_writeback_never_overwrites_what_a_person_typed():
    from core import sheet_writeback as W
    st, fm = _wb_store()
    header = ["lead_id", "company", "Ice Breaker", "Status", "Found Email"]
    rows = [{"lead_id": "1", "company": "Smith CPA", "Ice Breaker": "x", "Status": "Called him, not now",
             "Found Email": "typed@by.hand"},
            {"lead_id": "3", "company": "Lee & Co", "Ice Breaker": "", "Status": "Held: No ice breaker yet",
             "Found Email": ""}]
    cells = {(i, h): v for i, h, v in W.plan(header, rows, fm, st, SRC)["cells"]}
    assert (0, "Found Email") not in cells and (0, "Status") not in cells, cells   # his words stay
    assert cells[(1, "Status")] == "No email found"              # its own earlier words may change
    assert W.col_letter(0) == "A" and W.col_letter(25) == "Z" and W.col_letter(26) == "AA"


def check_writeback_writes_one_batch_to_the_sheet():
    from core import sheet_writeback as W
    st, fm = _wb_store()
    sent = []

    class Call:
        def __init__(self, fn):
            self.fn = fn

        def execute(self):
            return self.fn()

    class Svc:
        def spreadsheets(self):
            return self

        def values(self):
            return self

        def get(self, **kw):
            return Call(lambda: {"sheets": [{"properties": {"title": "Firms", "sheetId": 7,
                                                            "gridProperties": {"columnCount": 26}}}]})

        def batchUpdate(self, **kw):
            sent.append(kw["body"])
            return Call(lambda: {})

    class Client:
        _svc = Svc()

        def _header(self, *_a):
            return ["lead_id", "company"]

        def read(self, *_a):
            return [{"lead_id": "1", "company": "Smith CPA"}, {"lead_id": "2", "company": "Jones Tax"}]
    r = W.apply(Client(), "doc", "Firms", fm, st, SRC)
    assert r["ok"] and r["added_columns"] == ["Found Email", "Ice Breaker", "Status"], r
    ranges = {d["range"]: d["values"][0][0] for d in sent[-1]["data"]}
    assert ranges["'Firms'!C1"] == "Found Email" and ranges["'Firms'!C2"] == "owner1@firm1.com", ranges
    assert ranges["'Firms'!E2"] == "Added to Instantly (Draft) 2026-11-07", ranges


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_")]

if __name__ == "__main__":
    bad = 0
    for fn in CHECKS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL  {fn.__name__}: {e!r}")
    print(f"{len(CHECKS) - bad}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)
