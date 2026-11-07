"""
demo_services.py — stand-ins for the outside services (his option A, 2026-11-06).

The demo must cost $0 and give the same result every time, so only the OUTSIDE calls are
faked: the web fetch, the email check and the email finder. Everything between them —
research extraction, the recipe planner, the pipeline, the lead record, the store — is the
real code.

Answers come from data/demo/demo-sites.json. Every domain ends in `.example`, a name the
internet reserves and never resolves, so nothing here can reach a real company even by
mistake.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from . import research

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "data" / "demo"
SITES_FILE = DEMO_DIR / "demo-sites.json"
FIRMS_FILE = DEMO_DIR / "demo-firms.csv"
DEMO_SOURCE = "demo"                       # the store's source name for the demo firms
DEMO_FIELDMAP = ROOT / "config" / "fieldmap.demo.json"
DEMO_RECIPE = ROOT / "config" / "recipes" / "demo-waterfall.json"

# what each call WOULD cost on the real services, so the screen can say so
PRICE_CHECK_USD = 0.002
PRICE_FINDER_USD = 0.03


def _load(path=SITES_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class DemoServices:
    """One object holding the three stand-ins and how often each was called."""

    def __init__(self, path=SITES_FILE):
        data = _load(path)
        self.sites = data.get("sites") or {}
        self.mailboxes = {m.lower() for m in data.get("mailboxes") or []}
        self.finder_answers = {k.lower(): v for k, v in (data.get("finder") or {}).items()}
        self.calls = {"fetch": 0, "check": 0, "finder": 0}

    def __enter__(self):                # same shape as core/live_services.LiveServices
        return self

    def __exit__(self, *exc):
        return None

    # ── the web ──────────────────────────────────────────────────

    def fetch(self, url: str) -> dict:
        self.calls["fetch"] += 1
        p = urlparse(url)
        host = research.norm_host(p.netloc)
        site = self.sites.get(host)
        if not site or site.get("status") == "unreachable":
            raise ConnectionError(f"{host} does not answer")
        st = int(site.get("status") or 0)
        if st >= 400:
            return {"status": st}
        page = (site.get("pages") or {}).get(p.path or "/")
        if page is None:
            return {"status": 404}
        return {"status": 200, **page}

    # ── the email check ──────────────────────────────────────────

    def verify(self, email: str) -> dict:
        self.calls["check"] += 1
        ok = str(email or "").strip().lower() in self.mailboxes
        return {"email": email, "accepted": ok, "verification": "ok" if ok else "invalid"}

    # ── the email finder ─────────────────────────────────────────

    def find(self, firm: dict) -> dict:
        """Same shape as the real finder: {'email'} or {'error'}."""
        self.calls["finder"] += 1
        name = str(firm.get("lead_director") or "").strip()
        domain = research.norm_host(firm.get("lead_domain") or "")
        hit = self.finder_answers.get(f"{name}|{domain}".lower())
        return {"email": hit} if hit else {"error": "not found"}

    def would_cost(self) -> float:
        return round(self.calls["check"] * PRICE_CHECK_USD
                     + self.calls["finder"] * PRICE_FINDER_USD, 4)


RULESET_FILE = DEMO_DIR / "demo-ruleset.json"
TEMPLATES_FILE = DEMO_DIR / "demo-templates.json"
REPLIES_FILE = DEMO_DIR / "demo-replies.json"
DEMO_SENDING_CAMPAIGN = "Demo sending campaign"


class DemoSendingPlatform:
    """Stand-in for the sending platform (build session 2). Keeps the leads it was given in a
    list and nothing else: no network, no key, no real campaign. `test_only` is what
    core/sending.run checks before it will hand over a single lead."""

    test_only = True
    campaign = DEMO_SENDING_CAMPAIGN

    def __init__(self):
        self.added: list[dict] = []

    def add(self, lead: dict) -> dict:
        if not str(lead.get("email", "")).lower().endswith(".example"):
            raise ValueError("The demo sends only to .example addresses.")
        self.added.append(dict(lead))
        return {"ok": True, "id": f"demo-{len(self.added)}"}


class DemoInbox:
    """Stand-in reply inbox: a fixed reply for some demo leads, returned only once that lead
    was pushed. The received time is a fixed number of minutes before the check."""

    def __init__(self, path=REPLIES_FILE):
        self.replies = (_load(path).get("replies") or {})

    def __call__(self, pushed_keys, now=None):
        from datetime import datetime, timedelta
        now = now or datetime.now()
        out = []
        for key in pushed_keys:
            r = self.replies.get(str(key))
            if r:
                t = now - timedelta(minutes=int(r.get("minutes_ago") or 0))
                out.append({"key": str(key), "message": r["message"], "received": t.strftime("%Y-%m-%d %H:%M:%S")})
        return out


def demo_writer(path=TEMPLATES_FILE):
    """Stand-in for Claude working the template queue: one fixed draft per request type."""
    canned = _load(path).get("writer") or {}

    def write(kind: str, instructions: str) -> dict:
        d = canned.get(kind) or canned.get("new") or {}
        return {"subject": d.get("subject", ""), "body": d.get("body", "")}
    return write


class DemoWriteLimit:
    """Stand-in for a sheet that refuses a write now and then (Google's 429), so the Live
    demo gives the health agent a real, known issue to fix (build session 3).

    The `nth` status write of `stage` raises WriteLimit `times` times, then succeeds. Every
    other call passes straight to the real store. Same result every run."""

    def __init__(self, inner, stage: str = "find_email", nth: int = 5, times: int = 1):
        self._inner = inner
        self.stage, self.nth, self.left = stage, nth, times
        self.seen = 0

    def write_status(self, stage, source, key, values):
        from .health import WriteLimit
        if stage == self.stage:
            if self.left > 0 and self.seen + 1 == self.nth:
                self.left -= 1
                raise WriteLimit("write limit reached")
            self.seen += 1
        return self._inner.write_status(stage, source, key, values)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def demo_rows() -> list[dict]:
    import csv
    with open(FIRMS_FILE, encoding="utf-8-sig", newline="") as f:
        return [{(k or "").strip(): (v or "") for k, v in r.items()} for r in csv.DictReader(f)]
