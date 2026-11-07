"""
eval_showcase.py — the real-run showcase (2026-11-06): Draft-only push, the Privacy switch,
step cards that say what each step PRODUCED, and templates answered from the request queue.

Failed before 2026-11-06: core/live_services.py and core/privacy.py did not exist, sending
refused every non-test platform, and the run cards only had "n / total" (leads looked at:
"Sending 8/12" while 5 were sent).

What must hold:
  * a Draft-only platform pushes ONLY after Instantly says the campaign is Draft or Paused,
    asked once right before the first lead; Active / Completed / no answer → nothing pushed
  * Privacy masks emails, the app's known person names and client brands in VALUES only
  * the Privacy switch masks real /api/stack/ answers (middleware), and only while on
  * the Sending card counts pushed and held, the Cold email card counts templates and leads
  * a pipeline request waits in the queue until answered; an answer is scored and goes live at 90+

Run:  python eval_showcase.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))
import eval_sending as ES                           # noqa: E402
from core import live_services as LIVE              # noqa: E402
from core import privacy as PRIV                    # noqa: E402
from core import sending as SEND                    # noqa: E402
from core import templates as T                     # noqa: E402
import server as S                                  # noqa: E402


def _platform(status, calls):
    def get(path, key):
        calls.append(("get", path))
        if status is None:
            raise ConnectionError("no answer")
        return {"name": "Showcase", "status": status}

    def push(payload, key):
        calls.append(("push", payload["email"]))
        return {"ok": True, "status_code": 200, "response": {"id": "x"}}
    return LIVE.InstantlyDraftPlatform("k", "camp-1", get=get, push=push)


def check_draft_platform_refuses_unless_draft_or_paused():
    for status in (1, 3, 4, None):
        st, fm, rows = ES.ready()
        calls: list = []
        try:
            SEND.run(rows, fm, st, "demo", _platform(status, calls), test_mode=True)
        except SEND.SendRefused as e:
            assert "Nothing was sent" in str(e), str(e)
            assert not [c for c in calls if c[0] == "push"], (status, calls)
            assert not any(v.get("push_status") for v in st.statuses("demo").values())
            continue
        raise AssertionError(f"pushed with campaign status {status}")


def check_draft_platform_pushes_after_one_status_check():
    for status in (0, 2):
        st, fm, rows = ES.ready()
        calls: list = []
        r = SEND.run(rows, fm, st, "demo", _platform(status, calls), test_mode=True)
        assert r["pushed"] == 7 and r["held"] == 1, r
        assert calls[0][0] == "get" and sum(1 for c in calls if c[0] == "get") == 1, calls
        assert sum(1 for c in calls if c[0] == "push") == 7
        assert {p["mode"] for p in st.pushes("demo").values()} == {"draft"}


def check_draft_platform_still_needs_test_mode():
    st, fm, rows = ES.ready()
    calls: list = []
    try:
        SEND.run(rows, fm, st, "demo", _platform(0, calls), test_mode=False)
    except SEND.SendRefused:
        assert not calls
        return
    raise AssertionError("ran without test_mode")


def check_privacy_masks_values_not_keys():
    obj = {"email": "sarah.jones@smithcpa.com", "rows": [{"contact": "Sarah Jones", "company": "Smith CPA"}],
           "name": "Northwind Practices C10", "note": "sent from northwind.example by Fabrikam and Contoso", "n": 3}
    m = PRIV.mask(obj, PRIV.names_from_rows([{"contact_1_name": "Sarah Jones"}]))
    assert m["email"] == "s***@smithcpa.com", m
    assert m["rows"][0] == {"contact": "Sarah J.", "company": "Smith CPA"}, m
    assert m["name"] == "Practices C10", m
    low = json.dumps(m).lower()
    for w in ("northwind", "fabrikam", "contoso", "sarah.jones", "jones"):
        assert w not in low, (w, m)
    assert set(m) == set(obj) and m["n"] == 3


def _through_gate(path: str, body: dict) -> dict:
    """One answer passed through the real middleware, as Starlette hands it over (streamed)."""
    import asyncio
    from starlette.requests import Request
    from starlette.responses import StreamingResponse
    req = Request({"type": "http", "path": path, "method": "GET", "headers": [], "query_string": b""})

    async def call_next(_r):
        return StreamingResponse(iter([json.dumps(body).encode()]), media_type="application/json")

    async def go():
        resp = await S._privacy_gate(req, call_next)
        if hasattr(resp, "body_iterator"):
            return json.loads(b"".join([c async for c in resp.body_iterator]))
        return json.loads(resp.body)
    return asyncio.run(go())


def check_privacy_switch_masks_api_answers():
    S.STACK_DB = Path(tempfile.mkdtemp(prefix="show-")) / "stack.db"
    body = {"contact": "Sarah Whitcombe", "email": "sarah@harbourvale.example", "name": "Northwind Practices"}
    S.stack_presenting_set(False)
    assert _through_gate("/api/stack/lead", body) == body, "switch off: nothing changes"
    S.stack_presenting_set(True)
    S._PRIVACY_NAMES["at"] = 0
    try:
        on = _through_gate("/api/stack/lead", body)
        assert on == {"contact": "Sarah W.", "email": "s***@harbourvale.example", "name": "Practices"}, on
        assert _through_gate("/api/campaigns", body) == body, "only /api/stack/ answers are masked"
    finally:
        S.stack_presenting_set(False)


def _lead(website="", email="", ice="", sent="", reply=""):
    p = lambda v: {"value": v}                       # noqa: E731
    return {"website": p(website), "email": p(email), "ice": p(ice), "sent": p(sent), "reply": p(reply)}


def check_cards_say_what_each_step_produced():
    """His order (2026-11-07): Find email takes every lead; research takes only the leads with
    an email; every lead with an email gets a line, a no-site lead from the Default line.
    Failed before: research came first, and the cards counted from it."""
    leads = ([_lead("found", "enriched", "written", "pushed")] * 5
             + [_lead("dead_domain", "as-is", "written", "pushed")] * 2          # Default line
             + [_lead("", "no_website")] + [_lead("", "no_email")] * 4)        # never researched
    res = {"email": {"live": 2, "prepared": 7}, "ice": {"default": 2}}
    assert S._produced("find", leads, res, False) == "12 in → 7 emails found · 5 not found", \
        S._produced("find", leads, res, False)
    assert S._produced("research", leads, res, False) == "7 in → 5 websites read · 2 no site or not readable", \
        S._produced("research", leads, res, False)
    assert S._produced("ice", leads, res, False) == "7 in → 7 written · 2 from the Default line", \
        S._produced("ice", leads, res, False)
    assert S._produced("email", leads, res, False) == "2 templates live · 7 leads matched"
    assert S._produced("send", leads, res, False) == "7 pushed to Draft · 0 held"
    assert S._produced("replies", leads, res, False) == "0 replies (campaign is Draft)"
    assert S._produced("send", leads, res, True).startswith("7 queued (test)")
    # a lead with no website whose email the finder found by company name counts as found,
    # and goes into research (where it is "no site")
    noweb = [_lead("not_found", "enriched")] + [_lead("found", "as-is")]
    assert S._produced("find", noweb, res, False) == "2 in → 2 emails found · 0 not found"
    assert S._produced("research", noweb, res, False) == "2 in → 1 websites read · 1 no site or not readable"
    # leads left for a later run (the per-run limit, 2026-11-07: 40 firms, 10 per run) are not "in"
    later = leads + [_lead()] * 30
    assert S._produced("find", later, res, False) == "12 in → 7 emails found · 5 not found", S._produced("find", later, res, False)


def check_a_pipeline_request_waits_then_an_answer_goes_live():
    S.STACK_DB = Path(tempfile.mkdtemp(prefix="show-")) / "stack.db"
    st = S._stack_store()
    q = T.request(st, "demo", "new", "Write the first email", [], writer=None)
    assert q["state"] == "queued" and not T.live(st, "demo")
    ref = "Hi {{first_name}},\n\n{{ice_breaker}}\n\nI help small firms with month-end. Can I send a one-page outline?\n\nSam"
    a = S.stack_email_answer("demo", q["request"], "month-end at {{company}}", ref)
    assert a["ok"] and a["template"], a
    again = S.stack_email_answer("demo", q["request"], "x", "y")
    assert not again["ok"] and "already answered" in again["error"], again


def check_showcase_recipe_searches_no_website_leads_by_company():
    """His rule (2026-11-07): a lead with no website goes to the finder by company name.
    Failed before: the showcase recipe had no `icypeas_company` way, so such leads got nothing."""
    from core import recipe as RC
    raw = json.loads((Path(__file__).parent / "config" / "recipes" / "showcase-waterfall.json").read_text(encoding="utf-8"))
    rec = RC.Recipe(raw)
    assert RC.validate(rec) == [], RC.validate(rec)
    ways = [w["method"] for w in raw["people"][1]["how"]]
    assert ways == ["guess_patterns", "icypeas_domain", "icypeas_company"], ways   # the demo recipe's order
    row = {"lead_id": "X1", "company_name": "Smith CPA LLC", "website": "", "contact_1_name": "Sarah Jones",
           "contact_1_email": "", "email": ""}
    from core import demo_services as D, fieldmap as FM
    plan = RC.plan_for_row(rec, row, fm=FM.load(D.DEMO_FIELDMAP))
    ok = [w["method"] for p in plan.get("people") or [] for w in p.get("ways") or [] if w.get("ok")]
    assert "icypeas_company" in ok and "guess_patterns" not in ok, plan


def check_production_app_reports_on_the_real_campaign():
    """2026-11-07, his ask: a production app, no sample set on show. Home/Health follow the
    real campaign's run even when the sample firms ran later; Schedules run on the campaign he
    picks (sample firms until he picks, so nothing paid starts by itself); words are plain.
    Failed before: Home followed the newest run of ANY source, Schedules were sample-only."""
    S.STACK_DB = Path(tempfile.mkdtemp(prefix="prod-")) / "stack.db"
    st = S._stack_store()
    real = [f"campaign:{c.id}" for c in S._pipeline_camps()]
    assert S._home_source(st) == "demo"                          # nothing ran anywhere
    if real:
        st.add_run({"id": "R1", "source": real[0], "trigger": S.RUN_TRIGGER, "state": "done", "step": 5,
                    "start_step": 0, "end_step": 5, "due": "2026-11-07 10:00:00.000"})
        st.update_run("R1", started="2026-11-07 10:00:00")
        st.add_run({"id": "R2", "source": "demo", "trigger": S.DEMO_TRIGGER, "state": "done", "step": 5,
                    "start_step": 0, "end_step": 5, "due": "2026-11-07 11:00:00.000"})
        st.update_run("R2", started="2026-11-07 11:00:00")
        assert S._home_source(st) == real[0], S._home_source(st)
        assert S._sched_source(st) == "demo"
        r = S.stack_schedules_source(real[0])
        assert r["ok"] and r["source"] == real[0] and S._sched_source(st) == real[0], r
    bad = S.stack_schedules_source("campaign:nope")
    assert not bad["ok"] and "Run in the 6-step pipeline" in bad["error"], bad
    words = json.dumps([S.stack_mode(), S.NOT_YET_STEP, S.NOT_YET_SHEET, S.LOCKED_WHY]).lower()
    for w in ("demo", "test mode", "later update", "this version"):
        assert w not in words, (w, words)


def check_only_pipeline_campaigns_run():
    class C:
        def __init__(self, raw):
            self.raw = raw
    assert S._is_pipeline(C({"pipeline": True})) and not S._is_pipeline(C({})) and not S._is_pipeline(C({"pipeline": False}))


CHECKS = [check_draft_platform_refuses_unless_draft_or_paused, check_draft_platform_pushes_after_one_status_check,
          check_draft_platform_still_needs_test_mode, check_privacy_masks_values_not_keys,
          check_privacy_switch_masks_api_answers, check_cards_say_what_each_step_produced,
          check_a_pipeline_request_waits_then_an_answer_goes_live, check_only_pipeline_campaigns_run,
          check_showcase_recipe_searches_no_website_leads_by_company,
          check_production_app_reports_on_the_real_campaign]


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
