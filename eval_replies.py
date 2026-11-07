"""
eval_replies.py — step 6, Replies (core/replies.py): collect, classify, record.

Failed before 2026-11-06 (build session 2): core/replies.py did not exist.

What must hold:
  * every category is recognised; an unsubscribe is never read as interest, and
    "not interested" is never read as "interested"
  * a reply that matches no rule goes to a person (interested + "read and decide")
  * the action uses the message: return date, new address, the day offered
  * replies are collected only for pushed leads, once each; writes ONLY `reply_status`
  * a person can change the category (it rewrites reply_status) and mark it handled

Run:  python eval_replies.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import eval_sending as ES                           # noqa: E402
from core import demo_services as D                 # noqa: E402
from core import lead_record as LR                  # noqa: E402
from core import replies as REP                     # noqa: E402
from core import sending as SEND                    # noqa: E402

REPLY_STATUS = {"DM-001": "interested", "DM-002": "not_interested", "DM-003": "ooo",
                "DM-004": "wrong_person", "DM-012": "unsubscribe"}
NOW = datetime(2026, 11, 6, 11, 0, 0)


def sent():
    st, fm, rows = ES.ready()
    SEND.run(rows, fm, st, "demo", D.DemoSendingPlatform(), test_mode=True)
    return st, fm, rows


def check_categories():
    cases = {
        "Yes, please send more information.": "interested",
        "What would this cost for a 12-person clinic?": "interested",
        "Not interested, thanks.": "not_interested",
        "No thank you, we are covered.": "not_interested",
        "I am on annual leave until 3 December.": "ooo",
        "Automatic reply: I am away until Monday.": "ooo",
        "I have left the firm. Please contact anna@x.example.": "wrong_person",
        "Please remove me from your list.": "unsubscribe",
        "Unsubscribe. I am not interested.": "unsubscribe",
        "Stop emailing me, I would be interested in never hearing from you.": "unsubscribe",
        "Hmm.": "interested",
    }
    for text, want in cases.items():
        assert REP.classify(text) == want, (text, REP.classify(text), want)


def check_actions_use_the_message():
    assert REP.action("ooo", "I am out of the office until Monday 10 November.") == \
        "No action. The sequence resumes after Monday 10 November."
    assert REP.action("wrong_person", "Please contact james@b.example instead.") == \
        "Add james@b.example as a new contact for this company."
    assert REP.action("interested", "Could we speak on Tuesday?") == "Book a call. Tuesday was offered."
    assert REP.action("interested", "How much would it cost?") == "Reply with pricing."
    assert "decide" in REP.action("interested", "Hmm.")


def check_the_demo_gives_one_reply_per_category():
    st, fm, rows = sent()
    r = REP.check(rows, fm, st, "demo", D.DemoInbox(), now=NOW)
    assert r["new"] == 5, r
    got = {k: v["reply_status"] for k, v in st.statuses("demo").items() if v.get("reply_status")}
    assert got == REPLY_STATUS, got
    again = REP.check(rows, fm, st, "demo", D.DemoInbox(), now=NOW)
    assert again["new"] == 0 and again["seen"] == 5, again


def check_no_reply_before_sending():
    st, fm, rows = ES.ready()
    r = REP.check(rows, fm, st, "demo", D.DemoInbox(), now=NOW)
    assert r["new"] == 0 and not st.replies("demo"), r


def check_writes_only_reply_status():
    st, fm, rows = sent()
    before = {k: {c: v for c, v in d.items() if c != "reply_status"} for k, d in st.statuses("demo").items()}
    REP.check(rows, fm, st, "demo", D.DemoInbox(), now=NOW)
    after = {k: {c: v for c, v in d.items() if c != "reply_status"} for k, d in st.statuses("demo").items()}
    assert before == after
    assert LR.allowed("replies") == ("reply_status",)


def check_change_category_and_mark_handled():
    st, fm, rows = sent()
    REP.check(rows, fm, st, "demo", D.DemoInbox(), now=NOW)
    rep = next(r for r in st.replies("demo") if r["row_key"] == "DM-002")
    REP.recategorise(st, "demo", rep["id"], "interested")
    assert st.statuses("demo")["DM-002"]["reply_status"] == "interested"
    try:
        REP.recategorise(st, "demo", rep["id"], "maybe")
    except LR.WriteRefused:
        pass
    else:
        raise AssertionError("an unknown category was written")
    REP.mark_handled(st, "demo", rep["id"])
    assert next(r for r in st.replies("demo") if r["id"] == rep["id"])["handled"] == 1


def check_when_labels():
    assert REP.when_label("2026-11-06 10:14:00", NOW) == "Today 10:14"
    assert REP.when_label("2026-11-05 16:05:00", NOW) == "Yesterday 16:05"


CHECKS = [check_categories, check_actions_use_the_message, check_the_demo_gives_one_reply_per_category,
          check_no_reply_before_sending, check_writes_only_reply_status, check_change_category_and_mark_handled,
          check_when_labels]


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
