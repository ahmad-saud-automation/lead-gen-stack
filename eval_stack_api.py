"""
eval_stack_api.py — the server APIs behind the stack screens (build session 1, step 3).

Lead sources, Leads (list + record), Website research and Find email, all against a
throwaway database. Only the demo may run; live sheets and files are refused; Connect sheet
only reads; no outside service name reaches a screen.
Failed before 2026-11-06: none of these APIs existed.

Run:  python eval_stack_api.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "webapp"))
import server as S                                  # noqa: E402
import eval_demo as E                               # noqa: E402
from core import lead_record as LR                  # noqa: E402

BANNED = ["icypeas", "millionverifier", "million verifier", "anymailfinder", "instantly",
          "northwind outsourcing", "fabrikam", "contoso", "nick", "fieldmap.", ".json"]


def _sandbox():
    tmp = Path(tempfile.mkdtemp(prefix="stack-"))
    S.STACK_DB = tmp / "stack.db"
    # no Google call from an eval: the sheet's tab list is a stand-in
    S.sheet_info = lambda cfg=None: {"ok": True, "detail": "", "title": "Main lead list", "tabs": ["Hiring", "SMEs"]}
    return tmp


def _no_banned(obj, where):
    text = json.dumps(obj, ensure_ascii=False).lower()
    for w in BANNED:
        assert w not in text, (where, w)


def check_pickers_put_the_demo_first_and_only_it_runs():
    _sandbox()
    p = S.stack_pickers()["pickers"]
    assert p[0]["id"] == "demo" and p[0]["runnable"], p[0]
    # 2026-11-06: a campaign marked "pipeline": true (the showcase) runs too; every other stays locked
    pipes = {f"campaign:{c.id}" for c in S._pipeline_camps()}
    assert all(x["runnable"] == (x["id"] in pipes) for x in p[1:]), p[1:]
    assert all(x["why"] for x in p[1:] if x["id"] not in pipes)


def check_leads_before_any_run():
    _sandbox()
    v = S.stack_leads("demo")
    assert len(v["rows"]) == 12, len(v["rows"])
    f = {x["id"]: x["count"] for x in v["filters"]}
    assert f["all"] == 12 and f["not_searched"] == 12, f
    assert all(r["steps"]["email_status"]["value"] == "" for r in v["rows"])
    rec = S.stack_lead("demo", "DM-001")["lead"]
    assert rec["next"] == "Find email" and rec["research"] is None, rec


def check_research_run_reads_back_the_same_values_as_eval_demo():
    _sandbox()
    S.stack_run_find("demo")
    assert S.stack_research("demo")["to_research"] == 8          # only the leads with an email
    r = S.stack_run_research("demo")
    assert r["ok"] and r["found"] == 6 and r["processed"] == 8, r
    v = S.stack_research("demo")
    got = {x["key"]: x["status"]["value"] for x in v["rows"]}
    assert got == {k: w for k, w in E.WEBSITE.items() if w}, got
    assert v["to_research"] == 0 and v["tally"]["found"] == 6, v["tally"]
    one = next(x for x in v["rows"] if x["key"] == "DM-001")
    assert "Open role" in one["chips"] and "Award" in one["chips"], one["chips"]
    assert any(f["url"].startswith("https://harbourvale.example") for f in one["facts"]), one["facts"]
    # labels are lead_record's
    dead = next(x for x in v["rows"] if x["key"] == "DM-007")["status"]
    assert dead["label"] == LR.LABELS["website_status"]["dead_domain"] and dead["tone"] == "bad", dead
    # a second run skips what was researched in the last 30 days
    again = S.stack_run_research("demo")
    assert again["processed"] == 0 and again["skipped_recent"] == 8, again


def check_research_reads_only_leads_with_an_email():
    """His order (2026-11-07): Find email first, then only leads that got an email have their
    website read. Failed before: research read all 12 and ran first."""
    _sandbox()
    r = S.stack_run_research("demo")
    assert r["ok"] and r["processed"] == 0 and r["with_email"] == 0, r
    assert S._stack_store().facts("demo") == {}


def check_find_runs_first_on_every_lead():
    """Find email needs no research: it runs on all 12, website or not. Failed before
    2026-11-07: it refused with "Run Website research first"."""
    _sandbox()
    r = S.stack_run_find("demo")
    assert r["ok"] and r["processed"] == 12, r


def check_find_run_reads_back_the_same_values_as_eval_demo():
    _sandbox()
    r = S.stack_run_find("demo")
    assert r["ok"] and r["found"] == 8 and r["processed"] == 12 and r["would_cost"] > 0, r
    leads = {x["key"]: x for x in S.stack_leads("demo")["rows"]}
    assert {k: x["steps"]["email_status"]["value"] for k, x in leads.items()} == E.EMAIL
    assert leads["DM-002"]["email"] == "daniel.okafor@kestreltax.example"
    f = S.stack_find("demo")
    assert f["processed"] == 12 and f["found"] == 8 and f["ready"] == 0, f
    assert f["from_sheet"] == 3 and f["found_new"] == 4 and f["company_address"] == 1, f
    assert f["no_website"] == 1 and f["not_found"] == 4, f       # DM-006 is now searched (no_email)
    assert len(f["rungs"]) == 5 and sum(x["found"] for x in f["rungs"]) == 8, f["rungs"]
    assert f["rungs"][0]["name"] == "Address in sheet, contact 1" and f["rungs"][0]["found"] == 3, f["rungs"][0]
    assert f["rungs"][4]["name"] == "Company address" and f["rungs"][4]["found"] == 1, f["rungs"][4]
    assert f["would_cost"] == r["would_cost"], (f["would_cost"], r["would_cost"])


def check_one_lead_record_after_both_steps():
    _sandbox()
    S.stack_run_find("demo")
    S.stack_run_research("demo")
    rec = S.stack_lead("demo", "DM-003")["lead"]
    assert rec["email"] == "priya.r@brookfieldledger.example", rec["email"]
    assert rec["next"] == "Ice breakers", rec["next"]
    cols = {s["column"]: s["value"] for s in rec["steps"]}
    assert cols["website_status"] == "found" and cols["email_status"] == "enriched", cols
    assert rec["research"]["pages"] and rec["find"]["steps"], rec
    _no_banned(rec, "DM-003 record")
    assert S.stack_lead("demo", "DM-011")["lead"]["next"].startswith("None"), "no contact = no next step"
    assert "error" in S.stack_lead("demo", "NOPE")["lead"]


def check_only_the_demo_can_run():
    _sandbox()
    for src in ("campaign:anything", "Hiring", "import:x"):
        for fn in (S.stack_run_research, S.stack_run_find):
            r = fn(src)
            assert r["ok"] is False and r["error"], (src, r)
    st = S._stack_store()
    assert st.statuses("Hiring") == {} and st.statuses("campaign:anything") == {}


def check_reset_clears_the_demo():
    _sandbox()
    S.stack_run_find("demo")
    assert S.stack_reset_demo()["ok"]
    assert S._stack_store().statuses("demo") == {}
    assert S.stack_find("demo")["ready"] == 12


def check_sources_list_the_demo_and_the_sheet_without_reading_rows():
    _sandbox()
    v = S.stack_sources()
    ids = [s["id"] for s in v["sources"]]
    assert ids[0] == "demo", ids
    sheet = next(s for s in v["sources"] if s["kind"] == "sheet")
    assert [t["tab"] for t in sheet["tabs"]] == ["Hiring", "SMEs"], sheet
    assert v["columns"] == list(LR.COLUMNS)
    _no_banned(v["sources"][0], "demo source")


class _FakeClient:
    calls: list = []

    def __init__(self, _sa):
        self.client_email = "robot@example.iam"

    def info(self, doc_id):
        _FakeClient.calls.append("info")
        return {"title": "Demo sheet", "tabs": ["Firms"]}

    def _header(self, doc_id, tab):
        _FakeClient.calls.append("_header")
        return ["company_name", "website", "contact_1_name", "email", "Status"]

    def __getattr__(self, name):            # any other call (a write) fails the check
        raise AssertionError(f"Connect sheet called {name}")


def check_connect_sheet_only_reads():
    _sandbox()
    real_cfg, real_client = S.load_config, S.sheets_mod.SheetsClient
    try:
        assert not S.stack_check_sheet("not a link")["ok"]
        S.load_config = lambda: {"sheet_service_account_file": ""}
        assert "key file" in S.stack_check_sheet("https://docs.google.com/spreadsheets/d/abc123/edit")["error"]
        S.load_config = lambda: {"sheet_service_account_file": "x.json"}
        S.sheets_mod.SheetsClient = _FakeClient
        _FakeClient.calls = []
        r = S.stack_check_sheet("https://docs.google.com/spreadsheets/d/abc123/edit")
        assert r["ok"] and r["saved"] is False and r["title"] == "Demo sheet", r
        assert r["tabs"][0]["missing"] == list(LR.COLUMNS), r["tabs"][0]
        assert set(_FakeClient.calls) == {"info", "_header"}, _FakeClient.calls
    finally:
        S.load_config, S.sheets_mod.SheetsClient = real_cfg, real_client


def check_link_local_file():
    tmp = _sandbox()
    csv = tmp / "new-firms.csv"
    csv.write_text("company_name,website\nA Ltd,a.example\nB Ltd,b.example\n", encoding="utf-8")
    saved = {}
    real_cfg, real_save = S.load_config, S.save_config
    try:
        S.load_config = lambda: {"local_tabs": {"old": "C:\\x.csv"}, "sheet_service_account_file": ""}
        S.save_config = lambda patch: saved.update(patch) or patch
        assert "full path" in S.stack_check_local("new-firms.csv")["error"]
        assert "CSV" in S.stack_check_local(str(tmp / "x.xlsx"))["error"]
        c = S.stack_check_local(str(csv))
        assert c["ok"] and c["rows"] == 2 and c["name"] == "new-firms" and not c["clash"], c
        # a sheet tab's name would replace that tab with the file, so it is refused
        bad = S.stack_save_local(str(csv), "Hiring")
        assert not bad["ok"] and "replace" in bad["error"] and not saved, bad
        ok = S.stack_save_local(str(csv), "new-firms")
        assert ok["ok"] and saved["local_tabs"] == {"old": "C:\\x.csv", "new-firms": str(csv)}, saved
    finally:
        S.load_config, S.save_config = real_cfg, real_save


def check_no_service_names_on_any_screen():
    _sandbox()
    S.stack_run_research("demo")
    S.stack_run_find("demo")
    for name, body in (("leads", S.stack_leads("demo")), ("research", S.stack_research("demo")),
                       ("find", S.stack_find("demo"))):
        _no_banned({k: v for k, v in body.items() if k != "name"}, name)
    for key in E.EMAIL:
        _no_banned(S.stack_lead("demo", key)["lead"], key)


def check_a_huge_tab_sends_only_the_first_rows():
    """A campaign tab with 21,095 rows froze the browser; each filter now sends its first 500."""
    from core import fieldmap as fm_mod, stack_view as V
    _sandbox()
    fm = fm_mod.FieldMap({"row_key": "id", "company_name": "co", "email_status": "email_status"})
    rows = [{"id": f"R{i}", "co": f"Firm {i}", "email_status": "as-is" if i % 2 else ""} for i in range(1200)]
    v = V.leads_view(rows, fm, S._stack_store(), "big", show=500)
    f = {x["id"]: x["count"] for x in v["filters"]}
    assert v["total"] == 1200 and f["all"] == 1200 and f["not_searched"] == 600, (v["total"], f)
    assert 500 <= len(v["rows"]) <= 1000, len(v["rows"])
    assert sum(1 for r in v["rows"] if "not_searched" in r["filters"]) >= 500


def check_a_missing_tab_is_said_in_plain_words():
    e = Exception('<HttpError 400 returned "Unable to parse range: \'Practices\'". Details: ...>')
    msg = S._plain_read_error(e)
    assert msg.startswith("The tab 'Practices' is not in this campaign's Google Sheet"), msg
    assert "HttpError" not in msg


CHECKS = [check_a_huge_tab_sends_only_the_first_rows, check_a_missing_tab_is_said_in_plain_words,
          check_pickers_put_the_demo_first_and_only_it_runs, check_leads_before_any_run,
          check_research_run_reads_back_the_same_values_as_eval_demo, check_research_reads_only_leads_with_an_email,
          check_find_runs_first_on_every_lead,
          check_find_run_reads_back_the_same_values_as_eval_demo, check_one_lead_record_after_both_steps,
          check_only_the_demo_can_run, check_reset_clears_the_demo,
          check_sources_list_the_demo_and_the_sheet_without_reading_rows,
          check_connect_sheet_only_reads, check_link_local_file, check_no_service_names_on_any_screen]


def test_all():
    for c in CHECKS:
        c()


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
