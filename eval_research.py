"""
eval_research.py — step 1, Website research (core/research.py + core/store.py).

Every check failed before 2026-11-06: neither module existed. They run on the stand-in
web only, so no network is touched.

Run:  python eval_research.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from core import fieldmap as fieldmap_mod
from core import lead_record as LR
from core import research
from core import store as store_mod


def _web(sites: dict):
    """A tiny stand-in web: {host: {"status": 200, "pages": {path: page}}}."""
    from urllib.parse import urlparse

    def fetch(url):
        p = urlparse(url)
        site = sites.get(research.norm_host(p.netloc))
        if site is None or site.get("status") == "unreachable":
            raise ConnectionError("no answer")
        if site["status"] >= 400:
            return {"status": site["status"]}
        page = site["pages"].get(p.path or "/")
        return {"status": 200, **page} if page else {"status": 404}
    return fetch


HOME = {"title": "Acme Accounts | Leeds", "meta": "Accountants.",
        "heads": ["Tax and payroll for Leeds businesses"],
        "paras": ["Established in 2003, we look after over 250 clients with a team of 12 using Xero.",
                  "We specialise in dental practices and construction contractors across Yorkshire."],
        "hrefs": ["/careers", "/news", "/contact", "/privacy", "https://other.example/x",
                  "/about", "/services", "/team", "/awards"],
        "alts": ["Xero Platinum Partner logo"], "quotes": []}
SITES = {
    "acme.example": {"status": 200, "pages": {
        "/": HOME,
        "/careers": {"title": "Careers", "heads": ["Join us"], "paras": [],
                     "hrefs": [], "alts": [], "quotes": [], "meta": ""},
        "/news": {"title": "News | Acme", "heads": ["Our blog", "Making Tax Digital starts for landlords in April"],
                  "paras": [], "hrefs": []},
        "/about": {"title": "About", "heads": [], "paras": [], "hrefs": []},
        "/services": {"title": "Services", "heads": [], "paras": [], "hrefs": []},
        "/awards": {"title": "Awards", "heads": ["Winner, Small Practice of the Year"], "paras": [], "hrefs": []},
        "/team": {"title": "Team", "heads": [], "paras": [], "hrefs": []}}},
    "gone.example": {"status": 404, "pages": {}},
    "silent.example": {"status": "unreachable", "pages": {}},
    "wall.example": {"status": 200, "pages": {"/": {"title": "Just a moment...",
                     "heads": ["Checking your browser"], "paras": ["Please wait while we check."]}}},
    "parked.example": {"status": 200, "pages": {"/": {"title": "This domain may be for sale",
                       "heads": ["Buy this domain today"], "paras": []}}},
}


def check_at_most_five_pages_and_never_contact_or_privacy():
    links = research.pick_links(HOME["hrefs"], "https://acme.example")
    assert len(links) == research.MAX_PAGES - 1 == 4, links
    kinds = [k for _u, k in links]
    assert kinds[:2] == ["careers", "news"], kinds          # best opener first
    assert not any("contact" in u or "privacy" in u or "other.example" in u for u, _k in links)
    rec = research.research_one("Acme Accounts", "acme.example", _web(SITES))
    assert len(rec["pages"]) <= 5, rec["pages"]


def check_every_website_status_is_reachable():
    web = _web(SITES)
    got = {h: research.research_one("Acme Accounts", h, web)["website_status"]
           for h in ("acme.example", "gone.example", "silent.example", "wall.example",
                     "parked.example", "")}
    assert got == {"acme.example": "found", "gone.example": "dead_domain",
                   "silent.example": "dead_domain", "wall.example": "blocked",
                   "parked.example": "not_found", "": "not_found"}, got
    assert set(got.values()) == set(LR.VALUES["website_status"])


def check_facts_keep_the_url_they_came_from():
    rec = research.research_one("Acme Accounts", "https://www.acme.example/", _web(SITES))
    f = rec["facts"]
    assert f["awards"][0]["name"] == "Xero Platinum Partner", f["awards"]   # alt text, "logo" trimmed
    assert f["posts"] == [{"title": "Making Tax Digital starts for landlords in April",
                           "url": "https://acme.example/news"}], f["posts"]  # not "Our blog"
    assert f["vacancies"] == [], "a careers page with no job title is not a vacancy"
    assert f["software"] == ["xero"] and "dental" in f["sectors"], f
    assert f["numbers"]["since"] == "2003" and f["numbers"]["team"] == "12", f["numbers"]
    assert sum(len(x) for x in rec["evidence"]) <= research.EVIDENCE_CHAR_CAP


def check_a_bot_wall_is_never_read_as_the_site():
    rec = research.research_one("Wall Ltd", "wall.example", _web(SITES))
    assert rec["website_status"] == "blocked" and rec["facts"] == {} and rec["evidence"] == []


def check_facts_go_to_the_app_and_the_sheet_column_only_gets_website_status():
    st = store_mod.Store(Path(tempfile.mkdtemp()) / "t.db")
    fm = fieldmap_mod.FieldMap({"row_key": "lead_id", "company_name": "company", "website": "site"})
    rows = [{"lead_id": "A", "company": "Acme Accounts", "site": "acme.example", "Status": "his note"},
            {"lead_id": "B", "company": "Gone Ltd", "site": "gone.example", "Status": ""}]
    out = research.run(rows, fm, st, "t", _web(SITES))
    assert out["processed"] == 2 and out["found"] == 1 and out["dead_domain"] == 1, out
    assert st.statuses("t") == {"A": {"website_status": "found"}, "B": {"website_status": "dead_domain"}}
    assert st.facts("t")["A"]["facts"]["awards"], "facts are stored in the app"
    # the research step may not write anything but its own column
    for bad in ({"email_status": "enriched"}, {"Status": "x"}, {"website_status": "great"}):
        try:
            st.write_status("research", "t", "A", bad)
        except LR.WriteRefused:
            continue
        raise AssertionError(f"research wrote {bad}")
    assert rows[0]["Status"] == "his note", "the source rows are never changed"


def check_researched_in_the_last_30_days_is_skipped():
    st = store_mod.Store(Path(tempfile.mkdtemp()) / "t.db")
    fm = fieldmap_mod.FieldMap({"row_key": "lead_id", "company_name": "company", "website": "site"})
    rows = [{"lead_id": "A", "company": "Acme Accounts", "site": "acme.example"}]
    day = date(2026, 11, 6)
    research.run(rows, fm, st, "t", _web(SITES), today=day)
    again = research.run(rows, fm, st, "t", _web(SITES), today=day + timedelta(days=29))
    assert again["processed"] == 0 and again["skipped_recent"] == 1, again
    later = research.run(rows, fm, st, "t", _web(SITES), today=day + timedelta(days=30))
    assert later["processed"] == 1, later


CHECKS = [check_at_most_five_pages_and_never_contact_or_privacy,
          check_every_website_status_is_reachable,
          check_facts_keep_the_url_they_came_from,
          check_a_bot_wall_is_never_read_as_the_site,
          check_facts_go_to_the_app_and_the_sheet_column_only_gets_website_status,
          check_researched_in_the_last_30_days_is_skipped]


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
