"""
research.py — step 1 of the stack: Website research.

Ported 2026-11-06 from northwind/scripts/scrape_firm_sites.py (Stage A of the ice
breaker pipeline). The extraction logic and every lesson in its comments are kept; what
changed:

  * at most 5 pages a company (home + 4), as the approved screen says — the old script
    opened up to 9 for a one-off evidence sweep;
  * the fetch is a plain function passed in, so the SAME code runs on the real web
    (`PlaywrightFetcher`) or on the demo's stand-in web (core/demo_services.py);
  * facts go to the app database (core/store.py). A sheet only ever gets `website_status`.
  * the old Northwind-specific flags (already outsourcing, not a practice, niche) are left out:
    they belonged to one offer, not to a general research step.

A fetch returns {"status", "title", "meta", "heads", "paras", "hrefs", "alts", "quotes"}
or raises when the host cannot be reached at all.

website_status:  found · not_found (no website / parked / empty) ·
                 dead_domain (does not serve pages) · blocked (bot wall or hard 403)
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
NAV_TIMEOUT = 30_000
MAX_PAGES = 5                    # home + 4, the approved screen's "up to 5 pages"
EVIDENCE_CHAR_CAP = 800
REFRESH_DAYS = 30                # researched in the last 30 days -> skipped

# A domain that resolves is NOT the same as a website that serves pages: bare hosts often
# 404 while www serves fine, so never conclude "dead" from the first form alone.
URL_LADDER = ("https://{h}", "https://www.{h}", "http://{h}", "http://www.{h}")

PARKED = ["domain is for sale", "buy this domain", "this domain may be for sale",
          "under construction", "coming soon", "website is being updated",
          "default web page", "welcome to nginx", "apache2 default"]

# ⛔ Bot walls serve HTTP 200 with real-looking text. Without this check the challenge
# page is read as if it were the company's website and an ice breaker is written from it.
BOT_WALL = ["robot challenge screen", "requires cookies to be enabled",
            "checking your browser", "just a moment", "please enable javascript",
            "enable javascript and cookies", "ddos protection", "attention required",
            "verify you are human", "cf-browser-verification", "access denied",
            "security check to access", "why have i been blocked"]

# Internal pages worth opening, best opener first (a live vacancy or an award beats an
# about page: it is the thing they would not expect a stranger to know).
PAGE_PRIORITY = [
    ("careers", ["career", "vacanc", "join-us", "join our team", "jobs", "recruit"]),
    ("news", ["news", "blog", "insight", "article", "latest"]),
    ("awards", ["award", "accreditat", "accolade", "recognition"]),
    ("reviews", ["testimonial", "review", "what-our-clients", "client-feedback"]),
    ("case", ["case-stud", "case stud", "client-stor", "success-stor", "our-work", "portfolio"]),
    ("about", ["about", "who-we-are", "our-story", "why-us", "why-choose"]),
    ("services", ["services", "what-we-do"]),
    ("sectors", ["sectors", "industries", "specialis", "niche"]),
    ("team", ["team", "our-people", "meet"]),
]

# ⛔ blog / news / careers are NOT skipped: they are where the strongest openers come from.
SKIP_LINK = re.compile(
    r"(privacy|cookie|terms|sitemap|login|client-?login|portal|contact|"
    r"\.pdf|\.jpg|\.png|mailto:|tel:|#)", re.I)

SOFTWARE = ["xero", "quickbooks", "sage", "iris", "cch", "taxcalc", "freeagent",
            "dext", "receipt bank", "kashflow", "brightpay", "moneysoft",
            "capium", "nomisma", "clearbooks", "myworkpapers", "senta", "karbon"]

SECTORS = ["dentist", "dental", "doctor", "gp practice", "medical", "contractor",
           "construction", "cis", "landlord", "property", "restaurant", "hospitality",
           "e-commerce", "ecommerce", "amazon", "charit", "solicitor", "law firm",
           "startup", "start-up", "freelance", "locum", "haulage", "logistics", "retail"]

NAME_STOP = {"forensic", "accountant", "accountants", "accounting", "accountancy",
             "chartered", "certified", "limited", "ltd", "llp", "services", "service",
             "tax", "audit", "group", "partners", "partner", "consulting", "consultants",
             "solutions", "associates", "advisory", "advisers", "advisors", "business",
             "financial", "finance", "company", "practice", "management", "expert",
             "witness", "team", "our", "the", "welcome", "contact", "home", "about"}

JOB_WORDS = re.compile(
    r"\b(bookkeeper|accounts (assistant|senior|manager)|semi[- ]senior|audit (senior|junior)"
    r"|tax (senior|assistant|manager)|payroll (clerk|administrator|manager)|practice manager"
    r"|trainee accountant|client manager|accountant)\b", re.I)

AWARD_WORDS = re.compile(
    r"\b(winner|finalist|shortlisted|highly commended|award[- ]winning|top \d+ (firm|accountancy)"
    r"|platinum partner|gold partner|elite partner|firm of the year|accredited)\b", re.I)

SINCE_RE = re.compile(
    r"\b(?:since|established(?: in)?|founded(?: in)?|est\.?|started[^.]{0,40}?in)\s*((?:19|20)\d{2})\b", re.I)
YEARS_RE = re.compile(r"\b(?:over|more than|nearly)?\s*(\d{1,3})\+?\s*years?\b", re.I)
OFFICE_RE = re.compile(r"\b(\d{1,2}|two|three|four|five)\s+(?:offices|branches|locations)\b", re.I)

# An article headline is an h1/h2 INSIDE a page, never the tab title or a button.
INDEX_LABEL = re.compile(
    r"^(our )?(blog|news|insights?|articles?|latest|updates?|resources?)\b"
    r"|\|"
    r"|verification successful|waiting for|just a moment|checking your browser", re.I)

CTA_LABEL = re.compile(
    r"^(sign ?up|subscribe|get |book |contact|request|download|call us|talk to|speak to"
    r"|start |join |welcome to|about us|our services|meet the team|find out more"
    r"|learn more|read more|click here|enquire|why choose|what we do|how can we|current vacancies)"
    r"|love to hear from you|get in touch|free consultation|instant (quote|fee)"
    r"|fee estimate|newsletter|follow us|privacy|cookie|what our clients say", re.I)


# ── small helpers ────────────────────────────────────────────────────

def norm_host(h: str) -> str:
    h = (h or "").strip().lower()
    for p in ("https://", "http://"):
        if h.startswith(p):
            h = h[len(p):]
    for sep in ("/", "?", "#"):
        h = h.split(sep)[0]
    h = h.strip().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def pick_links(hrefs, base_url, cap: int = MAX_PAGES - 1):
    """Rank internal links by PAGE_PRIORITY -> [(url, kind)], at most `cap`."""
    base_host = urlparse(base_url).netloc.lower().replace("www.", "")
    scored = {}
    for h in hrefs or []:
        if not h or SKIP_LINK.search(h):
            continue
        full = urljoin(base_url, h)
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower().replace("www.", "") != base_host:
            continue
        path = (p.path or "/").rstrip("/").lower()
        if not path:
            continue
        for rank, (kind, kws) in enumerate(PAGE_PRIORITY):
            if any(kw in path for kw in kws):
                url = f"{p.scheme}://{p.netloc}{p.path}"
                if url not in scored or rank < scored[url][0]:
                    scored[url] = (rank, kind)
                break
    ordered = sorted(scored.items(), key=lambda kv: kv[1][0])[:cap]
    return [(u, k) for u, (_r, k) in ordered]


def _word_hits(terms, low):
    """Whole words only: 'cis' matched inside 'decisions' (measured 2026-09-02)."""
    return sorted({t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", low)})


def _page_lines(pg):
    return [clean(x) for x in ([pg.get("title") or ""] + (pg.get("heads") or [])
                               + (pg.get("paras") or [])) if clean(x)]


def _is_headline(ln: str, company: str = "") -> bool:
    """A real headline, not a button and not the company's own tagline."""
    if INDEX_LABEL.search(ln) or CTA_LABEL.search(ln):
        return False
    if not (4 <= len(ln.split()) <= 20):
        return False
    if re.fullmatch(r"[\d\s/-]+", ln):
        return False
    for tok in re.findall(r"[A-Za-z]{3,}", company or ""):
        if tok.lower() in NAME_STOP:
            continue
        if re.search(r"\b%s\b" % re.escape(tok), ln, re.I):
            return False
    return True


# ── the extractors (each keeps the URL it came from) ─────────────────

def find_vacancies(pages):
    """Only trust a job title found on a careers page."""
    out = []
    for pg in pages:
        if pg.get("kind") != "careers":
            continue
        for ln in _page_lines(pg):
            m = JOB_WORDS.search(ln)
            if m and len(ln) <= 120:
                out.append({"title": clean(m.group(0)), "line": ln, "url": pg["url"]})
                break
    return out[:3]


def find_posts(pages, company=""):
    out = []
    for pg in pages:
        if pg.get("kind") != "news":
            continue
        for ln in [clean(x) for x in (pg.get("heads") or []) if clean(x)]:
            if _is_headline(ln, company):
                out.append({"title": ln, "url": pg["url"]})
                break
    return out[:3]


def find_reviews(pages):
    out, seen = [], set()
    for pg in pages:
        for q in (pg.get("quotes") or []):
            t = clean(q)
            if not (25 <= len(t) <= 300) or INDEX_LABEL.search(t):
                continue
            if t[:60].lower() in seen:
                continue
            seen.add(t[:60].lower())
            out.append({"quote": t, "url": pg["url"]})
    return out[:3]


def find_cases(pages, company=""):
    out = []
    for pg in pages:
        if pg.get("kind") != "case":
            continue
        for ln in [clean(x) for x in (pg.get("heads") or []) if clean(x)]:
            if re.match(r"^(case stud|client stor|success stor)", ln, re.I):
                continue
            if _is_headline(ln, company):
                out.append({"title": ln, "url": pg["url"]})
                break
    return out[:3]


def find_awards(pages):
    """Badges are usually IMAGES, so alt text is searched too. The whole short line is
    stored, never the bare matched word ('given THE ACCREDITED on your site')."""
    out, seen = [], set()
    for pg in pages:
        for ln in _page_lines(pg) + [clean(a) for a in (pg.get("alts") or []) if clean(a)]:
            if not AWARD_WORDS.search(ln) or len(ln) > 160:
                continue
            if not (2 <= len(ln.split()) <= 12) or ln.lower() in seen:
                continue
            seen.add(ln.lower())
            name = re.sub(r"\s+(badge|logo)$", "", ln.strip(" .,:;-"), flags=re.I)
            out.append({"name": name, "url": pg["url"]})
            break
    return out[:3]


def find_numbers(blob: str):
    n = {}
    m = SINCE_RE.search(blob)
    if m:
        n["since"] = m.group(1)
    m = OFFICE_RE.search(blob)
    if m:
        n["offices"] = m.group(1)
    for m in YEARS_RE.finditer(blob):
        v = int(m.group(1))
        if 5 <= v <= 120:
            n["years"] = str(v)
            break
    m = re.search(r"(over|more than|around|nearly)?\s*([0-9][0-9,]{1,6})\+?\s+"
                  r"(clients|businesses|companies|customers)", blob, re.I)
    if m:
        n["clients"] = clean(m.group(0))
    m = re.search(r"\b(?:team|staff)\s+of\s+([0-9]{1,4})\b|\b([0-9]{1,4})\s+(?:staff|people)\b", blob, re.I)
    if m:
        n["team"] = m.group(1) or m.group(2)
    return n


def build_evidence(title, meta, heads, paras):
    out, used = [], 0
    for chunk in ([title] if title else []) + ([meta] if meta else []) + heads[:4] + paras[:3]:
        c = clean(chunk)
        if not c or c in out:
            continue
        if used + len(c) > EVIDENCE_CHAR_CAP:
            break
        out.append(c)
        used += len(c)
    return out


def fact_count(facts: dict) -> int:
    """How many usable facts a record holds (the Results table's 'Facts' number)."""
    keys = ("vacancies", "awards", "reviews", "cases", "posts", "sectors", "software")
    return sum(len(facts.get(k) or []) for k in keys) + (1 if facts.get("numbers") else 0)


# ── one company ──────────────────────────────────────────────────────

def research_one(company: str, website: str, fetch, *, today: date | None = None) -> dict:
    """Read one company's site with `fetch` and return its research record."""
    host = norm_host(website)
    rec = {"company": company, "host": host, "website_status": "", "detail": "",
           "pages": [], "evidence": [], "facts": {},
           "researched_on": (today or date.today()).isoformat()}
    if not host:
        rec.update(website_status="not_found", detail="no website on the lead")
        return rec

    base, best, home, last_err = None, 0, None, ""
    for tmpl in URL_LADDER:
        url = tmpl.format(h=host)
        try:
            pg = fetch(url)
        except Exception as e:  # noqa: BLE001 - unreachable: try the next URL form
            last_err = str(e)[:100]
            continue
        st = int(pg.get("status") or 0)
        best = st or best
        if st >= 400:
            continue
        text = " ".join([pg.get("title") or "", pg.get("meta") or ""]
                        + (pg.get("heads") or []) + (pg.get("paras") or [])).lower()
        if any(k in text for k in BOT_WALL):
            best = -403
            break
        if len(clean(" ".join([pg.get("title") or ""] + (pg.get("heads") or [])
                              + (pg.get("paras") or [])))) < 40:
            continue
        base, home = url, pg
        break

    if base is None:
        if best in (-403, 403):
            rec.update(website_status="blocked",
                       detail="the site shows a security check" if best == -403 else "the site refused access")
        elif best >= 400:
            rec.update(website_status="dead_domain", detail=f"no website on this domain (HTTP {best})")
        else:
            rec.update(website_status="dead_domain", detail="the domain does not answer")
        return rec

    pages = [{"url": base, "kind": "home", **{k: home.get(k) for k in
              ("title", "heads", "paras", "alts", "quotes")}}]
    meta = home.get("meta") or ""
    for url, kind in pick_links(home.get("hrefs"), base):
        try:
            pg = fetch(url)
        except Exception:  # noqa: BLE001 - one bad page never sinks the company
            continue
        if int(pg.get("status") or 0) >= 400:
            continue
        pages.append({"url": url, "kind": kind, **{k: pg.get(k) for k in
                      ("title", "heads", "paras", "alts", "quotes")}})
        meta = meta or pg.get("meta") or ""

    heads = [h for p in pages for h in (p.get("heads") or [])]
    paras = [x for p in pages for x in (p.get("paras") or [])]
    blob = " ".join([home.get("title") or "", meta] + heads + paras)
    low = blob.lower()
    if any(k in low for k in BOT_WALL):
        rec.update(website_status="blocked", detail="the site shows a security check")
        return rec
    if any(k in low for k in PARKED) and len(blob.strip()) < 400:
        rec.update(website_status="not_found", detail="a parked or placeholder page")
        return rec
    if len(blob.strip()) < 80:
        rec.update(website_status="not_found", detail="the site has no readable text")
        return rec

    rec["evidence"] = build_evidence(home.get("title") or "", meta, heads, paras)
    rec["facts"] = {
        "vacancies": find_vacancies(pages),
        "awards": find_awards(pages),
        "reviews": find_reviews(pages),
        "cases": find_cases(pages, company),
        "posts": find_posts(pages, company),
        "sectors": _word_hits(SECTORS, low)[:6],
        "software": _word_hits(SOFTWARE, low)[:6],
        "numbers": find_numbers(blob),
    }
    rec["pages"] = [{"url": p["url"], "kind": p["kind"], "title": p.get("title") or ""} for p in pages]
    rec.update(website_status="found", detail=f"{len(pages)} pages read")
    return rec


# ── the step ─────────────────────────────────────────────────────────

def run(rows: list[dict], fm, store, source: str, fetch, *, limit: int = 0,
        today: date | None = None, emit=None) -> dict:
    """Research every row not done in the last 30 days. Facts -> app database;
    `website_status` -> the app database through the Research step's allow-list."""
    emit = emit or (lambda *a, **k: None)
    tally = {"processed": 0, "skipped_recent": 0, "found": 0, "not_found": 0,
             "dead_domain": 0, "blocked": 0}
    results = []
    for row in rows:
        key = fm.get(row, "row_key")
        company = fm.get(row, "company_name")
        if not key:
            continue
        if store.researched_recently(source, key, REFRESH_DAYS, today=today):
            tally["skipped_recent"] += 1
            continue
        if limit and tally["processed"] >= limit:
            break
        rec = research_one(company, fm.get(row, "website"), fetch, today=today)
        store.save_facts(source, key, rec)
        store.write_status("research", source, key, {"website_status": rec["website_status"]})
        tally["processed"] += 1
        tally[rec["website_status"]] += 1
        emit(company, "research", rec["website_status"], rec["detail"])
        results.append({"row_key": key, "company": company, "website_status": rec["website_status"],
                        "detail": rec["detail"], "facts": fact_count(rec["facts"])})
    return {**tally, "results": results}


# ── the real web (not used by the demo) ──────────────────────────────

class PlaywrightFetcher:
    """`fetch(url)` on the real web with headless Chromium. Use as a context manager.

    Kept off the demo path on purpose (option A): the demo must give the same answer every
    time. Needs `playwright` and its browser installed in the engine's venv."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # lazy: the demo never needs it
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001 - no bundled browser on this profile: use the installed Chrome
            self._browser = self._pw.chromium.launch(headless=True, channel="chrome")
        self._ctx = self._browser.new_context(user_agent=UA, ignore_https_errors=True)
        self._ctx.set_default_timeout(NAV_TIMEOUT)
        self._page = self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        for x in (self._ctx, self._browser):
            try:
                x.close()
            except Exception:  # noqa: BLE001
                pass
        self._pw.stop()

    def __call__(self, url: str) -> dict:
        page = self._page
        resp = page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        def texts(sel, lo, hi, cap):
            out = []
            for el in page.query_selector_all(sel)[:cap]:
                t = clean(el.inner_text())
                if lo <= len(t) <= hi:
                    out.append(t)
            return out

        meta_el = page.query_selector('meta[name="description"]')
        return {
            "status": resp.status if resp else 0,
            "title": clean(page.title()),
            "meta": clean(meta_el.get_attribute("content") or "") if meta_el else "",
            "heads": texts("h1, h2", 12, 160, 12),
            "paras": texts("p", 60, 320, 40),
            "hrefs": page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"),
            "alts": [clean(a) for a in page.eval_on_selector_all(
                "img[alt]", "els => els.map(e => e.getAttribute('alt'))")[:60] if 3 <= len(clean(a or "")) <= 120],
            "quotes": texts("blockquote, q, [class*=testimonial], [class*=review]", 25, 400, 12),
        }
