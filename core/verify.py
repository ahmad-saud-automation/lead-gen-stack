"""
verify.py — verify candidate emails with MillionVerifier, using V7's exact
accept/reject tiers, and stop at the first accepted one (fewest verifications).

Tiers (a faithful copy of V7's "Normalize MillionVerifier Result"):
  PASS  (accept)        : good · ok · valid · deliverable · verified
  RISKY (catch-all)     : risky · catch_all · unknown · accept_all …
                          → accepted ONLY when accept_catchall is on
  BAD   (always reject) : bad · invalid · undeliverable · disposable · do_not_mail
                          also resultcode 6, or subresult no_mailbox/dns_error/quota

Cost-minimal: `find_verified_email` tries candidates in order and STOPS at the
first accepted result, so we pay for the fewest verifications.

NO-SPEND TEST MODE: pass test_mode=True (or a custom transport) to run the whole
pipeline with zero API calls, zero credits, and no key — for demos and tests.

Uses only the standard library (urllib). The key is read from MILLIONVERIFIER_API_KEY
in the environment / .env, never hardcoded.
"""
from __future__ import annotations

import os
import json
import urllib.parse
import urllib.request

from . import net
from . import retry as retry_mod

MV_ENDPOINT = "https://api.millionverifier.com/api/v3/"

PASS_VALUES = {"good", "ok", "valid", "deliverable", "verified"}
CATCHALL_VALUES = {"risky", "catch_all", "catch-all", "unknown", "accept_all",
                   "acceptall", "catchall"}
REJECT_VALUES = {"bad", "invalid", "undeliverable", "do_not_mail", "disposable"}
REJECT_SUBRESULTS = {"no_mailbox", "dns_error", "mailbox_quota_exceeded"}


def _lc(v) -> str:
    return str(v or "").strip().lower()


def classify_response(resp: dict, accept_catchall: bool = False) -> dict:
    """Pure: turn a MillionVerifier response into a verdict (V7 rules). Testable offline."""
    quality = _lc(resp.get("quality"))
    result = _lc(resp.get("result") or resp.get("status"))
    subresult = _lc(resp.get("subresult"))
    resultcode = _lc(resp.get("resultcode"))
    mv = _lc(resp.get("quality") or resp.get("result") or resp.get("status") or resp.get("resultcode"))
    email = _lc(resp.get("email") or resp.get("address"))

    has_good = mv in PASS_VALUES or quality in PASS_VALUES or result in PASS_VALUES
    has_reject = (mv in REJECT_VALUES or quality in REJECT_VALUES or result in REJECT_VALUES
                  or subresult in REJECT_VALUES or resultcode == "6"
                  or subresult in REJECT_SUBRESULTS)
    is_catchall = (mv in CATCHALL_VALUES or quality in CATCHALL_VALUES
                   or result in CATCHALL_VALUES or subresult in CATCHALL_VALUES)

    accepted = bool(email) and not has_reject and (has_good or (accept_catchall and is_catchall))
    tier = "pass" if has_good else ("bad" if has_reject else ("catch_all" if is_catchall else "unknown"))
    verification = mv or result or quality or subresult or ("good" if accepted else "not_found")
    return {"accepted": accepted, "tier": tier, "verification": verification}


# ── transports (real vs no-spend test) ──────────────────────────────

def _http_transport(email: str, api_key: str, timeout: int = 10) -> dict:
    q = urllib.parse.urlencode({"api": api_key, "email": email, "timeout": str(timeout)})
    req = urllib.request.Request(MV_ENDPOINT + "?" + q, headers=net.headers())
    with urllib.request.urlopen(req, timeout=timeout + 5) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def test_transport(email: str, api_key: str = "", timeout: int = 10) -> dict:
    """No-spend stub. Makes NO network call — it invents a verdict from the address
    shape (dotted first.last -> ok, bare first -> unknown). Results are SIMULATED:
    nothing has confirmed the mailbox exists, so they must never be mailed."""
    local = email.split("@")[0]
    result = "ok" if "." in local else "unknown"
    return {"email": email, "result": result, "quality": result,
            "resultcode": "1" if result == "ok" else "2", "simulated": True}


# ── verify one / find the first that verifies ───────────────────────

def verify_email(email: str, api_key: str | None = None, *, accept_catchall: bool = False,
                 timeout: int = 10, test_mode: bool = False, transport=None,
                 tries: int = 3, retry_wait: float = 5.0, on_retry=None) -> dict:
    key = (api_key if api_key is not None else os.environ.get("MILLIONVERIFIER_API_KEY", "")).strip()
    if transport is None:
        transport = test_transport if test_mode else _http_transport
    attempts = 1 if test_mode else max(1, int(tries or 1))   # the stub can't fail transiently
    try:
        resp = retry_mod.call(transport, email, key, timeout,
                              tries=attempts, wait=retry_wait, on_retry=on_retry) or {}
    except Exception as e:  # noqa: BLE001 — a dead API must not kill the run
        return {"email": email, "accepted": False, "tier": "error",
                "verification": "error", "error": str(e), "raw": {}}
    resp.setdefault("email", email)                 # so the accepted-check has an email
    verdict = classify_response(resp, accept_catchall)
    verdict.update({"email": email, "raw": resp, "simulated": bool(resp.get("simulated"))})
    return verdict


def find_verified_email(candidates, api_key: str | None = None, *, accept_catchall: bool = False,
                        test_mode: bool = False, transport=None, on_check=None) -> dict:
    """Try candidates in order; STOP at the first accepted. Returns the result
    plus how many verifications were used (the cost lever)."""
    checked = []
    for c in candidates:
        email = c["email"] if isinstance(c, dict) else c
        v = verify_email(email, api_key, accept_catchall=accept_catchall,
                         test_mode=test_mode, transport=transport)
        v["source"] = c.get("source", "") if isinstance(c, dict) else ""
        v["pattern"] = c.get("pattern", "") if isinstance(c, dict) else ""
        checked.append(v)
        if on_check:
            on_check(v)
        if v["accepted"]:
            return {"found_email": email, "verification": v["verification"], "tier": v["tier"],
                    "source": v["source"], "pattern": v["pattern"],
                    "checked": checked, "verifications_used": len(checked)}
    return {"found_email": "", "verification": "not_found",
            "tier": checked[-1]["tier"] if checked else "none",
            "source": "", "pattern": "", "checked": checked, "verifications_used": len(checked)}
