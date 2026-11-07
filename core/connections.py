"""
connections.py — "is this key working?" and "what can I pick from?", without spending.

Every call here is a READ that costs no credits:
    MillionVerifier  GET /api/v3/credits          -> credits left
    Anymailfinder    GET /v5.1/account            -> credits left
    Instantly        GET /api/v2/campaigns        -> the campaign dropdown (and the key test)
                     GET /api/v2/lead-lists       -> the "also add to a list" dropdown
    OpenAI           GET /v1/models               -> key test
Icypeas has no free account call (it needs the account's e-mail), so it is not tested here —
the screen says so instead of pretending.

All HTTP goes through `_get_json`, which the tests replace. Every request carries net.py's
User-Agent: urllib's default one is blocked by Cloudflare and looks exactly like a dead key.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import net

MV_CREDITS = "https://api.millionverifier.com/api/v3/credits"
AMF_ACCOUNT = "https://api.anymailfinder.com/v5.1/account"
INSTANTLY = "https://api.instantly.ai/api/v2"
OPENAI_MODELS = "https://api.openai.com/v1/models"

# Instantly's numeric campaign status, in words
INSTANTLY_STATUS = {0: "draft", 1: "active", 2: "paused", 3: "completed", 4: "running subsequences",
                    -1: "accounts unhealthy", -2: "bounce protection", -99: "suspended"}


def _get_json(url: str, headers: dict | None = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=net.headers(headers))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def _why(e: Exception, service: str) -> str:
    """An error in words a person can act on."""
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return f"{service} refused the key — check it was copied in full"
        if e.code == 429:
            return f"{service} says too many requests — try again in a minute"
        return f"{service} answered with an error ({e.code})"
    if isinstance(e, urllib.error.URLError):
        return f"could not reach {service} — check the internet connection"
    return f"{service}: {e}"


def _missing(service: str) -> dict:
    return {"ok": False, "detail": f"no {service} key saved yet"}


def test_millionverifier(key: str) -> dict:
    if not key:
        return _missing("MillionVerifier")
    try:
        r = _get_json(MV_CREDITS + "?" + urllib.parse.urlencode({"api": key}))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _why(e, "MillionVerifier")}
    if "credits" not in r:
        return {"ok": False, "detail": str(r.get("error") or "MillionVerifier did not accept the key")}
    return {"ok": True, "detail": f"{int(r['credits']):,} checks left", "credits": int(r["credits"])}


def test_anymailfinder(key: str) -> dict:
    if not key:
        return _missing("Anymailfinder")
    try:
        r = _get_json(AMF_ACCOUNT, {"Authorization": "Bearer " + key})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _why(e, "Anymailfinder")}
    left = r.get("credits_left")
    return {"ok": True, "detail": f"{int(left):,} credits left" if left is not None else "key accepted"}


def test_openai(key: str) -> dict:
    if not key:
        return _missing("OpenAI")
    try:
        _get_json(OPENAI_MODELS, {"Authorization": "Bearer " + key})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _why(e, "OpenAI")}
    return {"ok": True, "detail": "key accepted"}


def _instantly_all(path: str, key: str, max_pages: int = 10) -> list[dict]:
    """Every item of a paginated Instantly list (100 a page, at most `max_pages` pages)."""
    items, after = [], ""
    for _ in range(max_pages):
        q = {"limit": "100"}
        if after:
            q["starting_after"] = after
        r = _get_json(f"{INSTANTLY}/{path}?{urllib.parse.urlencode(q)}", {"Authorization": "Bearer " + key})
        items += r.get("items") or []
        after = r.get("next_starting_after") or ""
        if not after:
            break
    return items


def instantly_options(key: str) -> dict:
    """The dropdowns on the campaign page: Instantly campaigns and lead lists."""
    if not key:
        return {"ok": False, "detail": "no Instantly key saved yet", "campaigns": [], "lists": []}
    try:
        camps = _instantly_all("campaigns", key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": _why(e, "Instantly"), "campaigns": [], "lists": []}
    try:
        lists = _instantly_all("lead-lists", key)
    except Exception:  # noqa: BLE001 - a key without list scope still gives the campaigns
        lists = []
    picks = sorted(({"id": c["id"], "name": c.get("name") or c["id"],
                     "status": INSTANTLY_STATUS.get(c.get("status"), str(c.get("status", "")))}
                    for c in camps if c.get("id")), key=lambda c: c["name"].lower())
    # the count is of what the dropdown shows, so the two never disagree
    return {
        "ok": True, "detail": f"{len(picks)} campaign{'s' if len(picks) != 1 else ''} found",
        "campaigns": picks,
        "lists": sorted(({"id": x["id"], "name": x.get("name") or x["id"]}
                         for x in lists if x.get("id")), key=lambda x: x["name"].lower()),
    }


def test_instantly(key: str) -> dict:
    r = instantly_options(key)
    return {"ok": r["ok"], "detail": r["detail"]}
