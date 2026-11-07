"""
ledger.py — the "already handled" record. SQLite, two stages, keyed on the sheet's own id.

Two V1 bugs are fixed here, and both were silent.

1. THE KEY.  V1 keyed on lowercased company name. The Northwind sheet has 132 duplicate company
   names over 264 rows, so two different firms blocked each other forever. The key is now
   `row_key` — the sheet's `lead_id` — the same key n8n v8 write-back already switched to.

2. ENRICHED IS NOT PUSHED.  V1 put `email_found` in one TERMINAL set, so a lead that found
   an email but never reached Instantly was never looked at again. Harmless while there
   were no quotas; the moment a campaign caps at 50 a day it silently drops leads. There
   are now two stages, recorded separately:

       enrich  — we tried to find and verify an address. Do not spend on it twice.
       push    — it actually reached Instantly. Never send it again.

   A lead can be `enrich=email_found` and have no push row at all, which is exactly the
   state "found on Monday, quota ran out, still owed a send".

SQLite (not JSON) because two campaigns can now run at once, and two threads writing one
JSON file corrupts it.

⚠️ After fixing anything in the find-or-verify path, CLEAR THE LEDGER or the fix is
invisible — terminal outcomes are skipped forever and hide the improvement.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ENRICH, PUSH = "enrich", "push"
STAGES = (ENRICH, PUSH)

# enrichment outcomes that mean "do not spend on this lead again".
# The last four come from a Finding Recipe (core/recipe.py). They matter here: without
# them a lead that was deliberately skipped, or written marked "check by hand", would be
# picked up and paid for again on the very next run.
TERMINAL = {"email_found", "email_not_found", "no_website", "hold_security_gateway",
            "check_by_hand", "email_failed_check", "skipped_no_person", "skipped_by_rule"}
# ...of which these may be let back in (new finder, fresh key, cleared cache).
# `skipped_no_person` is retryable because the row simply had nobody to try YET — a name
# added to the sheet later makes it workable, and nothing was ever spent on it.
RETRYABLE = {"email_not_found", "skipped_no_person"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    row_key   TEXT NOT NULL,
    stage     TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT '',
    company   TEXT NOT NULL DEFAULT '',
    email     TEXT NOT NULL DEFAULT '',
    campaign  TEXT NOT NULL DEFAULT '',
    when_ts   TEXT NOT NULL DEFAULT '',
    when_day  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (row_key, stage)
);
CREATE INDEX IF NOT EXISTS ix_ledger_day ON ledger (stage, when_day);
"""

_ALIASES = ("row_key", "lead_id", "Lead ID", "lead id",
            "Reg Number", "Registration Number", "company_key", "Company Name", "company")


def norm_key(v) -> str:
    return " ".join(str(v or "").strip().lower().split())


def key_of(obj: dict, fm=None) -> str:
    """The ledger key for either a raw sheet row or a pipeline result row.

    Order: an explicit row_key -> the field map -> V1's legacy company key. The legacy
    fallback is last so an Northwind row with a real `lead_id` never degrades to a name."""
    for k in ("row_key", "lead_id"):
        if str(obj.get(k) or "").strip():
            return norm_key(obj[k])
    if fm is not None:
        v = fm.get(obj, "row_key")
        if v:
            return norm_key(v)
    for k in _ALIASES:
        if str(obj.get(k) or "").strip():
            return norm_key(obj[k])
    return ""


class Ledger:
    """Thread-safe. One connection, one lock, WAL on — two campaigns may write at once."""

    def __init__(self, path):
        p = Path(path)
        # a V1 path ending in .json becomes the matching .db, so nothing has to be renamed
        self.path = p.with_suffix(".db") if p.suffix.lower() == ".json" else p
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            try:
                self._db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass                       # a read-only volume still works, just slower
            self._db.commit()
        if p.suffix.lower() == ".json" and p.exists():
            self.migrate_json(p)

    # ── writing ──────────────────────────────────────────────────

    def record(self, row: dict, *, stage: str = ENRICH, pushed: bool | None = None,
               fm=None, campaign: str = "", test_mode: bool = False) -> str:
        """Record one outcome. `pushed=True` also writes the push row, so V1's
        `record(row, pushed=True)` keeps meaning what it used to.

        ⛔ `test_mode=True` records NOTHING. A test run invents its addresses, so writing
        them here would skip those real firms forever behind an address nobody ever
        checked. The guard lives on the ledger, not at the call sites, so a new caller
        cannot forget it."""
        if test_mode:
            return ""
        key = key_of(row, fm)
        if not key:
            return ""
        status = str(row.get("status") or "").strip()
        company = str(row.get("company") or row.get("Company Name") or "").strip()
        email = str(row.get("found_email") or row.get("email") or "").strip()
        now = datetime.now()
        stages = [stage] + ([PUSH] if pushed and stage != PUSH else [])
        with self._lock:
            for st in stages:
                self._db.execute(
                    "INSERT INTO ledger (row_key, stage, status, company, email, campaign,"
                    " when_ts, when_day) VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(row_key, stage) DO UPDATE SET"
                    "   status=excluded.status,"
                    "   company=CASE WHEN excluded.company != '' THEN excluded.company ELSE ledger.company END,"
                    "   email=CASE WHEN excluded.email != '' THEN excluded.email ELSE ledger.email END,"
                    "   campaign=CASE WHEN excluded.campaign != '' THEN excluded.campaign ELSE ledger.campaign END,"
                    "   when_ts=excluded.when_ts, when_day=excluded.when_day",
                    (key, st, status if st == ENRICH else (status or "pushed"), company, email,
                     str(campaign or ""), now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d")))
            self._db.commit()
        return key

    def record_push(self, row: dict, *, fm=None, campaign: str = "", status: str = "pushed") -> str:
        return self.record({**row, "status": status}, stage=PUSH, fm=fm, campaign=campaign)

    def save(self) -> None:
        """No-op. SQLite commits on write; kept so V1 call sites do not have to change."""

    # ── reading ──────────────────────────────────────────────────

    def entry(self, key: str, stage: str = ENRICH) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM ledger WHERE row_key=? AND stage=?",
                                 (key, stage)).fetchone()
        return dict(r) if r else None

    def is_done(self, row: dict, *, stage: str = ENRICH, retry_not_found: bool = False,
                fm=None) -> bool:
        """Should this row be skipped at this stage?

        enrich: skipped once it reached a terminal outcome (unless it is retryable and
                retry_not_found is on, and it was never actually pushed).
        push:   skipped the moment a push row exists. Nothing else blocks a push, which
                is what stops a quota-capped lead being lost.
        """
        key = key_of(row, fm)
        if not key:
            return False
        if stage == PUSH:
            return self.entry(key, PUSH) is not None
        e = self.entry(key, ENRICH)
        if not e:
            return False
        if retry_not_found and e.get("status") in RETRYABLE and self.entry(key, PUSH) is None:
            return False
        return e.get("status") in TERMINAL

    def filter_pending(self, rows: list[dict], fm=None, *, stage: str = ENRICH,
                       retry_not_found: bool = False) -> tuple[list[dict], int]:
        pending = [r for r in rows
                   if not self.is_done(r, stage=stage, retry_not_found=retry_not_found, fm=fm)]
        return pending, len(rows) - len(pending)

    def pending_push(self, *, campaign: str = "", limit: int = 0) -> list[dict]:
        """Leads that found an email but never reached Instantly — the quota leftovers.
        This is the query V1 could not answer, and why it lost leads."""
        sql = ("SELECT e.* FROM ledger e LEFT JOIN ledger p"
               " ON p.row_key = e.row_key AND p.stage = 'push'"
               " WHERE e.stage = 'enrich' AND e.status = 'email_found'"
               " AND e.email != '' AND p.row_key IS NULL")
        args: list = []
        if campaign:
            sql += " AND e.campaign = ?"
            args.append(campaign)
        sql += " ORDER BY e.when_ts"
        if limit:
            sql += " LIMIT ?"
            args.append(int(limit))
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def count_today(self, stage: str = PUSH, *, day: str = "", campaign: str = "") -> int:
        """How many leads hit this stage today. The global daily cap reads this with no
        campaign; a campaign's own per_day reads it with one."""
        d = day or datetime.now().strftime("%Y-%m-%d")
        sql = "SELECT COUNT(*) c FROM ledger WHERE stage=? AND when_day=?"
        args: list = [stage, d]
        if campaign:
            sql += " AND campaign=?"
            args.append(campaign)
        with self._lock:
            r = self._db.execute(sql, args).fetchone()
        return int(r["c"] if r else 0)

    def recent(self, limit: int = 25) -> list[dict]:
        """The last leads handled, newest first, with whether they actually reached
        Instantly. One row per lead, not one per stage."""
        sql = ("SELECT e.row_key, e.company, e.status, e.email, e.campaign, e.when_ts,"
               " CASE WHEN p.row_key IS NULL THEN 0 ELSE 1 END AS pushed"
               " FROM ledger e LEFT JOIN ledger p"
               " ON p.row_key = e.row_key AND p.stage = 'push'"
               " WHERE e.stage = 'enrich' ORDER BY e.when_ts DESC LIMIT ?")
        with self._lock:
            rows = [dict(r) for r in self._db.execute(sql, (int(limit),)).fetchall()]
        for r in rows:
            r["pushed"] = bool(r["pushed"])
            r["when"] = r.pop("when_ts")
        return rows

    def stats(self) -> dict:
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT stage, status, COUNT(*) c FROM ledger GROUP BY stage, status").fetchall()]
            total = self._db.execute(
                "SELECT COUNT(DISTINCT row_key) c FROM ledger").fetchone()["c"]
        by_status = {r["status"]: r["c"] for r in rows if r["stage"] == ENRICH}
        pushed = sum(r["c"] for r in rows if r["stage"] == PUSH)
        return {"total": int(total), "pushed": int(pushed), "by_status": by_status,
                "pending_push": len(self.pending_push())}

    # ── maintenance ──────────────────────────────────────────────

    def clear(self, *, stage: str = "") -> int:
        with self._lock:
            cur = (self._db.execute("DELETE FROM ledger WHERE stage=?", (stage,)) if stage
                   else self._db.execute("DELETE FROM ledger"))
            self._db.commit()
            return cur.rowcount

    def migrate_json(self, json_path) -> int:
        """Carry a V1 ledger.json across, once. The old file is renamed, not deleted, so a
        bad migration is recoverable."""
        p = Path(json_path)
        try:
            old = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:                                   # noqa: BLE001
            return 0
        if not isinstance(old, dict) or not old:
            return 0
        moved = 0
        for key, e in old.items():
            if not isinstance(e, dict):
                continue
            k = norm_key(key)
            if not k:
                continue
            self.record({"row_key": k, "company": e.get("company", ""),
                         "status": e.get("status", ""), "found_email": e.get("email", "")},
                        stage=ENRICH)
            if e.get("pushed"):
                self.record({"row_key": k, "company": e.get("company", ""),
                             "status": "pushed", "found_email": e.get("email", "")}, stage=PUSH)
            moved += 1
        try:
            p.rename(p.with_suffix(".json.migrated"))
        except OSError:
            pass
        return moved

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _legacy_key(firm_or_row: dict) -> str:    # kept for anything still importing it
    v = (firm_or_row.get("company_key") or firm_or_row.get("Company Name")
         or firm_or_row.get("company") or "")
    return norm_key(v)


_key = _legacy_key
