"""
eval_templates.py — step 4, Cold email: the copy scorer (core/copy_score.py) and the
templates + request queue (core/templates.py).

Failed before 2026-11-06 (build session 2): neither module existed.

What must hold:
  * the copywriting assistant's reference email scores 100 here too (its baseline)
  * each mistake costs what the assistant charges; an unapproved figure BLOCKS the template
  * a draft scoring 90+ with no blocked figure goes live by itself; anything else waits
  * a blocked draft can never be approved, by hand or automatically
  * live templates are shared evenly; rendering fills the three fields and nothing else

Run:  python eval_templates.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from core import copy_score as CS                   # noqa: E402
from core import demo_services as D                 # noqa: E402
from core import store as S                         # noqa: E402
from core import templates as T                     # noqa: E402

REFERENCE_SUBJECT = "your pricing page, and january cover"
REFERENCE_BODY = ("Kamran,\n\nYou publish your prices upfront, which almost nobody in the profession does.\n\n"
                  "Not pitching you. We run the bookkeeping behind a practice with 1,000 clients. Their workload "
                  "dropped 40% in January, and turnaround improved.\n\nMy team is ACCA qualified. A senior bookkeeper "
                  "is £13 an hour, ten-hour minimum. No contract, no notice. One call, then it is my team's problem, "
                  "not yours.\n\nHappy to send the January costing free, whether or not you ever use us.\n\n"
                  "Can I ring you Thursday at 10am?\n\nShaheryar")
# the assistant's own approved list (OKNUM)
REFERENCE_FIGURES = ["500", "130", "13", "10", "8", "1000", "1,000", "750", "1750", "50", "200", "3", "40", "60",
                     "35", "75", "20", "100", "520", "18", "14", "12", "6", "72", "25", "30"]

DEMO_SCORES = {"Template A": 93, "Template B": 81, "Draft C": 38}


def _store():
    return S.Store(Path(tempfile.mkdtemp(prefix="tpl-")) / "stack.db")


def check_the_reference_email_scores_100():
    r = CS.score(REFERENCE_SUBJECT, REFERENCE_BODY, REFERENCE_FIGURES)
    assert r["score"] == 100 and r["passed"] == 8 and not r["mistakes"], r


def check_each_mistake_costs_what_the_assistant_charges():
    base = CS.score(REFERENCE_SUBJECT, REFERENCE_BODY, REFERENCE_FIGURES)["score"]
    cases = [("Long dash", REFERENCE_BODY.replace("upfront,", "upfront —"), REFERENCE_SUBJECT, 3),
             ("Exclamation mark", REFERENCE_BODY.replace("10am?", "10am? Thanks!"), REFERENCE_SUBJECT, 3),
             ("Legal company name", REFERENCE_BODY.replace("Shaheryar", "Shaheryar, Example Ltd"), REFERENCE_SUBJECT, 3),
             ("Subject case", REFERENCE_BODY, "Your Pricing Page", 3),
             ("Long subject", REFERENCE_BODY, "a" * 51, 5)]
    for name, body, sub, cost in cases:
        r = CS.score(sub, body, REFERENCE_FIGURES)
        assert [m["name"] for m in r["mistakes"]] == [name], (name, r["mistakes"])
        assert r["score"] == base - cost, (name, r["score"])


def check_an_unapproved_figure_blocks():
    r = CS.score(REFERENCE_SUBJECT, REFERENCE_BODY.replace("40%", "45%"), REFERENCE_FIGURES)
    assert r["blocked"] and r["unapproved"] == ["45"] and r["score"] == 85, r
    r = CS.score(REFERENCE_SUBJECT, REFERENCE_BODY.replace("£13 an hour", "£500, prepaid"), REFERENCE_FIGURES)
    assert not r["blocked"], "a comma after an approved price is not a new figure (the 2026-09-05 trap)"
    assert not CS.auto_approves({"score": 95, "blocked": True})


def check_demo_templates_seed_with_these_scores():
    st = _store()
    T.ensure_seeded(st, "demo", T.load_demo(D.TEMPLATES_FILE))
    got = {t["name"]: t["score"] for t in st.templates("demo")}
    assert got == DEMO_SCORES, got
    assert [t["name"] for t in T.live(st, "demo")] == ["Template A", "Template B"]
    reqs = st.requests("demo")
    assert len(reqs) == 1 and reqs[0]["state"] == "draft_ready", reqs
    T.ensure_seeded(st, "demo", T.load_demo(D.TEMPLATES_FILE))
    assert len(st.templates("demo")) == 3, "seeding twice must not add templates"


def check_two_screens_seeding_at_once_give_one_set():
    """Found on screen 2026-11-06: the page loads twice in dev, both requests saw an empty
    store and both seeded, so four live templates showed 25% each."""
    import threading
    path = Path(tempfile.mkdtemp(prefix="tpl-race-")) / "stack.db"
    S.Store(path)
    demo = T.load_demo(D.TEMPLATES_FILE)
    gate = threading.Barrier(8)

    def go():
        st = S.Store(path)
        gate.wait()
        T.ensure_seeded(st, "demo", demo)
    ts = [threading.Thread(target=go) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    st = S.Store(path)
    assert len(st.templates("demo")) == 3 and len(st.requests("demo")) == 1, len(st.templates("demo"))
    st.reset("demo")
    T.ensure_seeded(st, "demo", demo)
    assert len(st.templates("demo")) == 3, "after a reset the demo seeds again"


def check_a_90_plus_draft_goes_live_by_itself():
    st = _store()
    demo = T.load_demo(D.TEMPLATES_FILE)
    T.ensure_seeded(st, "demo", demo)
    r = T.request(st, "demo", "new", "Lead with month-end", demo["approved_figures"], writer=D.demo_writer())
    assert r["auto_approved"] and r["state"] == "approved" and r["score"] >= 90, r
    assert len(T.live(st, "demo")) == 3


def check_a_low_draft_waits_and_a_blocked_one_cannot_be_approved():
    st = _store()
    demo = T.load_demo(D.TEMPLATES_FILE)
    T.ensure_seeded(st, "demo", demo)
    low = T.request(st, "demo", "improve", "Shorter please", demo["approved_figures"], writer=D.demo_writer())
    assert low["state"] == "draft_ready" and not low["auto_approved"], low
    bad = T.request(st, "demo", "facts", "Add a result", demo["approved_figures"], writer=D.demo_writer())
    assert bad["blocked"] and bad["state"] == "draft_ready", bad
    try:
        T.approve(st, "demo", bad["template"])
    except T.TemplateError as e:
        assert "blocked" in str(e)
    else:
        raise AssertionError("a blocked draft was approved")
    T.approve(st, "demo", low["template"])
    assert next(t for t in st.templates("demo") if t["id"] == low["template"])["state"] == "live"
    assert next(r for r in st.requests("demo") if r["id"] == low["request"])["state"] == "approved"


def check_without_a_writer_a_request_stays_queued():
    st = _store()
    r = T.request(st, "demo", "subjects", "Five subject lines", [])
    assert r["state"] == "queued" and st.requests("demo")[0]["state"] == "queued", r
    for kind, text in (("poem", "write a poem"), ("new", "hi")):
        try:
            T.request(st, "demo", kind, text, [])
        except T.TemplateError:
            continue
        raise AssertionError(f"accepted {kind!r} {text!r}")


def check_edit_rescores_and_reject_hides():
    st = _store()
    demo = T.load_demo(D.TEMPLATES_FILE)
    T.ensure_seeded(st, "demo", demo)
    c = next(t for t in st.templates("demo") if t["name"] == "Draft C")
    r = T.edit(st, "demo", c["id"], c["subject"], c["body"] + "\n\nNo contract.", demo["approved_figures"])
    assert r["score"] == DEMO_SCORES["Draft C"] + 15, r
    T.reject(st, "demo", c["id"])
    assert next(t for t in st.templates("demo") if t["id"] == c["id"])["state"] == "rejected"
    a = T.live(st, "demo")[0]
    try:
        T.edit(st, "demo", a["id"], "x", "y", [])
    except T.TemplateError:
        pass
    else:
        raise AssertionError("a live template was edited")


def check_render_fills_the_three_fields():
    t = {"subject": "capacity at {{company}}", "body": "Hi {{first_name}},\n\n{{ice_breaker}}"}
    m = T.render(t, {"first_name": "Jane", "company": "Hartley", "ice_breaker": "I noticed Hartley is hiring."})
    assert m == {"subject": "capacity at Hartley", "body": "Hi Jane,\n\nI noticed Hartley is hiring."}, m
    r = T.scored({"subject": "hi {{surname}}", "body": "x"}, [])
    assert r["blocked"] and r["unknown_fields"] == ["surname"], r


CHECKS = [check_the_reference_email_scores_100, check_each_mistake_costs_what_the_assistant_charges,
          check_an_unapproved_figure_blocks, check_demo_templates_seed_with_these_scores,
          check_two_screens_seeding_at_once_give_one_set,
          check_a_90_plus_draft_goes_live_by_itself, check_a_low_draft_waits_and_a_blocked_one_cannot_be_approved,
          check_without_a_writer_a_request_stays_queued, check_edit_rescores_and_reject_hides,
          check_render_fills_the_three_fields]


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
