"""
live_services.py — the REAL services behind the new pipeline pages, for campaigns marked
`"pipeline": true` (2026-11-06: the Pipeline showcase). Same shapes as core/demo_services.py,
so every step function runs unchanged:

  LiveServices.fetch(url)      → the real web (headless Chromium, research.PlaywrightFetcher)
  LiveServices.verify(email)   → the email check service (verify.verify_email)
  LiveServices.find(firm)      → the email finder (finders.find_icypeas)
  InstantlyDraftPlatform       → adds leads to ONE Instantly campaign, and only while that
                                 campaign is a Draft or Paused: `confirm_draft()` asks
                                 Instantly right before a push and refuses anything else.
  InstantlyInbox               → replies Instantly received for that campaign

⛔ Nothing here can make an email go out: a Draft or Paused campaign does not send. A
campaign that turns Active between two runs is refused at the next push.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import finders, instantly, net, research, verify

INSTANTLY_API = "https://api.instantly.ai/api/v2"
SAFE_STATUS = {0: "Draft", 2: "Paused"}
STATUS_NAME = {0: "Draft", 1: "Active", 2: "Paused", 3: "Completed", 4: "Running subsequences",
               -1: "Accounts unhealthy", -2: "Bounce protect", -99: "Suspended"}
PRICE_CHECK_USD = 0.002
PRICE_FINDER_USD = 0.03


class LiveServices:
    """The three real services and how often each was called. Use as a context manager:
    the browser opens on the first fetch and closes on exit."""

    def __init__(self, verify_key: str, finder_key: str, fetcher_factory=None):
        self.verify_key = str(verify_key or "").strip()
        self.finder_key = str(finder_key or "").strip()
        self._factory = fetcher_factory or research.PlaywrightFetcher
        self._fetcher = None
        self.calls = {"fetch": 0, "check": 0, "finder": 0}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._fetcher is not None:
            try:
                self._fetcher.__exit__(*exc)
            finally:
                self._fetcher = None

    def fetch(self, url: str) -> dict:
        """The PC's DNS drops some lookups (measured 2026-11-06: 3 of 10 live firms failed
        locally, all 10 answered on 8.8.8.8), so a name that does not resolve is asked
        again twice before the site counts as unreachable."""
        self.calls["fetch"] += 1
        if self._fetcher is None:
            self._fetcher = self._factory().__enter__()
        for attempt in range(3):
            try:
                return self._fetcher(url)
            except Exception as e:  # noqa: BLE001
                if "NAME_NOT_RESOLVED" not in str(e) or attempt == 2:
                    raise
                self._sleep(1.5 * (attempt + 1))
        raise ConnectionError(url)       # not reached

    @staticmethod
    def _sleep(s: float) -> None:
        import time
        time.sleep(s)

    def verify(self, email: str) -> dict:
        if not self.verify_key:
            return {"email": email, "accepted": False, "verification": "error",
                    "error": "No email check key saved in Settings."}
        self.calls["check"] += 1
        return verify.verify_email(email, self.verify_key)

    def find(self, firm: dict) -> dict:
        if not self.finder_key:
            return {"error": "No email finder key saved in Settings."}
        self.calls["finder"] += 1
        return finders.find_icypeas(firm, self.finder_key)

    def would_cost(self) -> float:
        return round(self.calls["check"] * PRICE_CHECK_USD + self.calls["finder"] * PRICE_FINDER_USD, 4)


def _get(path: str, key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(f"{INSTANTLY_API}/{path}",
                                 headers=net.headers({"Authorization": "Bearer " + key}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


class InstantlyDraftPlatform:
    """The sending platform for a pipeline campaign. `draft_only` is what core/sending.run
    checks; it then calls `confirm_draft()` once before the first lead."""

    test_only = False
    draft_only = True

    def __init__(self, api_key: str, campaign_id: str, campaign_name: str = "", *, get=None, push=None):
        self.key = str(api_key or "").strip()
        self.campaign_id = str(campaign_id or "").strip()
        self.campaign = campaign_name or "Instantly campaign"
        self._get = get or _get
        self._push = push or instantly._http_push
        self.added: list[dict] = []
        self.status = ""

    def confirm_draft(self) -> str:
        """'' when the campaign is a Draft or Paused right now; otherwise why not, in plain words."""
        if not self.key:
            return "No Instantly key saved in Settings. Nothing was sent."
        if not self.campaign_id:
            return "This campaign has no Instantly campaign. Nothing was sent."
        try:
            c = self._get(f"campaigns/{urllib.parse.quote(self.campaign_id)}", self.key)
        except Exception as e:  # noqa: BLE001
            return f"Could not ask Instantly about the campaign ({str(e)[:120]}). Nothing was sent."
        st = c.get("status")
        self.status = STATUS_NAME.get(st, str(st))
        if c.get("name"):
            self.campaign = str(c["name"])
        if st not in SAFE_STATUS:
            return (f"The Instantly campaign is {self.status}. The app adds leads only to a Draft or "
                    "Paused campaign, so no email can go out. Nothing was sent.")
        return ""

    def add(self, lead: dict) -> dict:
        first = str(lead.get("first_name") or "")
        payload = {"campaign": self.campaign_id, "email": lead["email"], "first_name": first,
                   "company_name": lead.get("company", ""),
                   "custom_variables": {"subject": lead.get("subject", ""), "body": lead.get("body", ""),
                                        "lead_id": str(lead.get("key", ""))}}
        res = self._push(payload, self.key)
        if not res.get("ok"):
            raise RuntimeError(f"Instantly answered {res.get('status_code')}")
        self.added.append(dict(lead))
        return {"ok": True, "id": (res.get("response") or {}).get("id", "")}


class InstantlyInbox:
    """Replies Instantly received for the campaign, matched back to leads by address."""

    def __init__(self, api_key: str, campaign_id: str, email_of: dict, *, get=None):
        self.key = str(api_key or "").strip()
        self.campaign_id = str(campaign_id or "").strip()
        self.email_of = {k: str(v or "").lower() for k, v in (email_of or {}).items()}
        self._get = get or _get

    def __call__(self, pushed_keys, now=None):
        if not (self.key and self.campaign_id and pushed_keys):
            return []
        want = {self.email_of.get(str(k), ""): str(k) for k in pushed_keys}
        want.pop("", None)
        q = urllib.parse.urlencode({"campaign_id": self.campaign_id, "email_type": "received", "limit": "100"})
        items = self._get(f"emails?{q}", self.key).get("items") or []
        out = []
        for m in items:
            sender = str(m.get("from_address_email") or m.get("lead") or "").lower()
            key = want.get(sender)
            if not key:
                continue
            body = (m.get("body") or {})
            text = body.get("text") if isinstance(body, dict) else str(body)
            out.append({"key": key, "message": str(text or m.get("content_preview") or "").strip(),
                        "received": str(m.get("timestamp_email") or m.get("timestamp_created") or "")[:19].replace("T", " ")})
        return out
