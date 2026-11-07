"""
net.py — one User-Agent for every outbound call.

Why this exists: urllib defaults to `User-Agent: Python-urllib/3.x`, and
MillionVerifier sits behind Cloudflare, which blocks that signature with
HTTP 403 "error code: 1010" before the request ever reaches their API.

The symptom is nasty because it looks like a dead key: every verification
comes back `error`, so every firm ends `email_not_found` and the run reports
0 found while still counting the credits it thought it spent. Three real runs
on 2026-07-30 died this way on a key that had 47,712 credits sitting on it.

Any UA at all is enough — Cloudflare is blocking the default, not us. Send an
honest one so the block stays diagnosable if a provider ever bans us on purpose.
"""
from __future__ import annotations

USER_AGENT = "LeadGenAutomationEngine/1.0 (+local)"


def headers(extra: dict | None = None) -> dict:
    """Merge a UA into a header dict. Explicit headers win."""
    h = {"User-Agent": USER_AGENT}
    h.update(extra or {})
    return h
