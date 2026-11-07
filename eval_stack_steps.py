"""
eval_stack_steps.py — the server APIs behind the step 3–6 screens (build session 2):
Ice breakers, Cold email, Sending, Replies, and the Test-mode box.

Failed before 2026-11-06: none of these APIs existed.

All against a throwaway database. Only the demo may run; the whole demo, run through the
APIs in screen order, must read back exactly the values the engine evals expect; no client
brand or outside service name reaches a screen.

Run:  python eval_stack_steps.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "webapp"))
import server as S                                  # noqa: E402
import eval_icebreakers as EI                       # noqa: E402
import eval_replies as ER                           # noqa: E402
import eval_sending as ES                           # noqa: E402

BANNED = ["icypeas", "millionverifier", "million verifier", "anymailfinder", "instantly",
          "northwind outsourcing", "northwind –", "northwind -", "fabrikam", "contoso", "nick", "fieldmap.", ".json", "shaheryar"]


def _sandbox():
    tmp = Path(tempfile.mkdtemp(prefix="steps-"))
    S.STACK_DB = tmp / "stack.db"
    return tmp


def _no_banned(obj, where):
    text = json.dumps(obj, ensure_ascii=False).lower()
    for w in BANNED:
        assert w not in text, (where, w)


def _through_find():
    _sandbox()                       # his order since 2026-11-07: Find email, then research
    assert S.stack_run_find("demo")["ok"]
    assert S.stack_run_research("demo")["ok"]


def check_test_mode_box():
    m = S.stack_mode()
    assert m["test_mode"] is True and m["can_change"] is False and "not sent" in m["text"], m


def check_ice_needs_email_and_research_first():
    _sandbox()
    r = S.stack_ice_run("demo")
    assert not r["ok"] and "email" in r["error"], r


def check_only_the_demo_runs_steps_3_to_6():
    _sandbox()
    src = "campaign:anything"
    for r in (S.stack_ice_run(src), S.stack_ice_ruleset(src, {}), S.stack_email_request(src, "new", "hello there"),
              S.stack_email_template(src, 1, "approve"), S.stack_send_run(src), S.stack_replies_check(src),
              S.stack_replies_update(src, 1, "interested")):
        assert r["ok"] is False and "not in the pipeline" in r["error"], r     # production words, 2026-11-07
    for r in (S.stack_ice_camp(src), S.stack_email_camp(src), S.stack_replies(src)):
        assert "not in the pipeline" in r["error"], r


def check_the_full_demo_through_the_apis_reads_back_the_engine_values():
    _through_find()
    r = S.stack_ice_run("demo")
    assert r["ok"] and r["written"] == 8 and r["default"] == 2 and r["no_facts"] == 0, r
    v = S.stack_ice_camp("demo")
    got = {x["key"]: x["status"]["value"] for x in v["leads"] if x["status"]["value"] in ("written", "no_facts")}
    assert got == EI.ICE_STATUS, got
    assert {x["key"]: x["rung"] for x in v["leads"] if x["rung"]} == EI.RUNG
    assert v["counts"]["waiting"] == 0 and v["counts"]["no_email"] == 4, v["counts"]
    s = S.stack_send_run("demo")
    assert s["ok"] and s["pushed"] == 7 and s["held"] == 1 and s["test_mode"] and s["platform_received"] == 7, s
    sv = S.stack_send()
    assert {x["key"]: x["template"] for x in sv["leads"] if x["template"]} == ES.TEMPLATE
    assert sv["rows"][0]["sent_today"] == 7 and sv["rows"][0]["queued"] == 0 and sv["can_send"] == 0, sv["rows"][0]
    c = S.stack_replies_check("demo")
    assert c["ok"] and c["new"] == 5, c
    rv = S.stack_replies("demo")
    assert {x["key"]: x["category"]["value"] for x in rv["replies"]} == ER.REPLY_STATUS
    leads = S.stack_leads("demo")
    st = {x["key"]: {k: x["steps"][k]["value"] for k in ("icebreaker_status", "push_status", "reply_status")}
          for x in leads["rows"]}
    assert {k: v["push_status"] for k, v in st.items() if v["push_status"]} == ES.PUSH_STATUS
    assert S.stack_lead("demo", "DM-001")["lead"]["next"] == "Complete"
    assert S.stack_lead("demo", "DM-005")["lead"]["next"].startswith("Held")       # no contact name


def check_ice_preview_and_rule_set_edits():
    _through_find()
    p = S.stack_ice_preview("demo", "DM-004")
    assert p["rung"] == "Sectors served" and not p["saved"] and "hospitality and retail" in p["line"], p
    v = S.stack_ice_camp("demo")
    rungs = v["ruleset"]["rungs"]
    moved = [rungs[3]] + rungs[:3] + rungs[4:]          # "Sectors served" first
    r = S.stack_ice_ruleset("demo", {"rungs": moved})
    assert r["ok"], r
    S.stack_ice_run("demo")
    v = S.stack_ice_camp("demo")
    assert {x["key"]: x["rung"] for x in v["leads"] if x["rung"]}["DM-001"] == "Sectors served"
    bad = [dict(x) for x in moved]
    bad[0]["fact"] = "works with clients"
    r = S.stack_ice_ruleset("demo", {"rungs": bad})
    assert not r["ok"] and "{item}" in r["error"], r
    r = S.stack_ice_run("demo", ["DM-001"], rewrite=True)
    assert r["ok"] and r["written"] == 1, r
    r = S.stack_ice_run("demo", [], rewrite=True)
    assert not r["ok"], r


def check_cold_email_camp_requests_and_approval():
    _through_find()
    e = S.stack_email_camp("demo")
    assert [t["name"] for t in e["templates"]] == ["Template A", "Template B", "Draft C"], e["templates"]
    assert [t["share"] for t in e["templates"]] == [50, 50, 0]
    assert e["top_score"] == 93 and e["live"] == 2 and e["drafts"] == 1
    r = S.stack_email_request("demo", "new", "Lead with month-end close")
    assert r["ok"] and r["auto_approved"], r
    e = S.stack_email_camp("demo")
    assert e["live"] == 3 and e["requests"][0]["state"]["value"] == "approved", e["requests"]
    c = next(t for t in e["templates"] if t["name"] == "Draft C")
    r = S.stack_email_template("demo", c["id"], "approve")
    assert r["ok"], r
    r = S.stack_email_request("demo", "facts", "Add a result figure")
    blocked = r["template"]
    r = S.stack_email_template("demo", blocked, "approve")
    assert not r["ok"] and "blocked" in r["error"], r
    r = S.stack_email_template("demo", blocked, "explode")
    assert not r["ok"], r
    sc = S.stack_email_score("hi", "Hi {{first_name}}, £99 an hour.")
    assert sc["blocked"] and sc["unapproved"] == ["99"], sc


def check_email_preview_fills_the_fields():
    _through_find()
    S.stack_ice_run("demo")
    e = S.stack_email_camp("demo")
    assert [x["key"] for x in e["preview"]] == ["DM-001", "DM-002", "DM-003", "DM-004", "DM-005", "DM-007",
                                                 "DM-008", "DM-012"]
    a = e["templates"][0]["id"]
    p = S.stack_email_preview("demo", "DM-001", a)
    assert p["to"] == "sarah@harbourvale.example" and p["subject"] == "capacity at Harbour & Vale", p
    assert p["body"].startswith("Hi Sarah,\n\nI noticed Harbour & Vale is hiring") and not p["note"], p
    p = S.stack_email_preview("demo", "DM-005", a)
    assert "hold" in p["note"], p


def check_sending_refuses_without_ready_leads():
    _sandbox()
    r = S.stack_send_run("demo")
    assert not r["ok"], r


def check_replies_change_and_handle():
    _through_find()
    S.stack_ice_run("demo")
    S.stack_send_run("demo")
    S.stack_replies_check("demo")
    rep = next(x for x in S.stack_replies("demo")["replies"] if x["key"] == "DM-002")
    assert S.stack_replies_update("demo", rep["id"], "interested")["ok"]
    assert S.stack_replies_update("demo", rep["id"], "", True)["ok"]
    rep = next(x for x in S.stack_replies("demo")["replies"] if x["key"] == "DM-002")
    assert rep["category"]["value"] == "interested" and rep["handled"] and rep["changed"], rep
    r = S.stack_replies_update("demo", rep["id"], "maybe")
    assert not r["ok"], r


def check_reset_clears_steps_3_to_6():
    _through_find()
    S.stack_ice_run("demo")
    S.stack_email_request("demo", "new", "Lead with month-end close")
    S.stack_send_run("demo")
    S.stack_replies_check("demo")
    S.stack_reset_demo()
    assert not S.stack_replies("demo")["replies"]
    assert S.stack_email_camp("demo")["live"] == 2
    assert S.stack_send()["rows"][0]["sent"] == 0
    assert S.stack_ice_camp("demo")["counts"]["written"] == 0


def check_no_brand_or_service_name_on_any_step_screen():
    _through_find()
    S.stack_ice_run("demo")
    S.stack_send_run("demo")
    S.stack_replies_check("demo")
    for name, body in (("ice", S.stack_ice()), ("ice/camp", S.stack_ice_camp("demo")),
                       ("ice/preview", S.stack_ice_preview("demo", "DM-001")),
                       ("email", S.stack_email()), ("email/camp", S.stack_email_camp("demo")),
                       ("send", S.stack_send()), ("replies", S.stack_replies("demo")), ("mode", S.stack_mode())):
        _no_banned(body, name)
    # one tile for Demo firms + one per pipeline campaign (2026-11-06)
    assert S.stack_ice()["later"]["count"] >= 0 and len(S.stack_ice()["campaigns"]) == 1 + len(S._pipeline_camps())


CHECKS = [check_test_mode_box, check_ice_needs_email_and_research_first, check_only_the_demo_runs_steps_3_to_6,
          check_the_full_demo_through_the_apis_reads_back_the_engine_values, check_ice_preview_and_rule_set_edits,
          check_cold_email_camp_requests_and_approval, check_email_preview_fills_the_fields,
          check_sending_refuses_without_ready_leads, check_replies_change_and_handle,
          check_reset_clears_steps_3_to_6, check_no_brand_or_service_name_on_any_step_screen]


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
