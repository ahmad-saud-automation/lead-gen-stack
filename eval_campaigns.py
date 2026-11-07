"""
eval_campaigns.py - offline test for many-campaigns-off-one-sheet (no network, no keys).
    python eval_campaigns.py   /   pytest eval_campaigns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from core import campaigns as C
from core.fieldmap import FieldMap

FM = FieldMap({"status": "Status", "send_gate": "send_ready", "employees": "Employees",
               "seniority_rank": "seniority_label", "row_key": "lead_id"})


def _camp(cid, **kw):
    base = {"id": cid, "name": cid, "enabled": True, "tab": "Practices",
            "limits": {"per_run": 50, "per_day": 100, "max_spend_usd": 5.0}}
    base.update(kw)
    return C.Campaign(base)


def _rows(n, **fixed):
    out = []
    for i in range(n):
        r = {"lead_id": f"P-{i}", "Status": "", "send_ready": "yes", "Employees": "5",
             "seniority_label": "owner"}
        r.update(fixed)
        out.append(r)
    return out


def check_the_live_config_is_safe():
    """`config/campaigns.json` is LIVE configuration, not a shipped default, so a lane
    being enabled is expected. What must never be true is a lane that can act without a
    destination, or one that sends unattended before it has been proven by hand."""
    live = Path(__file__).parent / "config" / "campaigns.json"
    if not live.exists():  # gitignored; a fresh clone has none until you copy the example
        print("  skipped: no live config/campaigns.json")
        return
    camps, g = C.load(live)
    assert camps, "no campaigns configured"
    assert C.validate(camps) == [], C.validate(camps)
    assert g.get("daily_push_cap", 0) > 0, "a global daily send cap must be set"
    assert g.get("daily_spend_cap_usd", 0) > 0, "a global daily spend cap must be set"

    for c in camps:
        if c.enabled:
            # an enabled lane with no target cannot push; the plan warns, but catching it
            # here means a scheduled run can never quietly do nothing
            assert c.instantly_campaign_id, \
                f"'{c.id}' is enabled but has no instantly.campaign_id"
        if c.auto_push:
            assert c.enabled and c.instantly_campaign_id, \
                f"'{c.id}' auto-pushes but is not fully configured"
            assert c.per_day, f"'{c.id}' auto-pushes with no per_day limit"


def check_validate_catches_the_expensive_mistakes():
    dupe_id = [_camp("a"), _camp("a")]
    assert any("duplicate campaign id" in i["issue"] for i in C.validate(dupe_id))

    # several lanes may share one Instantly campaign: the default labels send `campaign`
    same_target = [_camp("a", instantly={"campaign_id": "X"}),
                   _camp("b", instantly={"campaign_id": "X"})]
    assert C.validate(same_target) == [], C.validate(same_target)

    # ...but not when a hand-written label table drops it — then the lanes blur together
    no_lane_label = [_camp("a", instantly={"campaign_id": "X"}),
                     _camp("b", instantly={"campaign_id": "X"},
                           labels=[{"send_as": "trigger_family", "type": "column",
                                    "source": "trigger_family"}])]
    issues = C.validate(no_lane_label)
    assert [i["campaign"] for i in issues] == ["b"], issues
    assert "do not send 'campaign'" in issues[0]["issue"], issues

    # the same table is fine on a lane that has its Instantly campaign to itself
    alone = [no_lane_label[1], _camp("c", instantly={"campaign_id": "Y"})]
    assert C.validate(alone) == [], C.validate(alone)

    no_tab = [_camp("a", tab="")]
    assert any("no 'tab'" in i["issue"] for i in C.validate(no_tab))

    over = [_camp("a", limits={"per_run": 200, "per_day": 100})]
    assert any("larger than" in i["issue"] for i in C.validate(over)), C.validate(over)

    zero = [_camp("a", limits={"per_run": 0})]
    assert any("never take a row" in i["issue"] for i in C.validate(zero))


def check_missing_instantly_id_only_blocks_a_live_push():
    c = [_camp("a")]
    assert C.validate(c) == []                                  # fine while planning
    assert any("live push needs one" in i["issue"]
               for i in C.validate(c, require_push_target=True))


def check_one_firm_one_campaign():
    """Two lanes both WANT every row. Priority decides, and no row is ever in both."""
    rows = _rows(10)
    lanes = [_camp("second", priority=20), _camp("first", priority=10)]
    a = C.assign(rows, lanes, FM)
    assert len(a["claimed"]["first"]) == 10, a["claimed"]
    assert a["claimed"]["second"] == [], a["claimed"]
    keys = [r["lead_id"] for r in a["claimed"]["first"]]
    assert len(set(keys)) == 10


def check_assign_records_the_leftovers_and_why():
    rows = _rows(4) + _rows(3, send_ready="no")
    lane = _camp("only", rules={"all": [{"field": "send_gate", "op": "equals", "value": "yes"}]})
    a = C.assign(rows, [lane], FM)
    assert len(a["claimed"]["only"]) == 4
    assert len(a["unclaimed"]) == 3
    assert any("send_gate" in k for k in a["reasons"]), a["reasons"]


def check_disabled_campaigns_are_skipped_by_default():
    rows = _rows(5)
    lanes = [_camp("off", enabled=False)]
    assert C.assign(rows, lanes, FM)["claimed"] == {}
    assert len(C.assign(rows, lanes, FM, enabled_only=False)["claimed"]["off"]) == 5


def check_select_filters_sorts_and_caps():
    rows = (_rows(3, Employees="5", seniority_label="partner")
            + _rows(3, Employees="40", seniority_label="owner"))
    lane = _camp("s",
                 rules={"all": [{"field": "employees", "op": "between", "value": [2, 10]}]},
                 order=[{"field": "seniority_rank", "order": ["owner", "partner"]}],
                 limits={"per_run": 2, "per_day": 100})
    got = C.select(rows, lane, FM)
    assert len(got) == 2, len(got)                          # capped by per_run
    assert all(r["Employees"] == "5" for r in got), got     # rules applied


def check_plan_counts_and_spends_nothing():
    rows = _rows(400) + _rows(100, Employees="40")
    lanes = [_camp("micro", rules={"all": [{"field": "employees", "op": "between",
                                            "value": [2, 10]}]}),
             _camp("big", priority=20,
                   rules={"all": [{"field": "employees", "op": "between", "value": [11, 50]}]})]
    rep = C.plan({"Practices": rows}, lanes, {"Practices": FM}, mv_rate_usd=0.00178)
    by = {r["campaign"]: r for r in rep["campaigns"]}
    assert by["micro"]["matched"] == 400, by["micro"]
    assert by["big"]["matched"] == 100, by["big"]
    assert by["micro"]["take_this_run"] == 50                # per_run
    # 50 leads x ~2 verifications x $0.00178
    assert abs(by["micro"]["estimated_spend_usd"] - 0.178) < 0.001, by["micro"]
    assert rep["total_take"] == 100


def check_plan_warns_below_the_decision_floor():
    """Under 300 leads the decision agent refuses to call a result. Saying so up front is
    the whole point of the preview."""
    rep = C.plan({"Practices": _rows(120)}, [_camp("small")], {"Practices": FM})
    w = " | ".join(rep["campaigns"][0]["warnings"])
    assert "under the 300" in w, w


def check_plan_warns_when_nothing_matches():
    lane = _camp("none", rules={"all": [{"field": "employees", "op": "gt", "value": 999}]})
    rep = C.plan({"Practices": _rows(50)}, [lane], {"Practices": FM})
    w = " | ".join(rep["campaigns"][0]["warnings"])
    assert "no rows match" in w, w


def check_plan_warns_over_the_global_daily_cap():
    lanes = [_camp(f"c{i}", priority=i,
                   rules={"all": [{"field": "row_key", "op": "contains", "value": f"-{i}"}]},
                   limits={"per_run": 50, "per_day": 100}) for i in range(4)]
    rep = C.plan({"Practices": _rows(400)}, lanes, {"Practices": FM},
                 globals_cfg={"daily_push_cap": 60})
    assert any("global daily cap" in w for w in rep["warnings"]), rep["warnings"]


def check_campaign_tag_falls_back_to_the_id():
    assert _camp("abc").campaign_tag() == "abc"
    assert _camp("abc", writeback={"campaign_type": "Northwind-1"}).campaign_tag() == "Northwind-1"


CHECKS = [check_the_live_config_is_safe, check_validate_catches_the_expensive_mistakes,
          check_missing_instantly_id_only_blocks_a_live_push, check_one_firm_one_campaign,
          check_assign_records_the_leftovers_and_why,
          check_disabled_campaigns_are_skipped_by_default, check_select_filters_sorts_and_caps,
          check_plan_counts_and_spends_nothing, check_plan_warns_below_the_decision_floor,
          check_plan_warns_when_nothing_matches, check_plan_warns_over_the_global_daily_cap,
          check_campaign_tag_falls_back_to_the_id]


def test_live_config(): check_the_live_config_is_safe()
def test_validate(): check_validate_catches_the_expensive_mistakes()
def test_push_target(): check_missing_instantly_id_only_blocks_a_live_push()
def test_one_firm(): check_one_firm_one_campaign()
def test_leftovers(): check_assign_records_the_leftovers_and_why()
def test_disabled(): check_disabled_campaigns_are_skipped_by_default()
def test_select(): check_select_filters_sorts_and_caps()
def test_plan(): check_plan_counts_and_spends_nothing()
def test_floor(): check_plan_warns_below_the_decision_floor()
def test_nomatch(): check_plan_warns_when_nothing_matches()
def test_cap(): check_plan_warns_over_the_global_daily_cap()
def test_tag(): check_campaign_tag_falls_back_to_the_id()


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
