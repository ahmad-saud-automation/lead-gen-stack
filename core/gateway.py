"""
gateway.py — Security Gateway Guard (a faithful port of V7's "Security Gateway Guard").

Holds gateway-protected leads out of outreach BEFORE spending any finder/verify
credits, but only the most aggressive gateways that consistently bounce cold email.
Lenient gateways (Cisco, Sophos, Trend Micro, Fortinet, Microsoft Defender) pass.

Pure + deterministic — testable offline.
"""
from __future__ import annotations

# Only the aggressive gateways V7 blocks (Option B focused list).
BLOCKED_GATEWAYS = ["mimecast", "proofpoint", "pphosted", "mxlogic", "messagelabs", "mailcontrol"]
_SAFE_BLANKS = {"", "not found", "none", "n/a", "na"}


def guard(provider: str, *, block: bool = True) -> dict:
    """Return the hold decision for a lead's security-gateway provider.
    held => keep it out of outreach and mark hold_security_gateway."""
    raw = str(provider or "").strip()
    low = raw.lower()
    blank_or_safe = low in _SAFE_BLANKS
    blocked = (not blank_or_safe) and any(g in low for g in BLOCKED_GATEWAYS)
    held = bool(block) and blocked
    return {
        "held": held,
        "blocked": blocked,
        "provider": raw,
        "status": "hold_security_gateway" if held else "",
        "reason": f"Blocked gateway: {raw}" if held else "",
    }
