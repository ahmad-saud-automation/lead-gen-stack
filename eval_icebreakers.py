"""
eval_icebreakers.py — step 3, Ice breakers (core/icebreakers.py), on the 12 demo firms.

Failed before 2026-11-06 (build session 2): core/icebreakers.py did not exist.

What must hold:
  * the first matching rung wins, top to bottom; a rung that is off is skipped
  * every lead with a usable email that Website research has looked at is written; no
    matching rung, a dead or blocked site, or no facts -> the Default line (his rule,
    2026-11-07; before it they got `no_facts` and were held); leads with no address are
    not touched
  * the step writes ONLY `icebreaker_status` (never `Status`, never another step's column)
  * a pushed lead is never rewritten (the already-emailed guard)
  * the A/B shared-ground line and the default versions are given out evenly
  * the same input gives the same lines every time ($0, no outside call)

Run:  python eval_icebreakers.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from core import demo_services as D                 # noqa: E402
from core import fieldmap as FM                     # noqa: E402
from core import find_email as F                    # noqa: E402
from core import icebreakers as ICE                 # noqa: E402
from core import lead_record as LR                  # noqa: E402
from core import recipe as RC                       # noqa: E402
from core import research as R                      # noqa: E402
from core import store as S                         # noqa: E402

# what the demo must give, step by step (also read back by eval_stack_steps + the screen check)
ICE_STATUS = {"DM-001": "written", "DM-002": "written", "DM-003": "written", "DM-004": "written",
              "DM-005": "written", "DM-007": "written", "DM-008": "written", "DM-012": "written"}
RUNG = {"DM-001": "Open role", "DM-002": "Article or case study", "DM-003": "Award",
        "DM-004": "Sectors served", "DM-005": "Article or case study", "DM-007": "Default",
        "DM-008": "Default", "DM-012": "Award"}
LINE_001 = ("I noticed Harbour & Vale is hiring a payroll administrator. We work inside UK practice files "
            "every week, and in our experience that usually means client work is growing faster than the team.")


def ruleset() -> dict:
    return json.loads(Path(D.RULESET_FILE).read_text(encoding="utf-8"))


def prepared():
    """A throwaway store with Find email (every lead) then Website research (leads with an
    email) already run on the demo."""
    st = S.Store(Path(tempfile.mkdtemp(prefix="ice-")) / "stack.db")
    fm = FM.load(D.DEMO_FIELDMAP)
    rows = D.demo_rows()
    svc = D.DemoServices()
    key = fm.header("row_key") or "lead_id"
    rec = RC.Recipe(json.loads(Path(D.DEMO_RECIPE).read_text(encoding="utf-8")))
    F.run(st.overlay(rows, "demo", key), fm, rec, st, "demo", svc.verify, svc.find)
    mailed = [r for r in st.overlay(rows, "demo", key) if r.get("email_status") in ICE.USABLE_EMAIL]
    R.run(mailed, fm, st, "demo", svc.fetch)
    return st, fm, rows


def check_every_lead_with_an_email_gets_a_line():
    """8 leads have an email: 6 match a rung, the dead site (DM-007) and the blocked one
    (DM-008) get the Default line. Failed before 2026-11-07: those two got `no_facts`."""
    st, fm, rows = prepared()
    r = ICE.run(rows, fm, st, "demo", ruleset())
    assert (r["processed"], r["written"], r["default"], r["no_facts"], r["failed"]) == (8, 8, 2, 0, 0), r
    got = {k: v["icebreaker_status"] for k, v in st.statuses("demo").items() if v.get("icebreaker_status")}
    assert got == ICE_STATUS, got
    rungs = {k: v["rung_name"] for k, v in st.icebreakers("demo").items()}
    assert rungs == RUNG, rungs
    assert st.icebreakers("demo")["DM-001"]["line"] == LINE_001, st.icebreakers("demo")["DM-001"]["line"]


def check_same_result_every_time():
    a = prepared()
    b = prepared()
    ICE.run(a[2], a[1], a[0], "demo", ruleset())
    ICE.run(b[2], b[1], b[0], "demo", ruleset())
    la = {k: v["line"] for k, v in a[0].icebreakers("demo").items()}
    lb = {k: v["line"] for k, v in b[0].icebreakers("demo").items()}
    assert la == lb and len(la) == 8


def check_an_old_no_facts_lead_is_written_with_the_default():
    """A lead an older run stored as `no_facts` is not held for ever: the next run gives it
    the Default line. Failed before 2026-11-07: `no_facts` was final."""
    st, fm, rows = prepared()
    st.write_status("icebreakers", "demo", "DM-007", {"icebreaker_status": "no_facts"})
    s = {c: (st.statuses("demo").get("DM-007") or {}).get(c, "") for c in LR.COLUMNS}
    assert ICE.lead_state(s, False) == "waiting", ICE.lead_state(s, False)
    ICE.run(rows, fm, st, "demo", ruleset())
    assert st.statuses("demo")["DM-007"]["icebreaker_status"] == "written"
    assert st.icebreakers("demo")["DM-007"]["rung_name"] == "Default"


def check_writes_only_its_own_column():
    st, fm, rows = prepared()
    before = {k: {c: v for c, v in d.items() if c != "icebreaker_status"} for k, d in st.statuses("demo").items()}
    ICE.run(rows, fm, st, "demo", ruleset())
    after = {k: {c: v for c, v in d.items() if c != "icebreaker_status"} for k, d in st.statuses("demo").items()}
    assert before == after, "another step's column changed"
    assert LR.allowed("icebreakers") == ("icebreaker_status",)
    for bad in ("Status", "push_status", "email_status"):
        try:
            LR.stage_update("icebreakers", {bad: "written"})
        except LR.WriteRefused:
            continue
        raise AssertionError(f"icebreakers was allowed to write {bad}")


def check_first_matching_rung_wins_and_off_rungs_are_skipped():
    rs = ruleset()
    facts = {"vacancies": [{"title": "Tax Senior"}], "awards": [{"name": "Practice of the Year"}]}
    rung, item, _ = ICE.pick(facts, rs)
    assert rung["name"] == "Open role" and item == "tax senior", (rung, item)
    rs["rungs"][0]["on"] = False
    rung, item, _ = ICE.pick(facts, rs)
    assert rung["name"] == "Award" and item == "Practice of the Year", (rung, item)
    rung, _, _ = ICE.pick({"reviews": [{"quote": "great"}]}, rs)
    assert rung is None, "no rung matches, so the default is used"


def check_a_pushed_lead_is_never_rewritten():
    st, fm, rows = prepared()
    ICE.run(rows, fm, st, "demo", ruleset())
    st.write_status("sending", "demo", "DM-001", {"push_status": "pushed"})
    old = st.icebreakers("demo")["DM-001"]["line"]
    rs = ruleset()
    rs["rungs"][0]["implication"] = "something else entirely"
    r = ICE.run(rows, fm, st, "demo", rs, keys=["DM-001"], rewrite=True)
    assert r["skipped_sent"] == 1 and r["written"] == 0, r
    assert st.icebreakers("demo")["DM-001"]["line"] == old


def check_rewrite_selected_uses_the_new_rules():
    st, fm, rows = prepared()
    ICE.run(rows, fm, st, "demo", ruleset())
    rs = ruleset()
    rs["rungs"][0]["implication"] = "the team is stretched"
    r = ICE.run(rows, fm, st, "demo", rs, keys=["DM-001"], rewrite=True)
    assert r["written"] == 1, r
    assert st.icebreakers("demo")["DM-001"]["line"].endswith("the team is stretched."), st.icebreakers("demo")["DM-001"]
    assert st.icebreakers("demo")["DM-012"]["rung_name"] == "Award", "other leads are untouched"


def check_shared_ground_and_default_are_given_out_evenly():
    st, fm, rows = prepared()
    rs = ruleset()
    for r in rs["rungs"]:
        r["on"] = False
    rs["rungs"][0]["on"] = True            # only "Open role": DM-001 matches, the rest use the default
    ICE.run(rows, fm, st, "demo", rs)
    lines = st.icebreakers("demo")
    grounds = [v["shared_ground"] for v in lines.values()]
    assert abs(grounds.count(0) - grounds.count(1)) <= 1, grounds
    dv = [v["default_version"] for v in lines.values() if v["rung"] == "default"]
    assert len(dv) == 7 and max(dv.count(i) for i in range(3)) - min(dv.count(i) for i in range(3)) <= 1, dv


def check_short_company_and_first_name():
    assert ICE.short_company("Westbury Tax & Accounts") == "Westbury"
    assert ICE.short_company("Harbour & Vale Accountants") == "Harbour & Vale"
    assert ICE.short_company("Brookfield Ledger Ltd") == "Brookfield"
    assert ICE.short_company("Ashby Clarke LLP") == "Ashby Clarke"
    assert ICE.first_name("Emma Clarke") == ("Emma", "")
    assert ICE.first_name("Dr Anil Agrawal")[0] == "" and ICE.first_name("Dr Anil Agrawal")[1]
    assert ICE.first_name("")[1] == "No contact name"


def check_a_broken_rule_set_is_refused_in_plain_words():
    rs = ruleset()
    rs["rungs"][0]["fact"] = "is hiring"
    try:
        ICE.validate(rs)
    except ICE.RuleSetError as e:
        assert "{item}" in str(e)
    else:
        raise AssertionError("a fact without {item} was accepted")
    rs = ruleset()
    rs["rungs"][1]["source"] = "horoscope"
    try:
        ICE.validate(rs)
    except ICE.RuleSetError:
        pass
    else:
        raise AssertionError("an unknown fact source was accepted")


CHECKS = [check_every_lead_with_an_email_gets_a_line, check_same_result_every_time,
          check_an_old_no_facts_lead_is_written_with_the_default,
          check_writes_only_its_own_column, check_first_matching_rung_wins_and_off_rungs_are_skipped,
          check_a_pushed_lead_is_never_rewritten, check_rewrite_selected_uses_the_new_rules,
          check_shared_ground_and_default_are_given_out_evenly, check_short_company_and_first_name,
          check_a_broken_rule_set_is_refused_in_plain_words]


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
