"""
auth.py — one password in front of the whole app, for when it lives on a server.

On your own PC nothing changes: with no password set, the app is open, as it always was.
Once a password is set (Settings, or `python set_password.py` on the server) every engine
request needs the session cookie. `LEADGEN_REQUIRE_LOGIN=1` closes the app even while no
password is set yet — the server start script sets it, so a fresh server is never open.

Stored in data/auth.json, NOT data/config.json: /api/config returns the config to the
browser, and the password hash must never travel there.

    {"salt": hex, "hash": hex, "iterations": n, "secret": hex, "set_at": "..."}

Session cookie = "<expiry>.<hmac(secret, expiry)>". Changing the password replaces `secret`,
which signs everyone out.

Pure except load/save, which take the path so tests can use a temp file.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime
from pathlib import Path

COOKIE = "leadgen_session"
SESSION_SECONDS = 14 * 24 * 3600
ITERATIONS = 240_000
MIN_LENGTH = 10


def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def load(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def is_set(rec: dict) -> bool:
    return bool(rec.get("hash") and rec.get("salt") and rec.get("secret"))


def check_strength(password: str) -> str:
    """'' when acceptable, else the reason."""
    if len(password or "") < MIN_LENGTH:
        return f"use at least {MIN_LENGTH} characters"
    if password.strip() != password:
        return "no spaces at the start or end"
    return ""


def make(password: str) -> dict:
    """A new record for `password`, with a new session secret (signs everyone out)."""
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _hash(password, salt, ITERATIONS).hex(),
            "iterations": ITERATIONS, "secret": secrets.token_hex(32),
            "set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def save(path, rec: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2), encoding="utf-8")


def verify(rec: dict, password: str) -> bool:
    if not is_set(rec):
        return False
    got = _hash(password or "", bytes.fromhex(rec["salt"]), int(rec.get("iterations") or ITERATIONS))
    return hmac.compare_digest(got.hex(), rec["hash"])


def issue(rec: dict, *, now: float | None = None) -> str:
    exp = int((now or time.time()) + SESSION_SECONDS)
    sig = hmac.new(bytes.fromhex(rec["secret"]), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid(rec: dict, token: str | None, *, now: float | None = None) -> bool:
    if not is_set(rec) or not token or "." not in token:
        return False
    exp, _, sig = token.partition(".")
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return False
    want = hmac.new(bytes.fromhex(rec["secret"]), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


class Throttle:
    """Slows password guessing: after `limit` misses from one address within `window`
    seconds, that address is refused until the window passes. Per address, so a stranger
    cannot lock the owner out."""

    def __init__(self, limit: int = 5, window: int = 600):
        self.limit, self.window = limit, window
        self.misses: dict[str, list[float]] = {}

    def blocked(self, who: str, now: float | None = None) -> int:
        """Seconds left to wait, or 0."""
        now = now or time.time()
        recent = [t for t in self.misses.get(who, []) if now - t < self.window]
        self.misses[who] = recent
        if len(recent) >= self.limit:
            return int(self.window - (now - recent[0])) + 1
        return 0

    def miss(self, who: str, now: float | None = None) -> None:
        self.misses.setdefault(who, []).append(now or time.time())

    def clear(self, who: str) -> None:
        self.misses.pop(who, None)
