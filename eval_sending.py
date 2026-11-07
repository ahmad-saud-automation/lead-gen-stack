"""
eval_sending.py — step 5, Sending (core/sending.py). TEST MODE ONLY.

Failed before 2026-11-06 (build session 2): core/sending.py did not exist.

What must hold:
  * it refuses outright unless test_mode is True AND the platform is the test-only stand-in
  * only leads with an address + a written ice breaker + a first name are pushed; the rest
    are HELD with a reason, not dropped
  * leads are split evenly between live templates; the daily limit is kept
  * a pushed lead is never pushed twice; an unsubscribed lead never at all
  * writes ONLY `push_status`

Run:  python eval_sending.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import eval_icebreakers as EI                       # noqa: E402
from core import demo_services as D                 # noqa: E402
from core import icebreakers as ICE                 # noqa: E402
from core import lead_record as LR                  # noqa: E402
from core import sending as SEND                    # noqa: E402
from core import templates as T                     # noqa: E402

# 2026-11-07: DM-007 and DM-008 now have the Default ice breaker, so they are pushed too
# (before, they were held for "No ice breaker yet")
PUSH_STATUS = {"DM-001": "pushed", "DM-002": "pushed", "DM-003": "pushed", "DM-004": "pushed",
               "DM-007": "pushed", "DM-008": "pushed", "DM-012": "pushed", "DM-005": "held"}
TEMPLATE = {"DM-001": "Template A", "DM-002": "Template B", "DM-003": "Template A",
            "DM-004": "Template B", "DM-007": "Template A", "DM-008": "Template B", "DM-012": "Template A"}


def ready():
    st, fm, rows = EI.prepared()
    ICE.run(rows, fm, st, "demo", EI.ruleset())
    T.ensure_seeded(st, "demo", T.load_demo(D.TEMPLATES_FILE))
    return st, fm, rows


def check_refuses_outside_test_mode():
    st, fm, rows = ready()

    class LivePlatform:          # anything that is not the test-only stand-in
        campaign = "x"

        def add(self, lead):
            raise AssertionError("a lead reached a non-test platform")
    for mode, plat in ((False, D.DemoSendingPlatform()), (None, D.DemoSendingPlatform()), (True, LivePlatform())):
        try:
            SEND.run(rows, fm, st, "demo", plat, test_mode=mode)
        except SEND.SendRefused:
            continue
        raise AssertionError(f"sending ran with test_mode={mode} platform={type(plat).__name__}")
    assert not any(v.get("push_status") for v in st.statuses("demo").values())


def check_the_demo_pushes_seven_and_holds_one():
    st, fm, rows = ready()
    plat = D.DemoSendingPlatform()
    r = SEND.run(rows, fm, st, "demo", plat, test_mode=True)
    assert (r["pushed"], r["held"], r["failed"]) == (7, 1, 0), r
    got = {k: v["push_status"] for k, v in st.statuses("demo").items() if v.get("push_status")}
    assert got == PUSH_STATUS, got
    names = {t["id"]: t["name"] for t in st.templates("demo")}
    used = {k: names[p["template_id"]] for k, p in st.pushes("demo").items() if p["state"] == "pushed"}
    assert used == TEMPLATE, used
    assert len(plat.added) == 7 and all(a["email"].endswith(".example") for a in plat.added)
    first = next(a for a in plat.added if a["key"] == "DM-001")
    assert first["body"].startswith("Hi Sarah,\n\nI noticed Harbour & Vale is hiring"), first["body"][:80]
    assert "{{" not in first["body"] + first["subject"]
    reasons = {k: p["reason"] for k, p in st.pushes("demo").items() if p["state"] == "held"}
    assert reasons == {"DM-005": "No contact name"}, reasons


def check_never_pushes_twice():
    st, fm, rows = ready()
    SEND.run(rows, fm, st, "demo", D.DemoSendingPlatform(), test_mode=True)
    plat = D.DemoSendingPlatform()
    r = SEND.run(rows, fm, st, "demo", plat, test_mode=True)
    assert r["pushed"] == 0 and not plat.added, r


def check_daily_limit_and_unsubscribe():
    st, fm, rows = ready()
    st.write_status("replies", "demo", "DM-003", {"reply_status": "unsubscribe"})
    plat = D.DemoSendingPlatform()
    r = SEND.run(rows, fm, st, "demo", plat, test_mode=True, daily_limit=2)
    assert r["pushed"] == 2 and r["over_limit"] == 4, r
    assert "DM-003" not in {a["key"] for a in plat.added}


def check_no_live_template_means_nothing_sent():
    st, fm, rows = EI.prepared()
    ICE.run(rows, fm, st, "demo", EI.ruleset())
    try:
        SEND.run(rows, fm, st, "demo", D.DemoSendingPlatform(), test_mode=True)
    except SEND.SendRefused as e:
        assert "template" in str(e)
    else:
        raise AssertionError("sent without an approved template")


def check_writes_only_push_status():
    st, fm, rows = ready()
    before = {k: {c: v for c, v in d.items() if c != "push_status"} for k, d in st.statuses("demo").items()}
    SEND.run(rows, fm, st, "demo", D.DemoSendingPlatform(), test_mode=True)
    after = {k: {c: v for c, v in d.items() if c != "push_status"} for k, d in st.statuses("demo").items()}
    assert before == after
    assert LR.allowed("sending") == ("push_status",)


def check_a_title_in_the_name_is_held():
    st, fm, rows = ready()
    st.save_email_result("demo", "DM-012", {**st.email_results("demo")["DM-012"], "contact": "Dr Owen Morgan",
                                            "steps": []})
    SEND.run(rows, fm, st, "demo", D.DemoSendingPlatform(), test_mode=True)
    assert st.statuses("demo")["DM-012"]["push_status"] == "held"
    assert "title" in st.pushes("demo")["DM-012"]["reason"]


CHECKS = [check_refuses_outside_test_mode, check_the_demo_pushes_seven_and_holds_one, check_never_pushes_twice,
          check_daily_limit_and_unsubscribe, check_no_live_template_means_nothing_sent,
          check_writes_only_push_status, check_a_title_in_the_name_is_held]


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
