"""
eval_connections.py - offline test for the V5 screens' engine pieces.
    python eval_connections.py   /   pytest eval_connections.py

core/connections.py with every HTTP call faked, plus the server helpers behind the new
screens (reorder, the per-campaign sheet switch, the free test of a switched-off campaign),
each on a temp config folder that is put back afterwards.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.error
from contextlib import contextmanager
from pathlib import Path

from core import connections as C


@contextmanager
def fake_http(answers: dict):
    """answers: url-fragment -> dict to return, or an Exception to raise."""
    real = C._get_json
    seen = []

    def fake(url, headers=None, timeout=15):
        seen.append((url, headers or {}))
        for frag, ans in answers.items():
            if frag in url:
                if isinstance(ans, Exception):
                    raise ans
                return ans(url) if callable(ans) else ans
        raise AssertionError(f"unexpected call {url}")
    C._get_json = fake
    try:
        yield seen
    finally:
        C._get_json = real


def _http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def check_millionverifier_reads_credits_and_explains_a_bad_key():
    with fake_http({"/credits": {"credits": 12400}}) as seen:
        r = C.test_millionverifier("k1")
    assert r["ok"] and "12,400" in r["detail"], r
    assert "api=k1" in seen[0][0], "the key goes in the query, as MillionVerifier wants"
    with fake_http({"/credits": _http_error(401)}):
        r = C.test_millionverifier("bad")
    assert not r["ok"] and "refused the key" in r["detail"], r
    assert not C.test_millionverifier("")["ok"], "no key = not ok, and no call made"


def check_instantly_options_pages_and_names_the_status():
    def campaigns(url):
        if "starting_after" not in url:
            return {"items": [{"id": "c2", "name": "Zeta", "status": 1}], "next_starting_after": "c2"}
        return {"items": [{"id": "c1", "name": "alpha", "status": 0}, {"id": "", "name": "no id"}]}
    with fake_http({"/campaigns": campaigns, "/lead-lists": {"items": [{"id": "l1", "name": "Northwind all"}]}}) as seen:
        r = C.instantly_options("key")
    assert r["ok"] and [c["name"] for c in r["campaigns"]] == ["alpha", "Zeta"], r
    assert r["campaigns"][1]["status"] == "active" and r["campaigns"][0]["status"] == "draft"
    assert r["lists"] == [{"id": "l1", "name": "Northwind all"}]
    assert all(h.get("Authorization") == "Bearer key" for _u, h in seen)
    assert r["detail"] == "2 campaigns found"


def check_instantly_without_list_scope_still_gives_campaigns():
    with fake_http({"/campaigns": {"items": [{"id": "c1", "name": "A", "status": 2}]},
                    "/lead-lists": _http_error(403)}):
        r = C.instantly_options("key")
    assert r["ok"] and len(r["campaigns"]) == 1 and r["lists"] == [], r
    with fake_http({"/campaigns": urllib.error.URLError("offline")}):
        r = C.instantly_options("key")
    assert not r["ok"] and "could not reach Instantly" in r["detail"], r


def check_anymailfinder_and_openai():
    with fake_http({"/account": {"credits_left": 950}}) as seen:
        r = C.test_anymailfinder("a")
    assert r["ok"] and "950" in r["detail"] and seen[0][1]["Authorization"] == "Bearer a"
    with fake_http({"/models": {"data": []}}):
        assert C.test_openai("o")["ok"]


# ───────── server helpers on a temp config folder ─────────

@contextmanager
def engine(lanes: list[dict]):
    from webapp import server as S
    saved = {k: getattr(S, k) for k in ("CONFIG_DIR", "HISTORY_FILE")}
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "campaigns.json").write_text(json.dumps({"globals": {}, "campaigns": lanes}))
        S.CONFIG_DIR = Path(d)
        S.HISTORY_FILE = Path(d) / "history.json"
        try:
            yield S
        finally:
            for k, v in saved.items():
                setattr(S, k, v)


LANES = [{"id": "a", "name": "A", "tab": "T", "priority": 10},
         {"id": "b", "name": "B", "tab": "T", "priority": 20},
         {"id": "c", "name": "C", "tab": "T", "priority": 30}]


def check_reorder_turns_the_drag_order_into_priorities():
    with engine(LANES) as S:
        assert S.reorder_campaigns(["c", "a"])["ok"]
        rows = json.loads((S.CONFIG_DIR / "campaigns.json").read_text())["campaigns"]
        prio = {r["id"]: r["priority"] for r in rows}
        assert prio == {"c": 10, "a": 20, "b": 30}, prio
        assert not S.reorder_campaigns(["a", "a"])["ok"], "a campaign named twice is refused"
        assert not S.reorder_campaigns(["nope"])["ok"]


def check_campaign_sheet_switch_is_honoured():
    from core import campaigns as K
    from webapp import server as S
    assert S._lane_writes_back(K.Campaign({"id": "x"})), "on unless switched off"
    assert S._lane_writes_back(K.Campaign({"id": "x", "writeback": {"campaign_type": "x"}}))
    assert not S._lane_writes_back(K.Campaign({"id": "x", "writeback": {"enabled": False}}))


def check_switched_off_campaign_refuses_live_but_not_test():
    with engine([{**LANES[0], "enabled": False}]) as S:
        live = S.start_campaign_run("a", test_mode=False)
        assert "switched off" in (live.get("error") or ""), live
        test = S.start_campaign_run("a", test_mode=True)
        # the test gets past the on/off gate; it then fails only because tab T does not exist
        assert "switched off" not in (test.get("error") or ""), test


def check_readiness_names_what_to_fix():
    with engine([{**LANES[0], "enabled": False}]) as S:
        r = S.campaign_readiness("a")
        fixes = {i["fix"] for i in r["items"] if not i["ok"]}
        assert {"send", "on", "test"} <= fixes, r
        assert r["done"] < r["total"]
        assert "error" in S.campaign_readiness("nope")


def check_schedule_preview_uses_the_clocks_maths():
    from datetime import datetime
    from webapp import server as S
    r = S.schedule_preview({"kind": "weekly", "days": ["MON", "WED"], "start": "09:00", "anchor": "2026-10-05"},
                           now=datetime(2026, 10, 5, 8, 0))
    assert r["next"] == ["2026-10-05 09:00", "2026-10-07 09:00", "2026-10-12 09:00"], r
    assert r["summary"] == "MON, WED at 09:00"
    bad = S.schedule_preview({"kind": "weekly"})
    assert bad["problems"] and bad["next"] == [], "a schedule with a problem promises no times"


def check_display_reads_share_one_sheet_read():
    import threading
    import time as _t
    from webapp import server as S
    real, calls = S._read_tab, []

    def slow(cfg, tab):
        calls.append(tab)
        _t.sleep(0.3)
        return [{"a": "1"}]
    S._read_tab = slow
    S._TAB_CACHE.clear()
    try:
        cfg = {"sheet_url": "u"}
        ts = [threading.Thread(target=S._read_tab_for_display, args=(cfg, "T")) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert calls == ["T"], f"4 screens at once must share one read, got {calls}"
        S._read_tab_for_display(cfg, "T")
        assert calls == ["T"], "a second look within a minute reuses it"
        key = next(iter(S._TAB_CACHE))
        S._TAB_CACHE[key] = (S._TAB_CACHE[key][0] - S.TAB_CACHE_SECONDS - 1, S._TAB_CACHE[key][1])
        S._read_tab_for_display(cfg, "T")
        assert calls == ["T", "T"], "after a minute it reads the sheet again"
    finally:
        S._read_tab = real
        S._TAB_CACHE.clear()


def check_preview_reads_the_campaigns_own_sheet():
    """Bug found 2026-11-06 on the C10 Best 500 lane: the campaign page asked for the tab's
    columns from the app's main sheet, so a lane with its own `sheet_url` showed no columns
    and every Instantly field as "(not in this source)". The run itself was right."""
    from webapp import server as S
    lanes = [{"id": "own", "name": "Own", "tab": "T", "sheet_url": "own-sheet", "priority": 10}]
    real_read, real_cfg, seen = S._read_tab, S.load_config, []

    def fake_read(cfg, tab):
        seen.append(cfg.get("sheet_url"))
        return [{"company_name": "Acme", "final_email": "a@acme.example"}]
    with engine(lanes) as S:
        S._read_tab = fake_read
        S.load_config = lambda: {"sheet_url": "main-sheet", "use_ledger": False}
        S._TAB_CACHE.clear()
        try:
            by_id = S.import_preview("T", campaign="own")
            assert seen[-1] == "own-sheet", f"read {seen[-1]} instead of the campaign's own sheet"
            assert "company_name" in by_id["headers"], by_id
            S._TAB_CACHE.clear()
            S.import_preview("T")
            assert seen[-1] == "own-sheet", "a tab only one campaign reads uses that campaign's sheet"
        finally:
            S._read_tab, S.load_config = real_read, real_cfg
            S._TAB_CACHE.clear()


def check_a_free_tests_leads_can_never_be_sent_live():
    from webapp import server as S
    rid = "zz-test-run-guard"
    S.JOBS[rid] = {"run_id": rid, "status": "finished", "test_mode": True, "kind": "run", "started": "2026-10-05 00:00:00",
                   "stage": "done", "finished": "2026-10-05 00:00:01", "cancel": False,
                   "counters": S._new_counters(), "rates": {}, "events": [], "_seq": 0, "total": 1, "processed": 1,
                   "results": [{"company": "Smith & Co", "found_email": "ian.smith@smithco.co.uk", "verification": "ok", "status": "email_found"}]}
    try:
        r = S.start_push(rid, test_mode=False, confirm=True)
        assert "free test" in (r.get("error") or ""), r
    finally:
        S.JOBS.pop(rid, None)


CHECKS = [check_millionverifier_reads_credits_and_explains_a_bad_key,
          check_a_free_tests_leads_can_never_be_sent_live,
          check_display_reads_share_one_sheet_read,
          check_schedule_preview_uses_the_clocks_maths,
          check_instantly_options_pages_and_names_the_status,
          check_instantly_without_list_scope_still_gives_campaigns,
          check_anymailfinder_and_openai,
          check_reorder_turns_the_drag_order_into_priorities,
          check_campaign_sheet_switch_is_honoured,
          check_switched_off_campaign_refuses_live_but_not_test,
          check_readiness_names_what_to_fix]


def test_all():
    for c in CHECKS:
        c()


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
