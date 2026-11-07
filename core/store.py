"""
store.py — the app database for the full stack (data/stack.db).

Three things live here, keyed by (source, row_key):

  pipeline       the five step columns (core/lead_record.py) for sources the app may NOT
                 write to — uploaded files, local files and the demo. A Google Sheet keeps
                 its own columns; this table is the "results stay in the app" half.
  website_facts  what Website research found on a company's site. Never goes to a sheet:
                 the sheet only ever gets `website_status`.
  email_results  what Find email found and how, so a file source can be exported and the
                 Leads record pane can show the steps.

Every pipeline write goes through `lead_record.stage_update`, so the allow-list and the
allowed values are enforced here too, not only on sheets.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from . import lead_record

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline (
    source TEXT NOT NULL, row_key TEXT NOT NULL, col TEXT NOT NULL,
    value TEXT NOT NULL, updated TEXT NOT NULL,
    PRIMARY KEY (source, row_key, col));
CREATE TABLE IF NOT EXISTS website_facts (
    source TEXT NOT NULL, row_key TEXT NOT NULL, company TEXT, host TEXT,
    status TEXT, detail TEXT, facts TEXT, evidence TEXT, pages TEXT,
    researched_on TEXT, PRIMARY KEY (source, row_key));
CREATE TABLE IF NOT EXISTS email_results (
    source TEXT NOT NULL, row_key TEXT NOT NULL, company TEXT, email TEXT,
    contact TEXT, rung TEXT, method TEXT, verification TEXT, checks INTEGER,
    finder_calls INTEGER, steps TEXT, updated TEXT, PRIMARY KEY (source, row_key));
CREATE TABLE IF NOT EXISTS rulesets (
    source TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, updated TEXT,
    PRIMARY KEY (source, id));
CREATE TABLE IF NOT EXISTS icebreakers (
    source TEXT NOT NULL, row_key TEXT NOT NULL, ruleset TEXT, rung TEXT, rung_name TEXT,
    fact TEXT, line TEXT, shared_ground INTEGER, default_version INTEGER, updated TEXT,
    PRIMARY KEY (source, row_key));
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, name TEXT, subject TEXT,
    body TEXT, state TEXT, score INTEGER, result TEXT, request TEXT, approved_by TEXT,
    created TEXT);
CREATE TABLE IF NOT EXISTS template_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, kind TEXT, instructions TEXT,
    state TEXT, template_id INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS pushes (
    source TEXT NOT NULL, row_key TEXT NOT NULL, state TEXT, reason TEXT, template_id INTEGER,
    email TEXT, campaign TEXT, mode TEXT, pushed_on TEXT, PRIMARY KEY (source, row_key));
CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, row_key TEXT NOT NULL,
    sender TEXT, company TEXT, email TEXT, message TEXT, received TEXT, category TEXT,
    auto_category TEXT, action TEXT, handled INTEGER DEFAULT 0, UNIQUE (source, row_key, message));
CREATE TABLE IF NOT EXISTS seeds (
    source TEXT NOT NULL, what TEXT NOT NULL, PRIMARY KEY (source, what));
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stack_runs (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, trigger TEXT, state TEXT, step INTEGER,
    start_step INTEGER, end_step INTEGER, due TEXT, started TEXT, finished TEXT, message TEXT,
    events TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, at TEXT, step TEXT, kind TEXT,
    issue TEXT, action TEXT, result TEXT, run_id TEXT, row_key TEXT);
CREATE TABLE IF NOT EXISTS pending_writes (
    source TEXT NOT NULL, row_key TEXT NOT NULL, stage TEXT NOT NULL, vals TEXT,
    incident INTEGER, created TEXT, PRIMARY KEY (source, row_key, stage));
CREATE TABLE IF NOT EXISTS retries (
    source TEXT NOT NULL, row_key TEXT NOT NULL, step TEXT NOT NULL, after TEXT, tries INTEGER,
    PRIMARY KEY (source, row_key, step));
CREATE TABLE IF NOT EXISTS summaries (
    source TEXT NOT NULL, day TEXT NOT NULL, body TEXT, made TEXT, PRIMARY KEY (source, day));
"""

# `settings` is left out on purpose: schedules, approval rules and Live demo mode survive a
# demo reset.
TABLES = ("pipeline", "website_facts", "email_results", "rulesets", "icebreakers", "templates",
          "template_requests", "pushes", "replies", "seeds", "stack_runs", "incidents",
          "pending_writes", "retries", "summaries")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = sqlite3.connect(str(self.path), timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ── pipeline columns ─────────────────────────────────────────

    def write_status(self, stage: str, source: str, row_key: str, values: dict) -> dict:
        """Write one step's own column(s) for one row. Refuses anything the step does not own."""
        checked = lead_record.stage_update(stage, values)       # raises WriteRefused
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._conn() as c:
            for col, val in checked.items():
                c.execute("INSERT INTO pipeline VALUES (?,?,?,?,?) ON CONFLICT(source,row_key,col) "
                          "DO UPDATE SET value=excluded.value, updated=excluded.updated",
                          (source, str(row_key), col, val, now))
        return checked

    def statuses(self, source: str) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        with self._conn() as c:
            for r in c.execute("SELECT row_key, col, value FROM pipeline WHERE source=?", (source,)):
                out.setdefault(r["row_key"], {})[r["col"]] = r["value"]
        return out

    def overlay(self, rows: list[dict], source: str, key_header: str) -> list[dict]:
        """Copies of the rows with the stored step columns filled in (blank when none)."""
        st = self.statuses(source)
        out = []
        for row in rows:
            r = dict(row)
            got = st.get(str(r.get(key_header, "")), {})
            for col in lead_record.COLUMNS:
                r[col] = got.get(col, r.get(col, "") or "")
            out.append(r)
        return out

    # ── website facts ────────────────────────────────────────────

    def save_facts(self, source: str, row_key: str, rec: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO website_facts VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (source, str(row_key), rec.get("company", ""), rec.get("host", ""),
                       rec.get("website_status", ""), rec.get("detail", ""),
                       json.dumps(rec.get("facts") or {}, ensure_ascii=False),
                       json.dumps(rec.get("evidence") or [], ensure_ascii=False),
                       json.dumps(rec.get("pages") or [], ensure_ascii=False),
                       rec.get("researched_on") or date.today().isoformat()))

    def facts(self, source: str) -> dict[str, dict]:
        out = {}
        with self._conn() as c:
            for r in c.execute("SELECT * FROM website_facts WHERE source=?", (source,)):
                out[r["row_key"]] = {
                    "company": r["company"], "host": r["host"], "website_status": r["status"],
                    "detail": r["detail"], "facts": json.loads(r["facts"] or "{}"),
                    "evidence": json.loads(r["evidence"] or "[]"),
                    "pages": json.loads(r["pages"] or "[]"), "researched_on": r["researched_on"]}
        return out

    def researched_recently(self, source: str, row_key: str, days: int = 30,
                            today: date | None = None) -> bool:
        with self._conn() as c:
            r = c.execute("SELECT researched_on FROM website_facts WHERE source=? AND row_key=?",
                          (source, str(row_key))).fetchone()
        if not r or not r["researched_on"]:
            return False
        when = date.fromisoformat(r["researched_on"])
        return (today or date.today()) - when < timedelta(days=days)

    # ── find email results ───────────────────────────────────────

    def save_email_result(self, source: str, row_key: str, res: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO email_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (source, str(row_key), res.get("company", ""), res.get("email", ""),
                       res.get("contact", ""), res.get("rung", ""), res.get("method", ""),
                       res.get("verification", ""), int(res.get("checks") or 0),
                       int(res.get("finder_calls") or 0),
                       json.dumps(res.get("steps") or [], ensure_ascii=False),
                       datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def email_results(self, source: str) -> dict[str, dict]:
        out = {}
        with self._conn() as c:
            for r in c.execute("SELECT * FROM email_results WHERE source=?", (source,)):
                d = dict(r)
                d["steps"] = json.loads(d.get("steps") or "[]")
                out[r["row_key"]] = d
        return out

    # ── step 3: rule sets and ice breakers ───────────────────────

    def ruleset(self, source: str, rid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT body FROM rulesets WHERE source=? AND id=?", (source, rid)).fetchone()
        return json.loads(r["body"]) if r else None

    def save_ruleset(self, source: str, body: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO rulesets VALUES (?,?,?,?)",
                      (source, body["id"], json.dumps(body, ensure_ascii=False), _now()))

    def save_icebreaker(self, source: str, row_key: str, rec: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO icebreakers VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (source, str(row_key), rec.get("ruleset", ""), rec.get("rung", ""),
                       rec.get("rung_name", ""), rec.get("fact", ""), rec.get("line", ""),
                       int(rec.get("shared_ground") or 0), rec.get("default_version"), _now()))

    def icebreakers(self, source: str) -> dict[str, dict]:
        with self._conn() as c:
            return {r["row_key"]: dict(r) for r in
                    c.execute("SELECT * FROM icebreakers WHERE source=?", (source,))}

    # ── step 4: templates and requests ───────────────────────────

    def add_template(self, source: str, t: dict) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO templates (source,name,subject,body,state,score,result,request,"
                            "approved_by,created) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (source, t.get("name", ""), t.get("subject", ""), t.get("body", ""),
                             t.get("state", "draft"), int(t.get("score") or 0),
                             json.dumps(t.get("result") or {}, ensure_ascii=False),
                             t.get("request", ""), t.get("approved_by", ""), _now()))
            return int(cur.lastrowid)

    def update_template(self, source: str, tid: int, **fields) -> None:
        if "result" in fields:
            fields["result"] = json.dumps(fields["result"] or {}, ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE templates SET {cols} WHERE source=? AND id=?",
                      (*fields.values(), source, int(tid)))

    def templates(self, source: str) -> list[dict]:
        with self._conn() as c:
            out = [dict(r) for r in c.execute("SELECT * FROM templates WHERE source=? ORDER BY id", (source,))]
        for t in out:
            t["result"] = json.loads(t.get("result") or "{}")
        return out

    def add_request(self, source: str, kind: str, instructions: str, state: str = "queued") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO template_requests (source,kind,instructions,state,template_id,created) "
                            "VALUES (?,?,?,?,?,?)", (source, kind, instructions, state, None, _now()))
            return int(cur.lastrowid)

    def update_request(self, source: str, rid: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE template_requests SET {cols} WHERE source=? AND id=?",
                      (*fields.values(), source, int(rid)))

    def requests(self, source: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM template_requests WHERE source=? ORDER BY id DESC", (source,))]

    # ── step 5: what Sending did with each lead ──────────────────

    def save_push(self, source: str, row_key: str, rec: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO pushes VALUES (?,?,?,?,?,?,?,?,?)",
                      (source, str(row_key), rec.get("state", ""), rec.get("reason", ""),
                       rec.get("template_id"), rec.get("email", ""), rec.get("campaign", ""),
                       rec.get("mode", "test"), rec.get("pushed_on") or _now()))

    def pushes(self, source: str) -> dict[str, dict]:
        with self._conn() as c:
            return {r["row_key"]: dict(r) for r in c.execute("SELECT * FROM pushes WHERE source=?", (source,))}

    # ── step 6: replies ──────────────────────────────────────────

    def add_reply(self, source: str, rec: dict) -> int | None:
        """Store one reply; None when the same message from the same lead is already stored."""
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO replies (source,row_key,sender,company,email,message,"
                            "received,category,auto_category,action,handled) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                            (source, str(rec["row_key"]), rec.get("sender", ""), rec.get("company", ""),
                             rec.get("email", ""), rec.get("message", ""), rec.get("received", ""),
                             rec.get("category", ""), rec.get("category", ""), rec.get("action", "")))
            return int(cur.lastrowid) if cur.rowcount else None

    def update_reply(self, source: str, rid: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE replies SET {cols} WHERE source=? AND id=?", (*fields.values(), source, int(rid)))

    def replies(self, source: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM replies WHERE source=? ORDER BY received DESC, id", (source,))]

    # ── session 3: settings, chain runs, health ──────────────────

    def setting(self, key: str, default=None):
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_setting(self, key: str, value) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def add_run(self, rec: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO stack_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rec["id"], rec["source"], rec.get("trigger", ""), rec.get("state", "scheduled"),
                       int(rec.get("step") or 0), int(rec.get("start_step") or 0), int(rec.get("end_step") or 0),
                       rec.get("due", ""), rec.get("started", ""), rec.get("finished", ""),
                       rec.get("message", ""), "[]", "{}"))

    def update_run(self, run_id: str, **fields) -> None:
        for k in ("events", "result"):
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE stack_runs SET {cols} WHERE id=?", (*fields.values(), run_id))

    def add_event(self, run_id: str, ev: dict) -> None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT events FROM stack_runs WHERE id=?", (run_id,)).fetchone()
            if r is None:
                return
            evs = json.loads(r["events"] or "[]")
            evs.append(ev)
            c.execute("UPDATE stack_runs SET events=? WHERE id=?", (json.dumps(evs, ensure_ascii=False), run_id))

    @staticmethod
    def _run_row(r) -> dict:
        d = dict(r)
        d["events"] = json.loads(d.get("events") or "[]")
        d["result"] = json.loads(d.get("result") or "{}")
        return d

    def run(self, run_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM stack_runs WHERE id=?", (run_id,)).fetchone()
        return self._run_row(r) if r else None

    def runs(self, source: str, states: tuple = ()) -> list[dict]:
        with self._conn() as c:
            rows = [self._run_row(r) for r in c.execute(
                "SELECT * FROM stack_runs WHERE source=? ORDER BY rowid DESC", (source,))]
        return [r for r in rows if not states or r["state"] in states]

    def add_incident(self, source: str, rec: dict) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO incidents (source,at,step,kind,issue,action,result,run_id,row_key) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (source, rec.get("at") or _now(), rec.get("step", ""), rec.get("kind", ""),
                             rec.get("issue", ""), rec.get("action", ""), rec.get("result", ""),
                             rec.get("run_id", ""), str(rec.get("row_key", ""))))
            return int(cur.lastrowid)

    def update_incident(self, source: str, iid: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE incidents SET {cols} WHERE source=? AND id=?", (*fields.values(), source, int(iid)))

    def incidents(self, source: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM incidents WHERE source=? ORDER BY id", (source,))]

    def add_pending(self, source: str, row_key: str, stage: str, values: dict, incident: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO pending_writes VALUES (?,?,?,?,?,?)",
                      (source, str(row_key), stage, json.dumps(values, ensure_ascii=False), int(incident), _now()))

    def pending(self, source: str) -> list[dict]:
        with self._conn() as c:
            out = [dict(r) for r in c.execute("SELECT * FROM pending_writes WHERE source=?", (source,))]
        for p in out:
            p["vals"] = json.loads(p["vals"] or "{}")
        return out

    def drop_pending(self, source: str, row_key: str, stage: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM pending_writes WHERE source=? AND row_key=? AND stage=?", (source, str(row_key), stage))

    def set_retry(self, source: str, row_key: str, step: str, after: str, tries: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO retries VALUES (?,?,?,?,?)", (source, str(row_key), step, after, int(tries)))

    def retries(self, source: str, step: str) -> dict[str, dict]:
        with self._conn() as c:
            return {r["row_key"]: dict(r) for r in
                    c.execute("SELECT * FROM retries WHERE source=? AND step=?", (source, step))}

    def forget_research(self, source: str, row_key: str) -> None:
        """Let Website research look at one company again (a queued retry has come due)."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM website_facts WHERE source=? AND row_key=?", (source, str(row_key)))

    def save_summary(self, source: str, day: str, body: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?)",
                      (source, day, json.dumps(body, ensure_ascii=False), _now()))

    def latest_summary(self, source: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM summaries WHERE source=? ORDER BY day DESC LIMIT 1", (source,)).fetchone()
        return {**json.loads(r["body"] or "{}"), "made": r["made"]} if r else None

    # ── housekeeping ─────────────────────────────────────────────

    def claim_seed(self, source: str, what: str) -> bool:
        """True for exactly one caller per (source, what) until the next reset. Two screen
        requests arriving together (found 2026-11-06: the demo templates were seeded twice,
        so four "live" templates showed 25% each) cannot both seed."""
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO seeds VALUES (?,?)", (source, what))
            return bool(cur.rowcount)

    def reset(self, source: str) -> None:
        """Forget everything about one source (the demo's "start again")."""
        with self._lock, self._conn() as c:
            for t in TABLES:
                c.execute(f"DELETE FROM {t} WHERE source=?", (source,))
