"""
server.py - Lead Gen Automation Engine (Accountancy Outreach V7), Phase 1.

Local FastAPI app over the tested core engine. Phase-1 scope:
    Dashboard · Leads · Settings · Live run · Results · Log · History

Live run streams every pipeline event (per lead, per stage). Events are written to a
per-run append-only NDJSON file (so a 50k-lead run never lives in one JSON blob); the
live feed keeps a rolling in-memory window; the Log tab reads from disk with
server-side filter + limit. Credits are tracked per tool (MillionVerifier per check;
Anymailfinder / Icypeas per email found - those arrive in Phase 2).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse, Response

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import organize as organize_mod  # noqa: E402
from core import verify as verify_mod  # noqa: E402
from core import cost as cost_mod  # noqa: E402
from core import pipeline as pipeline_mod  # noqa: E402
from core import finders as finders_mod  # noqa: E402
from core import icebreaker as icebreaker_mod  # noqa: E402
from core import instantly as instantly_mod  # noqa: E402
from core import sheets as sheets_mod  # noqa: E402
from core import ledger as ledger_mod  # noqa: E402
from core import net as net_mod  # noqa: E402
from core import fieldmap as fieldmap_mod  # noqa: E402
from core import campaigns as campaigns_mod  # noqa: E402
from core import runner as runner_mod  # noqa: E402
from core import rules as rules_mod  # noqa: E402
from core import imports as imports_mod  # noqa: E402
from core import schedules as schedules_mod  # noqa: E402
from core import auth as auth_mod  # noqa: E402
from core import connections as conn_mod  # noqa: E402
from core import recipe as recipe_mod  # noqa: E402
from core import lead_record as lead_record_mod  # noqa: E402

WEBAPP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
RECIPES_DIR = CONFIG_DIR / "recipes"        # one Finding Recipe per file, shared by lanes
DATA = ROOT / "data"
RUNS_DIR = DATA / "runs"
UPLOADS_DIR = DATA / "uploads"
IMPORTS_DIR = DATA / "imports"          # CSVs registered as `import:<slug>` tabs (V4 F)
LEADS_FILE = DATA / "leads.json"
HISTORY_FILE = DATA / "history.json"
CONFIG_FILE = DATA / "config.json"
LEDGER_FILE = DATA / "ledger.json"
DEFAULT_CONFIG_FILE = ROOT / "config.json"
for d in (DATA, RUNS_DIR, UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

KEEP_RUNS = 300        # retention: prune run files beyond this many
FEED_WINDOW = 1000     # rolling in-memory events kept for the live feed
LOG_SCAN_CAP = 6000    # max events the Log tab scans (recent-first)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


DEFAULT_CONFIG = {
    "use_endole": True, "verify_endole_with_mf": True, "use_patterns": True,
    "use_icypeas": True, "use_anymailfinder": False,
    "verify_icypeas_with_mf": False, "verify_anymailfinder_with_mf": False,
    "use_icebreaker": True, "use_openai_echo": False,
    "accept_catchall": False, "block_security_gateways": False,
    "pattern_mode": "lean", "max_firms": 50,
    "mv_per_verification_usd": 0.00178,
    "anymailfinder_usd_per_credit": 0.0, "icypeas_usd_per_credit": 0.0,
    "apollo_credit_usd": 0.0236,
    "millionverifier_api_key": "", "icypeas_api_key": "",
    "anymailfinder_api_key": "", "openai_api_key": "",
    "owned_companies": [], "owned_domains": [],
    # ── Phase 3 ──
    "instantly_api_key": "", "instantly_campaign_id": "",
    "push_delay_seconds": 3,                 # V7 waits 3s between pushes
    "sheet_url": "", "sheet_tab": "Combined",
    "sheet_service_account_file": "", "sheet_writeback": False,
    # {tab name: local .csv path} - read a snapshot instead of the live sheet, so a
    # campaign can be tested with no credentials. Every screen says when this is on.
    "local_tabs": {},
    "strict_status": True,          # blank Status = process, anything written = done
    "api_tries": 3,                 # V7 parity: retry each API call 3x…
    "api_retry_wait": 5.0,          # …5s apart, backing off on 429 / 5xx / timeouts
    "verify_delay_ms": 0,           # optional pacing between verifications (0 = full speed)
    "icypeas_throttle_seconds": 2,  # V7's "Throttle Before Icypeas" node
    # Icypeas answers asynchronously. These two are the CEILING on collecting one answer and
    # how often it is asked for — not a fixed pause. The old code slept the whole ceiling on
    # every ask, which measured as 81% of a run's wall clock (~12s an ask) on 2026-10-08.
    "icypeas_wait_seconds": 15,     # give up on one answer after this long
    "icypeas_poll_seconds": 1.5,    # first gap before asking "is it ready?", then widening
    "use_ledger": True,             # skip leads already handled in a previous run
    "retry_not_found": False,       # let email_not_found leads back in on later runs
    "icebreaker_templates": {},     # edited copy from the Icebreaker tab (blank = defaults)
    # campaign lanes send Icebreaker Studio's line only; a lead whose sheet row has none yet
    # is held back from the push instead of going out unpersonalised
    "hold_without_icebreaker": True,
    # an address taken as-is from the sheet is never checked (his rule). Decided 2026-10-15:
    # those may be sent anyway. Switch off to hold them at the send gate again.
    "send_unchecked_sheet_emails": True,
}
_BOOL_KEYS = {"use_endole", "verify_endole_with_mf", "use_patterns", "use_icypeas",
              "use_anymailfinder", "verify_icypeas_with_mf", "verify_anymailfinder_with_mf",
              "use_icebreaker", "use_openai_echo", "accept_catchall", "block_security_gateways",
              "sheet_writeback", "strict_status", "use_ledger", "retry_not_found",
              "hold_without_icebreaker", "send_unchecked_sheet_emails"}
_KEY_FIELDS = ("millionverifier_api_key", "icypeas_api_key", "anymailfinder_api_key",
               "openai_api_key", "instantly_api_key")
TOOLS = [
    ("millionverifier", "MillionVerifier", "mv_per_verification_usd", "1 credit / check (found or not)"),
    ("anymailfinder", "Anymailfinder", "anymailfinder_usd_per_credit", "1 credit / email found"),
    ("icypeas", "Icypeas", "icypeas_usd_per_credit", "1 credit / email found"),
]


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(DEFAULT_CONFIG_FILE, {}))
    cfg.update(_read_json(CONFIG_FILE, {}))
    return cfg


def save_config(patch: dict) -> dict:
    cfg = load_config()
    for k, v in patch.items():
        if k in DEFAULT_CONFIG:
            cfg[k] = v
    _write_json(CONFIG_FILE, cfg)
    return cfg


def _mv_key(cfg: dict) -> str:
    import os
    return (cfg.get("millionverifier_api_key") or os.environ.get("MILLIONVERIFIER_API_KEY", "")).strip()


# ───────────────────────── leads: import + organize (+ V7 endole/gateway) ─────────────────────────

def _rows_from_csv_bytes(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", "replace")
    sample = text[:4096]
    delim = ","
    if sample.count(";") > sample.count(",") and sample.count(";") > sample.count("\t"):
        delim = ";"
    elif sample.count("\t") > sample.count(","):
        delim = "\t"
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    return [{(k or "").strip(): (v or "") for k, v in row.items()} for row in reader]


def _first(row: dict, *keys):
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return ""


def _attach_v7_fields(rows: list[dict], firms: list[dict]) -> None:
    info: dict[str, dict] = {}
    for row in rows:
        company = _first(row, "Company Name", "Organization", "Company", "lead_company")
        reg = _first(row, "Reg Number", "Registration Number")
        key = organize_mod._norm_company(reg or company)
        if not key or key in info:
            continue
        info[key] = {
            "endole": _first(row, "Original Endole email", "Email").lower(),
            "gateway": _first(row, "Email Security Gateway Provider", "Security Gateway Provider", "Security Gateway"),
        }
    for f in firms:
        meta = info.get(organize_mod._norm_company(f.get("company_key", "")), {})
        # organize() now fills these from the field map, so only overwrite when this
        # lookup actually found something — otherwise a blank here would erase it
        endole = meta.get("endole", "") or f.get("lead_endole_email", "")
        f["lead_endole_email"] = endole
        f["endole_generic"] = organize_mod.is_generic_email(endole) if endole else False
        f["email_security_gateway_provider"] = (meta.get("gateway", "")
                                                or f.get("email_security_gateway_provider", ""))


def firm_status_label(firm: dict) -> str:
    t = (firm.get("primary_title") or "").strip()
    return t.title() if t else "Director"


def _leads_view(payload: dict) -> dict:
    firms = payload.get("firms", [])
    return {
        "count": payload.get("count", 0), "rows_in": payload.get("rows_in", 0),
        "files": payload.get("files", []), "skipped": payload.get("skipped", {}),
        "ts": payload.get("ts"),
        "preview": [{
            "company": f.get("Company Name", ""), "domain": f.get("lead_domain", ""),
            "director": f.get("lead_director", "") or f.get("Oldest Director Name", ""),
            "status_label": firm_status_label(f),
            "gateway": f.get("email_security_gateway_provider", "") or "none",
            "endole": f.get("lead_endole_email", ""),
            "no_website": f.get("is_no_website_path", False),
        } for f in firms],
    }


# ───────────────────────── run jobs + streaming events ─────────────────────────

JOBS: dict[str, dict] = {}


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _run_file(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _events_file(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.events.ndjson"


def _append_event(run_id: str, ev: dict) -> None:
    with open(_events_file(run_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _read_events(run_id: str, since: int = 0, limit: int | None = None) -> list[dict]:
    fp = _events_file(run_id)
    if not fp.exists():
        return []
    out = []
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("seq", 0) >= since:
                out.append(ev)
    return out[-limit:] if limit else out


def _credit_breakdown(cfg: dict, credits: dict) -> dict:
    rows, total_usd, total_credits = [], 0.0, 0
    for key, label, rate_key, rule in TOOLS:
        n = int(credits.get(key, 0))
        usd = round(n * float(cfg.get(rate_key) or 0.0), 4)
        total_usd += usd
        total_credits += n
        rows.append({"tool": label, "credits": n, "usd": usd, "rule": rule})
    return {"rows": rows, "total_credits": total_credits, "total_usd": round(total_usd, 4)}


def _run_record(job: dict) -> dict:
    return {
        "run_id": job["run_id"], "status": job["status"], "test_mode": job["test_mode"],
        "stage": job["stage"], "total": job["total"], "processed": job["processed"],
        "counters": job["counters"], "started": job["started"], "finished": job.get("finished"),
        "event_count": job["_seq"], "results": job["results"], "cfg_rates": job["rates"],
        "skipped_done": job.get("skipped_done", 0),
        "kind": job.get("kind", "run"), "source_run": job.get("source_run"),
        # which lane this run belonged to. It must survive to disk: the push reads it back
        # to find the campaign's target id, labels and options.
        "campaign": job.get("campaign", ""), "campaign_name": job.get("campaign_name", ""),
        "selection": job.get("selection"),
        "held_not_send_ready": job.get("held_not_send_ready", 0),
        "backlog_runs": job.get("backlog_runs", 0),    # a campaign-wide send: runs it drew on
    }


def _snapshot(job: dict, since: int = 0) -> dict:
    rec = _run_record(job)
    rec["events"] = [e for e in job["events"] if e["seq"] >= since]
    rec["credits"] = _credit_breakdown_from_job(job)
    return rec


def _credit_breakdown_from_job(job: dict) -> dict:
    # a test run's checks are simulated (no API call), so they cost nothing: pricing its
    # counters showed made-up spend on runs that never left the machine (found 2026-10-04)
    if job.get("test_mode"):
        return _credit_breakdown(job["rates"], {})
    return _credit_breakdown(job["rates"], job["counters"]["credits"])


def _persist(job: dict) -> None:
    _write_json(_run_file(job["run_id"]), _run_record(job))


def _prune_runs() -> None:
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_RUNS:]:
        rid = old.stem
        try:
            old.unlink()
            _events_file(rid).unlink(missing_ok=True)
        except Exception:
            pass


TALLY = {"email_found": "found", "hold_security_gateway": "held",
         "no_website": "no_website", "email_not_found": "not_found",
         # a Finding Recipe's outcomes. "check by hand" and "failed the check" DID find an
         # address, so they are counted apart from `found` — nothing in them is sendable.
         "check_by_hand": "check_by_hand", "email_failed_check": "failed_check",
         "skipped_no_person": "skipped", "skipped_by_rule": "skipped"}

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _openai_echo(text: str, api_key: str, model: str = "gpt-4o-mini") -> str:
    """V7's OpenAI node only echoes the icebreaker back verbatim. Off by default
    (use_openai_echo) since the text is already built deterministically in code."""
    import urllib.request
    payload = json.dumps({
        "model": model, "temperature": 0,
        "messages": [
            {"role": "system", "content": "Return the user's text back exactly as given. No preamble, no changes."},
            {"role": "user", "content": text},
        ],
    }).encode()
    req = urllib.request.Request(OPENAI_URL, data=payload, method="POST",
                                 headers=net_mod.headers({"Content-Type": "application/json",
                                                          "Authorization": "Bearer " + api_key}))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:  # noqa: BLE001 - echo is cosmetic; fall back to the built text
        return ""


def _worker(run_id: str, firms: list[dict], cfg: dict, *, campaign=None, fm=None,
            recipe=None) -> None:
    job = JOBS[run_id]
    key = _mv_key(cfg)
    test_mode = job["test_mode"]
    # the lane's own sheet, when it has one, before anything reads or writes a document
    cfg = cfg_for_campaign(cfg, campaign)
    # a recipe changes WHO is tried and in what order; without one the engine keeps its
    # own fixed order, which is what every campaign built before recipes does
    if recipe is not None:
        cfg = {**cfg, "recipe": recipe}
    accept_catchall = bool(cfg.get("accept_catchall", False))
    credits = job["counters"]["credits"]

    tries = max(1, int(cfg.get("api_tries", 3) or 1))
    retry_wait = float(cfg.get("api_retry_wait", 5.0) or 0)
    verify_delay = max(0, int(cfg.get("verify_delay_ms", 0) or 0)) / 1000.0

    def _retry_note(what):
        def note(attempt, attempts, exc, pause):
            job["counters"]["retries"] = job["counters"].get("retries", 0) + 1
            emit("", what, "retry", f"attempt {attempt}/{attempts} failed ({exc}) - retrying in {pause:.0f}s")
        return note

    def verify_email(email):
        v = verify_mod.verify_email(email, key, accept_catchall=accept_catchall, test_mode=test_mode,
                                    tries=tries, retry_wait=retry_wait, on_retry=_retry_note("verify"))
        credits["millionverifier"] += 1          # MillionVerifier: 1 credit per check
        job["counters"]["verifs"] += 1
        if v.get("tier") == "error":
            job["counters"]["errors"] += 1
        if verify_delay and not test_mode:
            time.sleep(verify_delay)
        return {"accepted": v["accepted"], "verification": v["verification"], "tier": v["tier"]}

    def emit(company, stage, status, detail, email=""):
        ev = {"seq": job["_seq"], "ts": _now(), "company": company, "stage": stage,
              "status": status, "detail": detail, "email": email}
        job["_seq"] += 1
        job["events"].append(ev)
        if len(job["events"]) > FEED_WINDOW + 200:
            job["events"] = job["events"][-FEED_WINDOW:]
        job["stage"] = stage
        _append_event(run_id, ev)

    # Icypeas / Anymailfinder: 1 credit ONLY when they return an email (no charge on a miss)
    def find_icypeas(firm):
        r = finders_mod.find_icypeas(firm, cfg.get("icypeas_api_key", ""), test_mode=test_mode,
                                     throttle=float(cfg.get("icypeas_throttle_seconds", 2) or 0),
                                     wait=float(cfg.get("icypeas_wait_seconds", 15) or 0),
                                     poll_every=float(cfg.get("icypeas_poll_seconds", 1.5) or 1.5),
                                     tries=tries, retry_wait=retry_wait, on_retry=_retry_note("icypeas"))
        if r.get("email"):
            credits["icypeas"] += 1
        elif r.get("error"):
            job["counters"]["errors"] += 1
        return r

    def find_anymail(firm):
        r = finders_mod.find_anymailfinder(firm, cfg.get("anymailfinder_api_key", ""), test_mode=test_mode,
                                           tries=tries, retry_wait=retry_wait, on_retry=_retry_note("anymail"))
        if r.get("email"):
            credits["anymailfinder"] += 1
        elif r.get("error"):
            job["counters"]["errors"] += 1
        return r

    def make_icebreaker(firm, email):
        if campaign is not None:
            # a lane sends Icebreaker Studio's line from the sheet, never one of ours
            line = runner_mod.sheet_icebreaker(firm, fm)
            if not line:
                emit(firm.get("Company Name", ""), "icebreaker", "skip",
                     "no Icebreaker Studio line on the sheet yet")
            return {"text": line, "style": "studio" if line else ""}
        ib = icebreaker_mod.build(firm, email, cfg.get("icebreaker_templates") or None)
        if cfg.get("use_openai_echo") and not test_mode and cfg.get("openai_api_key"):
            echoed = _openai_echo(ib["text"], cfg.get("openai_api_key", ""))
            if echoed:
                ib = {**ib, "text": echoed}
        return ib

    # V7 logged no_website / email_not_found straight back to the sheet - do the same,
    # live, so those leads are never re-verified on a later run.
    # ⛔ A TEST RUN TOUCHES NO PRODUCTION STATE. Same rule as the ledger: its addresses
    # and verdicts are invented, so it must never stamp a status onto the real sheet.
    # (The push worker already skips its writer in test mode; this is the run's half.)
    write_row = None
    if test_mode:
        emit("", "sheet", "skip", "test mode - the sheet is never written")
    elif campaign is not None and not tab_source(cfg, campaign.tab)["live"]:
        emit("", "sheet", "skip", f"'{campaign.tab}' is a file, not the live sheet - nothing is written back")
    elif campaign is not None and not _lane_writes_back(campaign):
        emit("", "sheet", "skip", "this campaign's 'Update my Google Sheet' is off - nothing is written back")
    else:
        write_row = _open_sheet_writer(cfg, emit, tab=(campaign.tab if campaign else ""),
                                       fm=fm, recipe=recipe, stage="find_email")
    seen_person, remember_person, flush_people = _person_memory(recipe, test_mode)
    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
    camp_id = campaign.id if campaign else ""
    key_col = (fm.header("row_key") if fm is not None else "") or "Company Name"
    # only translate column names when the map actually knows the sheet's key column,
    # otherwise the writer is still matching rows on Company Name (V1 behaviour)
    use_map = fm is not None and bool(fm.header("row_key"))

    for firm in firms:
        if job.get("cancel"):
            break
        row = pipeline_mod.process_firm(firm, cfg, verify_email, emit,
                                        find_icypeas=find_icypeas, find_anymail=find_anymail,
                                        make_icebreaker=make_icebreaker, fm=fm,
                                        seen_person=seen_person, remember_person=remember_person)
        # the pipeline result knows nothing about the sheet it came from — carry the
        # identity and campaign across so the ledger, the labels and the write-back all
        # key on the SAME row
        for k in ("row_key", "lead_id", "campaign", "campaign_type", "seniority_label", "_raw"):
            if firm.get(k) not in (None, ""):
                row.setdefault(k, firm[k])
        job["results"].append(row)
        job["processed"] += 1
        bucket = TALLY.get(row["status"])
        if bucket:
            job["counters"][bucket] += 1
        # a test run marks nothing as handled — the ledger enforces that itself
        if led:
            led.record(row, fm=fm, campaign=camp_id, test_mode=test_mode)
        # A RECIPE writes every outcome straight away, into its own four columns — he asked
        # to see a row's result the moment it happens, not at push time. Without a recipe,
        # found leads still keep a blank sheet status until the push writes
        # pushed_to_instantly_*, exactly as before.
        if write_row and recipe is not None:
            try:
                up = sheets_mod.build_recipe_writeback_row(row, recipe, key_header=key_col)
                w = write_row(up) if up else {"ok": False, "reason": "nothing to write"}
                if w.get("ok"):
                    job["counters"]["written_back"] += 1
                    emit(row.get("company", ""), "sheet", "success",
                         f"{recipe.write_targets()['status_to']} → "
                         f"{lead_record_mod.email_status_for(row)} (row {w['row']})")
                elif up:
                    emit(row.get("company", ""), "sheet", "fail", f"write-back: {w.get('reason')}")
            except Exception as e:  # noqa: BLE001 - a sheet error must not kill the run
                emit(row.get("company", ""), "sheet", "fail", f"write-back error: {e}")
        elif write_row and row["status"] in ("no_website", "email_not_found", "hold_security_gateway"):
            try:
                up = sheets_mod.build_writeback_row(row, row["status"], write_icebreaker=campaign is None,
                                                    stage="find_email")
                w = write_row(sheets_mod.to_sheet_row(up, fm) if use_map else up)
                if w.get("ok"):
                    job["counters"]["written_back"] += 1
                    emit(row.get("company", ""), "sheet", "success",
                         f"email_status → {up.get('email_status', '')} (row {w['row']})")
                else:
                    emit(row.get("company", ""), "sheet", "fail", f"write-back: {w.get('reason')}")
            except Exception as e:  # noqa: BLE001 - a sheet error must not kill the run
                emit(row.get("company", ""), "sheet", "fail", f"write-back error: {e}")
        _persist(job)

    flush_people()          # remember who was searched, so another tab does not pay again
    job["status"] = "cancelled" if job.get("cancel") else "finished"
    job["stage"] = "done"
    job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _persist(job)
    _append_history(job)
    _prune_runs()


def _append_history(job: dict) -> None:
    c = job["counters"]
    cb = _credit_breakdown_from_job(job)
    hist = _read_json(HISTORY_FILE, [])
    hist.insert(0, {
        "run_id": job["run_id"], "when": job["started"], "status": job["status"],
        # which lane, so the campaign list can show each lane's last run
        "kind": job.get("kind", "run"), "campaign": job.get("campaign", ""),
        "campaign_name": job.get("campaign_name", ""), "source_run": job.get("source_run"),
        "test_mode": job["test_mode"], "leads": job["total"], "found": c["found"],
        "held": c["held"], "not_found": c["not_found"], "no_website": c["no_website"],
        "pushed": c.get("pushed", 0), "push_failed": c.get("push_failed", 0),
        "credits": cb["total_credits"], "spent_usd": cb["total_usd"],
    })
    _write_json(HISTORY_FILE, hist[:KEEP_RUNS])


def start_run(test_mode: bool) -> dict:
    cfg = load_config()
    firms = _read_json(LEADS_FILE, {}).get("firms", [])
    if not firms:
        return {"error": "No leads imported yet. Add CSV(s) on the Leads tab first."}
    skipped_done = 0
    if cfg.get("use_ledger", True):
        led = ledger_mod.Ledger(LEDGER_FILE)
        firms, skipped_done = led.filter_pending(
            firms, retry_not_found=bool(cfg.get("retry_not_found", False)))
        if not firms:
            return {"error": f"All {skipped_done} leads were handled in earlier runs. "
                             "Import more, or clear the ledger in Settings."}
    firms = firms[: int(cfg.get("max_firms", 50) or 50)]
    run_id = uuid.uuid4().hex[:12]
    job = {
        "run_id": run_id, "status": "running", "test_mode": bool(test_mode), "stage": "organize",
        "total": len(firms), "processed": 0, "results": [], "events": [], "_seq": 0,
        "counters": _new_counters(),
        "rates": {"mv_per_verification_usd": cfg.get("mv_per_verification_usd", 0.0),
                  "anymailfinder_usd_per_credit": cfg.get("anymailfinder_usd_per_credit", 0.0),
                  "icypeas_usd_per_credit": cfg.get("icypeas_usd_per_credit", 0.0)},
        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cancel": False,
        "skipped_done": skipped_done,
    }
    JOBS[run_id] = job
    _persist(job)
    threading.Thread(target=_worker, args=(run_id, firms, cfg), daemon=True).start()
    return _snapshot(job)


def _lane_writes_back(camp) -> bool:
    """A campaign's own "Update my Google Sheet" switch (`writeback.enabled`, on unless set to
    false). Until 2026-10-05 the editor saved it but nothing read it: only the global
    `sheet_writeback` counted, so switching it off for one campaign changed nothing. Both must
    now be on for a write."""
    return (camp.writeback or {}).get("enabled", True) is not False


def _open_sheet_writer(cfg: dict, emit, *, tab: str = "", fm=None, recipe=None,
                       stage: str = "sending") -> object | None:
    """One live row-writer for the configured sheet, or None (with a reason emitted).

    With a field map the writer matches rows on the sheet's OWN key column (lead_id) and
    is allowed to write only the headers that map resolves — never a guessed name, whose
    write Google Sheets would discard in silence.

    ⛔ With a RECIPE the allow-list is that recipe's four columns and nothing else. This is
    where his sheet is protected: `Contact Name` and `Email Source` are not on the list, so
    a write to them is refused by the writer itself, not merely avoided by the caller."""
    if not cfg.get("sheet_writeback"):
        return None
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
    if not (sa and parsed["doc_id"]):
        emit("", "sheet", "skip", "write-back needs a service-account file + sheet URL")
        return None
    key_col, allowed = "Company Name", None
    if fm is not None and fm.header("row_key"):
        key_col = fm.header("row_key")
        allowed = sheets_mod.writeback_headers(fm)
    if recipe is not None:
        allowed = recipe.write_columns()
    if stage == "find_email":
        # the shared lead record's allow-list (core/lead_record.py): never his `Status`,
        # never another step's column — refused by the writer itself
        bad = lead_record_mod.forbidden_headers("find_email", fm)
        allowed = [c for c in (allowed if allowed is not None else sheets_mod.WRITEBACK_COLUMNS)
                   if c not in bad]
    if recipe is not None:
        emit("", "sheet", "info",
             "this run may write only: " + ", ".join(allowed))
    try:
        w = sheets_mod.SheetsClient(sa).open_writer(
            parsed["doc_id"], tab or cfg.get("sheet_tab") or "Combined",
            key_column=key_col, allowed=allowed)
        emit("", "sheet", "info", f"live write-back ready (key: {key_col})")
        return w
    except Exception as e:  # noqa: BLE001
        emit("", "sheet", "fail", f"write-back unavailable: {e}")
        return None


PERSON_CACHE_FILE = DATA / "person_cache.json"


def _person_memory(recipe, test_mode: bool):
    """(seen, remember, flush) for a recipe's "search the same person once".

    32 of his firms sit on two CH tabs, so without this the second tab pays to find the
    same person again. The key is firm + person (core/recipe.person_cache_key).

    ⛔ A FREE TEST NEVER TOUCHES THE FILE. Its addresses are invented, so remembering them
    would stop the real run from ever searching that person. It still de-duplicates inside
    the one test run, so the test's cost estimate stays honest."""
    if recipe is None or not recipe.search_same_person_once:
        return None, None, (lambda: None)
    known: set[str] = set() if test_mode else set(_read_json(PERSON_CACHE_FILE, {}).get("people") or [])
    added: set[str] = set()

    def remember(k: str) -> None:
        if k and k not in known:
            known.add(k)
            added.add(k)

    def flush() -> None:
        if test_mode or not added:
            return
        _write_json(PERSON_CACHE_FILE, {"people": sorted(known), "updated": _now()})

    return known.__contains__, remember, flush


def _new_counters() -> dict:
    return {"found": 0, "held": 0, "no_website": 0, "not_found": 0, "verifs": 0, "errors": 0,
            "retries": 0, "pushed": 0, "push_failed": 0, "push_skipped": 0, "written_back": 0,
            # recipe outcomes (0 on every run that does not use one)
            "check_by_hand": 0, "failed_check": 0, "skipped": 0,
            "credits": {"millionverifier": 0, "anymailfinder": 0, "icypeas": 0}}


def wait_for_job(run_id: str, timeout: float = 3600.0) -> dict | None:
    """Block until a job finishes (used by the headless scheduled runner)."""
    import time
    t0 = time.time()
    while run_id in JOBS and JOBS[run_id]["status"] == "running" and time.time() - t0 < timeout:
        time.sleep(0.25)
    return get_run(run_id)


# ── Google Sheets source + write-back ───────────────────────────────

def load_leads_from_sheet() -> dict:
    """Pull leads from the configured Sheet (service account if set, else the
    no-credentials CSV export) and organize them exactly like a CSV import."""
    cfg = load_config()
    parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
    doc_id = parsed["doc_id"]
    if not doc_id:
        raise ValueError("No Google Sheet URL set in Settings.")
    tab = cfg.get("sheet_tab") or "Combined"
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if sa:
        rows = sheets_mod.SheetsClient(sa).read(doc_id, tab)
        label = f"sheet:{tab} (service account)"
    else:
        rows = sheets_mod.read_via_csv_export(doc_id, parsed["gid"])
        label = f"sheet:{tab} (link export)"
    result = organize_mod.organize(rows, owned_companies=cfg.get("owned_companies"),
                                   owned_domains=cfg.get("owned_domains"),
                                   strict_status=bool(cfg.get("strict_status", True)))
    _attach_v7_fields(rows, result["firms"])
    payload = {"firms": result["firms"], "skipped": result["skipped"], "count": result["count"],
               "files": [label], "rows_in": len(rows),
               "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(LEADS_FILE, payload)
    return _leads_view(payload)


# ── campaigns: many lanes, each off its own sheet ────────────────────

def cfg_for_campaign(cfg: dict, camp=None) -> dict:
    """The settings one lane runs with.

    Every sheet read and every write-back in here resolves its document from
    `cfg["sheet_url"]`, so for a long time the engine could see exactly ONE spreadsheet
    and a campaign could only choose a tab inside it. A campaign may now carry its own
    `sheet_url`; this returns a copy of the settings with that document swapped in, and
    the settings themselves when it does not (so the nine Practices lanes are untouched).

    Returning a copy matters: `_read_tab_for_display` keys its cache on the sheet URL, so
    two lanes on two different documents cannot serve each other's rows out of it."""
    url = str(getattr(camp, "sheet_url", "") or "").strip()
    if not url:
        return cfg
    return {**cfg, "sheet_url": url}


def tab_source(cfg: dict, tab: str) -> dict:
    """Where a tab's rows come from, so the UI can say so out loud.

    A local CSV always wins when one is configured. That is deliberate — it lets a
    campaign be tested with no credentials at all — but it reads a SNAPSHOT, not the live
    sheet, so it must never be silently in effect.

    An uploaded CSV (`import:<slug>`) has no sheet at all: it is never written back."""
    if imports_mod.is_import_tab(tab):
        p = imports_mod.path_for(IMPORTS_DIR, tab)
        return {"kind": "import", "path": str(p or ""), "live": False}
    local = str((cfg.get("local_tabs") or {}).get(tab) or "").strip()
    if local:
        return {"kind": "local_csv", "path": local, "live": False}
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if sa:
        return {"kind": "service_account", "path": "", "live": True}
    return {"kind": "link_export", "path": "", "live": True}


def _read_tab(cfg: dict, tab: str) -> list[dict]:
    """Raw rows from ONE tab. A service account can address a tab by name; the
    no-credentials CSV export only reaches the tab the URL's gid points at. A local CSV
    configured in `local_tabs` overrides both, for offline testing."""
    if imports_mod.is_import_tab(tab):
        p = imports_mod.path_for(IMPORTS_DIR, tab)
        if p is None or not p.exists():
            raise ValueError(f"'{tab}' is not an uploaded file any more — upload it again on Import")
        return _rows_from_csv_bytes(p.read_bytes())
    local =str((cfg.get("local_tabs") or {}).get(tab) or "").strip()
    if local:
        p = Path(local)
        if not p.exists():
            raise ValueError(f"local_tabs points '{tab}' at {p}, which does not exist")
        return _rows_from_csv_bytes(p.read_bytes())
    parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
    if not parsed["doc_id"]:
        raise ValueError("No Google Sheet URL set in Settings.")
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if sa:
        return sheets_mod.SheetsClient(sa).read(parsed["doc_id"], tab)
    return sheets_mod.read_via_csv_export(parsed["doc_id"], parsed["gid"])


_TAB_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_TAB_LOCKS: dict[tuple, threading.Lock] = {}
_TAB_LOCKS_GUARD = threading.Lock()
TAB_CACHE_SECONDS = 60


def _read_tab_for_display(cfg: dict, tab: str) -> list[dict]:
    """`_read_tab` for screens that only SHOW counts (previews, the checklist, column matching).

    The campaign page asks for counts, the checklist and the column list at once, and each one
    read all 21,714 rows of the sheet from Google: ~15 s before anything appeared (measured
    2026-10-05). They now share ONE read, kept for a minute; requests that arrive during that
    read wait for it instead of starting their own. Runs and sends never use this — they always
    read the sheet fresh."""
    src = tab_source(cfg, tab)
    key = (tab, src["kind"], src.get("path", ""), cfg.get("sheet_url", ""))
    with _TAB_LOCKS_GUARD:
        lock = _TAB_LOCKS.setdefault(key, threading.Lock())
    with lock:
        hit = _TAB_CACHE.get(key)
        if hit and time.time() - hit[0] < TAB_CACHE_SECONDS:
            return hit[1]
        rows = _read_tab(cfg, tab)
        _TAB_CACHE[key] = (time.time(), rows)
        return rows


def campaigns_view() -> dict:
    """Every campaign, plus any config problem that would stop a run."""
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camps = loaded["campaigns"]
    state = _read_json(SCHEDULE_STATE, {})
    return {
        "globals": loaded["globals"],
        "issues": campaigns_mod.validate(camps, recipes=recipe_mod.load_dir(RECIPES_DIR)),
        "windows_available": windows_available(),
        "campaigns": [{
            "schedule": {k: v for k, v in lane_schedule_view(c, state).items() if k != "schedule"}
            | {k: schedules_mod.normalize(c.schedule)[0][k] for k in ("via", "test_mode")},
            "id": c.id, "name": c.name, "enabled": c.enabled, "priority": c.priority,
            "tab": c.tab, "fieldmap": c.fieldmap,
            "per_run": c.per_run, "per_day": c.per_day,
            "max_spend_usd": c.max_spend_usd,
            "instantly_campaign_id": c.instantly_campaign_id,
            "labels": len(c.labels), "auto_push": c.auto_push,
            "rule_count": sum(len(c.rules.get(b) or []) for b in ("all", "any", "none")),
            "label_issues": instantly_mod.validate_label_specs(c.labels or None),
        } for c in camps],
    }


def build_plan(*, enabled_only: bool = True) -> dict:
    """The free preview: what each campaign WOULD take. No API call, no spend."""
    cfg = load_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    # a pipeline campaign is planned by the pipeline itself, never by the old run-all preview
    lanes = [c for c in loaded["campaigns"] if (c.enabled or not enabled_only) and not _is_pipeline(c)]
    if not lanes:
        return {"campaigns": [], "total_take": 0, "globals": loaded["globals"],
                "warnings": ["no campaign is enabled"], "fieldmaps": {}, "config_issues": []}

    rows_by_tab, fieldmaps, reports, errors = {}, {}, {}, []
    sources = {}
    for tab in sorted({c.tab for c in lanes if c.tab}):
        # the lane is found BEFORE the read, because a lane may name its own sheet and the
        # tab has to be read out of the right document. Tab names are the key here, so two
        # lanes on two sheets must not share a tab name - C1..C9 and the Practices tabs do not.
        lane = next((c for c in lanes if c.tab == tab), None)
        lane_cfg = cfg_for_campaign(cfg, lane)
        sources[tab] = tab_source(lane_cfg, tab)
        try:
            rows = _read_tab_for_display(lane_cfg, tab)
        except Exception as e:  # noqa: BLE001 — a bad tab must not hide the other tabs
            errors.append(f"could not read tab '{tab}': {e}")
            continue
        rows_by_tab[tab] = rows
        heads = runner_mod.headers_of(rows)
        fm = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], heads)
        fieldmaps[tab] = fm
        reports[tab] = runner_mod.check_fieldmap(fm, heads)

    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
    rep = campaigns_mod.plan(rows_by_tab, lanes, fieldmaps, ledger=led,
                             globals_cfg=loaded["globals"],
                             mv_rate_usd=float(cfg.get("mv_per_verification_usd", 0) or 0))
    rep["fieldmaps"] = reports
    rep["sources"] = sources
    rep["config_issues"] = campaigns_mod.validate(loaded["campaigns"])
    rep["warnings"] = (rep.get("warnings") or []) + errors
    return rep


def _read_campaigns_raw() -> dict:
    return _read_json(CONFIG_DIR / "campaigns.json", {"globals": {}, "campaigns": []})


def _write_campaigns_raw(body: dict) -> dict:
    """Validate, keep one backup, then write. A config file is never replaced by a broken
    one — the engine would refuse to run and the previous state would be gone."""
    camps = [campaigns_mod.Campaign(c) for c in (body.get("campaigns") or [])]
    # NOTE: `recipes` is deliberately NOT passed here. A campaign is allowed to be a work in
    # progress — the same reason it may exist with no Instantly id yet. A brand-new recipe has
    # no columns picked, and the editor cannot offer the right columns until a campaign points
    # at it, so blocking the save here made attaching a new recipe impossible. Every screen
    # still SHOWS recipe problems (campaigns_view, detail, readiness), and start_campaign_run
    # refuses to spend a penny on a broken one.
    issues = campaigns_mod.validate(camps)
    for c in camps:
        issues += [{"campaign": c.id, "issue": f"labels: {i}"}
                   for i in instantly_mod.validate_label_specs(c.labels or None)]
    if issues:
        return {"ok": False, "issues": issues}
    path = CONFIG_DIR / "campaigns.json"
    if path.exists():
        (CONFIG_DIR / "campaigns.backup.json").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "campaigns": len(camps)}


def save_campaign(patch: dict) -> dict:
    """Update ONE campaign in place, leaving every other key in the file untouched."""
    cid = str(patch.get("id") or "").strip()
    if not cid:
        return {"ok": False, "issues": [{"campaign": "", "issue": "no campaign id given"}]}
    body = _read_campaigns_raw()
    rows = body.get("campaigns") or []
    idx = next((i for i, c in enumerate(rows) if str(c.get("id")) == cid), -1)
    if idx < 0:
        return {"ok": False, "issues": [{"campaign": cid, "issue": "no such campaign"}]}
    merged = {**rows[idx]}
    for k, v in patch.items():
        if k != "id":
            merged[k] = v
    rows[idx] = merged
    body["campaigns"] = rows
    out = _write_campaigns_raw(body)
    out["campaign"] = cid
    return out


def save_globals(patch: dict) -> dict:
    body = _read_campaigns_raw()
    body["globals"] = {**(body.get("globals") or {}), **patch}
    return _write_campaigns_raw(body)


def create_campaign(req: dict) -> dict:
    """Add a lane — blank, or a copy of `copy_from`. It starts switched off and checked last."""
    body = _read_campaigns_raw()
    rows = body.get("campaigns") or []
    src = None
    if req.get("copy_from"):
        src = next((c for c in rows if str(c.get("id")) == str(req["copy_from"])), None)
        if src is None:
            return {"ok": False, "issues": [{"campaign": "", "issue": f"no campaign '{req['copy_from']}' to copy"}]}
    row, problems = campaigns_mod.new_campaign(
        rows, name=str(req.get("name") or ""), tab=str(req.get("tab") or ""),
        fieldmap=str(req.get("fieldmap") or ""), cid=str(req.get("id") or ""), copy_from=src)
    if problems:
        return {"ok": False, "issues": [{"campaign": str(req.get("id") or ""), "issue": p} for p in problems]}
    body["campaigns"] = rows + [row]
    out = _write_campaigns_raw(body)
    out["campaign"] = row["id"]
    return out


def delete_campaign(cid: str) -> dict:
    """Remove a lane's configuration. Refused while it is running; its past runs, events and
    ledger rows keep the id they recorded."""
    cid = str(cid or "").strip()
    if any(j.get("status") == "running" and j.get("campaign") == cid for j in JOBS.values()):
        return {"ok": False, "issues": [{"campaign": cid, "issue": "it is running — stop the run first"}]}
    body = _read_campaigns_raw()
    rows, problem = campaigns_mod.remove_campaign(body.get("campaigns") or [], cid)
    if problem:
        return {"ok": False, "issues": [{"campaign": cid, "issue": problem}]}
    body["campaigns"] = rows
    out = _write_campaigns_raw(body)
    out["campaign"] = cid
    if out.get("ok"):
        lane_task_delete(cid)                   # its Windows task would fire a lane that is gone
    return out


def import_fieldmap_file(tab: str) -> str:
    """The field-map file an upload's lanes use: one per upload, named after it, so mapping
    one CSV's columns never changes another's."""
    return f"fieldmap.{tab[len(imports_mod.PREFIX):]}.json"


def fieldmap_detail(tab: str = "") -> dict:
    """Everything the mapping screen needs: the engine's fields, what they are mapped to
    today, the sheet's real headers, and how full each column actually is.

    Fill rate matters — mapping to a column that is 0% filled looks correct and silently
    does nothing."""
    cfg = load_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    lane = next((c for c in loaded["campaigns"] if not tab or c.tab == tab), None)
    if not lane and tab:
        # a source nobody reads yet (an upload, or a sheet tab with no campaign): show its columns
        # against its own map file, the same name the New-campaign wizard will give it
        own = import_fieldmap_file(tab) if imports_mod.is_import_tab(tab) else \
            f"fieldmap.{campaigns_mod.slug(tab) or 'source'}.json"
        lane = campaigns_mod.Campaign({"id": "", "tab": tab, "fieldmap": own})
        loaded["fieldmaps"][lane.fieldmap] = fieldmap_mod.load(CONFIG_DIR / lane.fieldmap)
    if not lane:
        return {"error": f"No campaign uses tab '{tab}'."}
    cfg = cfg_for_campaign(cfg, lane)
    try:
        rows = _read_tab_for_display(cfg, lane.tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read tab '{lane.tab}': {e}"}

    heads = runner_mod.headers_of(rows)
    sample = rows[:500]
    fill = {h: (sum(1 for r in sample if str(r.get(h) or "").strip()) * 100 //
                max(1, len(sample))) for h in heads}
    saved = loaded["fieldmaps"].get(lane.fieldmap or "") or fieldmap_mod.FieldMap({})
    auto = fieldmap_mod.suggest(heads)
    check = runner_mod.check_fieldmap(saved.completed(heads), heads)

    fields = []
    for f in fieldmap_mod.FIELDS:
        name = f["name"]
        mapped = saved.header(name)
        fields.append({
            "field": name, "direction": f["dir"], "required": f["required"],
            "recommended": name in fieldmap_mod.RECOMMENDED,
            "note": f.get("note", ""), "aliases": f["aliases"][:4],
            "mapped": mapped, "suggested": auto.get(name, ""),
            "resolved": check["resolved"].get(name, ""),
            "fill": fill.get(mapped or check["resolved"].get(name, ""), None),
        })
    used = {v for v in check["resolved"].values()}
    return {"tab": lane.tab, "file": lane.fieldmap, "rows": len(rows),
            "source": tab_source(cfg, lane.tab),
            "headers": [{"name": h, "fill": fill[h], "used": h in used} for h in heads],
            "fields": fields, "check": check, "preview": rows[:5]}


def save_fieldmap(name: str, mapping: dict) -> dict:
    fname = (name or "").strip() or "fieldmap.json"
    if not fname.endswith(".json") or "/" in fname or "\\" in fname:
        return {"ok": False, "error": "field-map name must be a plain .json filename"}
    path = CONFIG_DIR / fname
    body = _read_json(path, {})
    body["name"] = body.get("name") or fname
    body["mapping"] = {str(k): str(v) for k, v in (mapping or {}).items() if str(v).strip()}
    if path.exists():
        (CONFIG_DIR / (fname[:-5] + ".backup.json")).write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "file": fname, "mapped": len(body["mapping"])}


def start_campaign_run(campaign_id: str, *, test_mode: bool = True) -> dict:
    """Enrich one campaign's next batch. The push is still a separate, confirmed step."""
    cfg = load_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == campaign_id), None)
    if not camp:
        return {"error": f"No campaign '{campaign_id}' in config/campaigns.json."}
    if _is_pipeline(camp):
        return start_pipeline_campaign(camp, trigger=RUN_NOW_TRIGGER, test_mode=test_mode)
    # A switched-off campaign may still do a FREE test (no API call, no ledger, no sheet write),
    # so a new campaign can be tried before it is turned on. A live run needs it on.
    if not camp.enabled and not test_mode:
        return {"error": f"'{camp.name}' is switched off. Switch it on before a live run "
                         "(a free test works while it is off)."}
    # a click and a schedule (or two clicks) must not work the same rows twice at once
    if any(j.get("status") == "running" and j.get("campaign") == camp.id for j in JOBS.values()):
        return {"error": f"'{camp.name}' is already running. Wait for it to finish, or stop it."}

    recipes = recipe_mod.load_dir(RECIPES_DIR)
    problems = [i["issue"] for i in campaigns_mod.validate([camp], recipes=recipes)]
    if problems:
        return {"error": "Campaign config problem: " + "; ".join(problems)}
    rec = recipe_mod.for_campaign(camp, recipes)
    cfg = cfg_for_campaign(cfg, camp)

    try:
        rows = _read_tab(cfg, camp.tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read tab '{camp.tab}': {e}"}

    heads = runner_mod.headers_of(rows)
    fm = runner_mod.fieldmap_for(camp, loaded["fieldmaps"], heads)
    check = runner_mod.check_fieldmap(fm, heads)
    if not check["ok"]:
        return {"error": "Field map problem: " + "; ".join(check["blocking"])}
    # a recipe writes to columns it names itself. A write to a column that is not in the
    # sheet is discarded by Google with no error, so stop BEFORE anything is spent.
    if rec is not None:
        rc = recipe_mod.check_against_sheet(rec, heads)
        if not rc["ok"]:
            return {"error": f"Finding recipe '{rec.name}': " + "; ".join(rc["blocking"])}

    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
    prep = runner_mod.prepare(camp, rows, fm, ledger=led, cfg=cfg)
    firms = prep["firms"]
    if not firms:
        return {"error": f"'{campaign_id}' has no rows to work on right now "
                         f"({prep['matched']} matched, {prep['blocked_by_ledger']} already done, "
                         f"{prep['day_remaining']} left in today's limit)."}

    run_id = uuid.uuid4().hex[:12]
    job = {
        "run_id": run_id, "status": "running", "test_mode": bool(test_mode), "stage": "organize",
        "campaign": camp.id, "campaign_name": camp.name,
        "total": len(firms), "processed": 0, "results": [], "events": [], "_seq": 0,
        "counters": _new_counters(),
        "rates": {"mv_per_verification_usd": cfg.get("mv_per_verification_usd", 0.0),
                  "anymailfinder_usd_per_credit": cfg.get("anymailfinder_usd_per_credit", 0.0),
                  "icypeas_usd_per_credit": cfg.get("icypeas_usd_per_credit", 0.0)},
        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cancel": False,
        "skipped_done": prep["blocked_by_ledger"], "selection": {
            k: prep[k] for k in ("matched", "blocked_by_ledger", "available",
                                 "day_remaining", "selected")},
    }
    JOBS[run_id] = job
    _persist(job)
    threading.Thread(target=_worker, args=(run_id, firms, cfg),
                     kwargs={"campaign": camp, "fm": fm, "recipe": rec}, daemon=True).start()
    return _snapshot(job)


# ── Instantly push (outward-facing: gated by confirm + test mode) ────

ACCEPTED_VERIFICATIONS = {"good", "ok", "valid", "deliverable", "verified"}
# an address the recipe took as-is from the sheet, on purpose without a check
UNCHECKED_SHEET = "accepted_no_check"


def _is_send_ready(row: dict, *, send_unchecked: bool = False) -> bool:
    """THE SEND GATE: `send_ready = yes`, or a verification that actually passed.

    Only a MillionVerifier PASS opens it. An address a finder merely thought was
    'probable' has an email but no pass, and must never be sent. The one exception is
    `send_unchecked`: the sheet's own address, which his rule says is never checked."""
    if str(row.get("send_ready") or "").strip().lower() == "yes":
        return True
    ver = str(row.get("verification") or row.get("Verification Status") or "").strip().lower()
    if send_unchecked and ver == UNCHECKED_SHEET:
        return True
    if str(row.get("send_ready") or "").strip().lower() == "no":
        return False
    return ver in ACCEPTED_VERIFICATIONS


def _push_worker(push_id: str, rows: list[dict], cfg: dict, *, camp=None, fm=None) -> None:
    import time
    job = JOBS[push_id]
    test_mode = job["test_mode"]
    # the lane's own sheet, when it has one, before the write-back is opened below
    cfg = cfg_for_campaign(cfg, camp)
    key = str(cfg.get("instantly_api_key", "")).strip()
    # the campaign's own Instantly id wins; the single config id is the V1 fallback
    campaign = (camp.instantly_campaign_id if camp else "") or \
        str(cfg.get("instantly_campaign_id", "")).strip()
    labels = (camp.labels or None) if camp else None
    options = runner_mod.push_options(camp) if camp else None
    camp_id = camp.id if camp else ""
    use_map = fm is not None and bool(fm.header("row_key"))
    delay = max(0, min(int(cfg.get("push_delay_seconds", 3) or 0), 60))
    writeback = bool(cfg.get("sheet_writeback"))
    write_row, pending = None, []

    def emit(company, stage, status, detail, email=""):
        ev = {"seq": job["_seq"], "ts": _now(), "company": company, "stage": stage,
              "status": status, "detail": detail, "email": email}
        job["_seq"] += 1
        job["events"].append(ev)
        if len(job["events"]) > FEED_WINDOW + 200:
            job["events"] = job["events"][-FEED_WINDOW:]
        job["stage"] = stage
        _append_event(push_id, ev)

    # one live sheet writer, so each pushed lead updates its Status row immediately
    # (same behaviour as n8n's per-item "Update Sheet" node)
    if camp is not None and not tab_source(cfg, camp.tab)["live"]:
        # an uploaded CSV or a local snapshot: there is no sheet row to update
        writeback = False
        if not test_mode:
            emit("", "sheet", "skip", f"'{camp.tab}' is a file, not the live sheet - nothing is written back")
    elif camp is not None and not _lane_writes_back(camp):
        writeback = False
        if not test_mode:
            emit("", "sheet", "skip", "this campaign's 'Update my Google Sheet' is off - nothing is written back")
    elif not test_mode:
        write_row = _open_sheet_writer(cfg, emit, tab=(camp.tab if camp else ""), fm=fm)
    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None

    # global daily send ceiling, across every campaign — the mailbox limit, not a
    # per-campaign one, so one lane cannot quietly eat the whole day's capacity
    loaded_globals = runner_mod.load_config_dir(CONFIG_DIR)["globals"]
    day_cap = int(loaded_globals.get("daily_push_cap") or 0)
    sent_today = led.count_today("push") if (led and day_cap and not test_mode) else 0

    for row in rows:
        if job.get("cancel"):
            break
        if day_cap and not test_mode and sent_today >= day_cap:
            emit("", "push", "skip",
                 f"global daily cap reached ({day_cap}) - stopping, the rest stay queued")
            break
        company = row.get("company", "")
        res = instantly_mod.push_lead(
            runner_mod.label_source_row(row) if camp else row,
            campaign, key, test_mode=test_mode,
            labels=labels, fm=fm, options=options,
            tries=max(1, int(cfg.get("api_tries", 3) or 1)),
            retry_wait=float(cfg.get("api_retry_wait", 5.0) or 0),
            on_retry=lambda a, n, e, p: emit(company, "push", "retry",
                                             f"attempt {a}/{n} failed ({e}) - retrying in {p:.0f}s"))
        if res.get("skipped"):
            job["counters"]["push_skipped"] += 1
            emit(company, "push", "skip", res.get("reason", "skipped"))
        elif res["ok"]:
            job["counters"]["pushed"] += 1
            emit(company, "push", "success",
                 f"{row.get('found_email', '')} → campaign{' (test)' if test_mode else ''}", row.get("found_email", ""))
            sent_today += 1
            job["results"].append({**row, "status": res["status"], "pushed": True})
            # same rule as the run: a dry run never records a real send
            if led:
                led.record({**row, "status": res["status"]}, pushed=True, fm=fm,
                           campaign=camp_id, test_mode=test_mode)
            if writeback:
                # the Ice Breaker column is Icebreaker Studio's: a lane never writes it
                up = sheets_mod.build_writeback_row(row, res["status"], write_icebreaker=camp is None)
                up = sheets_mod.to_sheet_row(up, fm) if use_map else up
                if write_row:
                    try:
                        w = write_row(up)                    # live: one row, right now
                        if w.get("ok"):
                            job["counters"]["written_back"] += 1
                            emit(company, "sheet", "success", f"Status → {res['status']} (row {w['row']})")
                        else:
                            emit(company, "sheet", "fail", f"write-back: {w.get('reason')}")
                    except Exception as e:  # noqa: BLE001 - never let a sheet error kill the push
                        pending.append(up)
                        emit(company, "sheet", "fail", f"write-back error, queued: {e}")
                else:
                    pending.append(up)
        else:
            job["counters"]["push_failed"] += 1
            job["counters"]["errors"] += 1
            emit(company, "push", "fail", str(res.get("error") or res.get("response") or "push failed"))
        job["processed"] += 1
        _persist(job)
        if delay and not test_mode:
            time.sleep(delay)

    # anything that couldn't be written live gets one batched retry at the end
    if writeback and pending and not test_mode:
        sa = str(cfg.get("sheet_service_account_file") or "").strip()
        parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
        if sa and parsed["doc_id"]:
            try:
                out = sheets_mod.SheetsClient(sa).update_statuses(
                    parsed["doc_id"],
                    (camp.tab if camp else "") or cfg.get("sheet_tab") or "Combined", pending,
                    key_column=(fm.header("row_key") if use_map else "Company Name"),
                    allowed=(sheets_mod.writeback_headers(fm) if use_map else None))
                job["counters"]["written_back"] += out.get("updated", 0)
                emit("", "sheet", "success", f"retried {out.get('updated', 0)} queued rows")
            except Exception as e:  # noqa: BLE001
                emit("", "sheet", "fail", f"queued write-back failed: {e}")

    job["status"] = "cancelled" if job.get("cancel") else "finished"
    job["stage"] = "done"
    job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _persist(job)
    _append_history(job)            # so a push can be found again after leaving its page
    _prune_runs()


def _lane_icebreakers(cfg: dict, camp, fm, rows: list[dict]) -> tuple[list[dict], list[dict], str]:
    """A lane's send-ready rows carrying Icebreaker Studio's CURRENT line
    -> (ready, waiting for a line, note).

    The live tab is read again (free, no API spend): Studio may have written lines since
    the run. If the sheet cannot be read, the lines the run saw are used and the note says
    so. The push and its preview both call this, so what is previewed is what is sent."""
    note = ""
    cfg = cfg_for_campaign(cfg, camp)
    try:
        rows = runner_mod.refresh_icebreakers(rows, _read_tab(cfg, camp.tab), fm)
    except Exception as e:  # noqa: BLE001 - an unreadable sheet falls back to the run's lines
        rows = runner_mod.refresh_icebreakers(rows, [], fm)
        note = f"Could not re-read the sheet ({e}), so these are the lines the run saw."
    if not cfg.get("hold_without_icebreaker", True):
        return rows, [], note
    ready, waiting = runner_mod.split_by_icebreaker(rows)
    return ready, waiting, note


def start_push(run_id: str = "", *, test_mode: bool = True, confirm: bool = False) -> dict:
    """Push the verified leads of a finished run to Instantly. Requires an explicit
    confirm; a real (non-test) push also needs a key + campaign id."""
    if not confirm:
        return {"error": "Push not confirmed."}
    cfg = load_config()
    snap = get_run(run_id) if run_id else latest_run(kind="run")
    if not snap:
        return {"error": "No run to push. Do a Live run first."}

    # the campaign this run belonged to, if any — it carries the target id, the label
    # table and the Instantly options
    camp, fm = None, None
    camp_id = str(snap.get("campaign") or "").strip()
    if camp_id:
        loaded = runner_mod.load_config_dir(CONFIG_DIR)
        camp = next((c for c in loaded["campaigns"] if c.id == camp_id), None)
        if camp is None:
            return {"error": f"This run belonged to campaign '{camp_id}', which is no longer "
                             "in config/campaigns.json. Restore it before pushing."}
        fm = loaded["fieldmaps"].get(camp.fieldmap or "")

    # A free test's addresses are INVENTED from name patterns and "verified" by a stub that
    # never contacts a mail server (core/verify.py test_transport says "ok" to first.last@).
    # They pass the send gate on paper, so a live push of a test run would mail made-up
    # addresses and bounce. Only a dry run of them is allowed. (found 2026-10-05)
    if snap.get("test_mode") and not test_mode:
        return {"error": "This was a free test: its addresses were made up and never checked, so they "
                         "cannot be sent. Run the campaign live, then send from that run."}
    found = [r for r in snap.get("results", []) if r.get("found_email")]
    if not found:
        return {"error": "That run has no verified emails to push."}
    found, already = _drop_already_pushed(found, fm, cfg, test_run=bool(snap.get("test_mode")))
    if not found:
        return {"error": f"All {already} leads from this run are already in Instantly. Nothing was pushed."}
    return _launch_push(found, cfg, camp=camp, fm=fm, test_mode=test_mode,
                        source_run=snap.get("run_id"),
                        campaign_name=snap.get("campaign_name", ""))


def _send_gate(found: list[dict], cfg: dict) -> list[dict]:
    """THE SEND GATE. Only a verification PASS may be sent (plus the sheet's own unchecked
    address, when that setting is on). V1 pushed anything with an address, which is how an
    unverified Icypeas "probable" would have gone out."""
    unchecked = bool(cfg.get("send_unchecked_sheet_emails", True))
    return [r for r in found if _is_send_ready(r, send_unchecked=unchecked)]


def _launch_push(found: list[dict], cfg: dict, *, camp=None, fm=None, test_mode: bool = True,
                 source_run=None, campaign_name: str = "", backlog_runs: int = 0) -> dict:
    """Gate, hold, check the target, then start one push job for `found`. A single run's
    send and a campaign's whole backlog both come through here, so they cannot drift."""
    rows = _send_gate(found, cfg)
    held = len(found) - len(rows)
    if not rows:
        return {"error": f"None of the {len(found)} addresses passed verification, so none "
                         "are send-ready. Nothing was pushed."}
    if camp is not None:
        rows, waiting, _note = _lane_icebreakers(cfg, camp, fm, rows)
        if not rows:
            return {"error": f"None of the {len(waiting)} send-ready leads has an Icebreaker "
                             "Studio line on the sheet yet, so none were pushed. Run Icebreaker "
                             "Studio for them, or switch off 'Hold leads without an ice "
                             "breaker' in Settings."}

    if not test_mode:
        if not str(cfg.get("instantly_api_key", "")).strip():
            return {"error": "Add your Instantly API key in Settings before a live push."}
        target = (camp.instantly_campaign_id if camp else "") or \
            str(cfg.get("instantly_campaign_id", "")).strip()
        if not target:
            return {"error": ("Campaign '%s' has no instantly.campaign_id in "
                              "config/campaigns.json." % camp.id) if camp else
                             "Add your Instantly campaign id in Settings before a live push."}
    push_id = uuid.uuid4().hex[:12]
    job = {
        "run_id": push_id, "kind": "push", "source_run": source_run,
        "backlog_runs": backlog_runs,
        "status": "running", "test_mode": bool(test_mode), "stage": "push",
        "total": len(rows), "processed": 0, "results": [], "events": [], "_seq": 0,
        "counters": _new_counters(),
        "rates": {"mv_per_verification_usd": cfg.get("mv_per_verification_usd", 0.0),
                  "anymailfinder_usd_per_credit": cfg.get("anymailfinder_usd_per_credit", 0.0),
                  "icypeas_usd_per_credit": cfg.get("icypeas_usd_per_credit", 0.0)},
        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cancel": False,
    }
    job["campaign"] = camp.id if camp else ""
    job["campaign_name"] = camp.name if camp else campaign_name
    job["held_not_send_ready"] = held
    JOBS[push_id] = job
    _persist(job)
    threading.Thread(target=_push_worker, args=(push_id, rows, cfg),
                     kwargs={"camp": camp, "fm": fm}, daemon=True).start()
    return _snapshot(job)


# ── a campaign's backlog: every found lead that never reached Instantly ──
#
# Found 2026-10-15: auto-push only ever sent the run that had just finished, and the Send tab
# only one run. Leads found while sending was off were stranded — nothing picked them up
# again. The backlog reads every saved live run of the lane, keeps each lead's newest copy,
# and drops whatever the ledger already shows as pushed. The ledger itself cannot be the
# source: it holds the address but not the labels, names and ice breaker a push needs.

def _campaign_and_fm(camp_id: str):
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == camp_id), None)
    return camp, (loaded["fieldmaps"].get(camp.fieldmap or "") if camp else None)


def campaign_backlog(camp_id: str, fm=None) -> tuple[list[dict], int]:
    """(found-but-never-pushed leads, how many runs they came from), oldest run first."""
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    newest: dict[str, tuple[dict, str]] = {}
    for fp in files:
        if fp.name.endswith(".events.ndjson"):
            continue
        rec = _read_json(fp, None)
        if (not rec or rec.get("kind", "run") != "run" or rec.get("test_mode")
                or rec.get("campaign") != camp_id or rec.get("status") == "running"):
            continue
        for r in rec.get("results") or []:
            if not r.get("found_email"):
                continue
            key = ledger_mod.key_of(r, fm) or str(r.get("found_email")).strip().lower()
            newest.pop(key, None)                # re-insert so the order follows the newest run
            newest[key] = (r, rec.get("run_id", fp.stem))
    led = ledger_mod.Ledger(LEDGER_FILE)
    try:
        rows = [(r, rid) for r, rid in newest.values() if not led.is_done(r, stage="push", fm=fm)]
    finally:
        led.close()
    return [r for r, _ in rows], len({rid for _, rid in rows})


def _drop_already_pushed(found: list[dict], fm, cfg: dict, *,
                         test_run: bool = False) -> tuple[list[dict], int]:
    """(leads the ledger has no push for, how many it already has). Found 2026-10-15: a run's
    own Send tab offered all 54 of a run whose leads were all already in Instantly, so one
    click would have sent every one again. A free test's leads are never in the ledger and
    may share a key with a real sent lead, so they are left alone."""
    if test_run or not cfg.get("use_ledger", True):
        return found, 0
    led = ledger_mod.Ledger(LEDGER_FILE)
    try:
        rows = [r for r in found if not led.is_done(r, stage="push", fm=fm)]
    finally:
        led.close()
    return rows, len(found) - len(rows)


def _push_running(camp_id: str) -> bool:
    return any(j.get("kind") == "push" and j.get("status") == "running"
               and j.get("campaign") == camp_id for j in JOBS.values())


def start_backlog_push(camp_id: str, *, test_mode: bool = True, confirm: bool = False) -> dict:
    """Send every waiting lead of one campaign in one push job."""
    if not confirm:
        return {"error": "Push not confirmed."}
    camp, fm = _campaign_and_fm(camp_id)
    if camp is None:
        return {"error": f"No campaign '{camp_id}'."}
    cfg = load_config()
    # the ledger is the only record of what already went: without it every send repeats
    if not cfg.get("use_ledger", True):
        return {"error": "The lead history (use_ledger) is off, so the app cannot tell which "
                         "leads were already sent. Switch it on in Settings first."}
    # two sends of one backlog at once would both read the ledger before either wrote to it
    if _push_running(camp.id):
        return {"error": "A send for this campaign is already running — wait for it to finish."}
    found, n_runs = campaign_backlog(camp.id, fm)
    if not found:
        return {"error": "Nothing is waiting: every lead this campaign found is already in Instantly."}
    return _launch_push(found, cfg, camp=camp, fm=fm, test_mode=test_mode,
                        backlog_runs=n_runs)


# ── Windows Task Scheduler (fixed commands, validated numbers only) ──

TASK_NAME = "LeadGenAutomationEngine"


def _schtasks(args: list[str]) -> dict:
    import subprocess
    try:
        p = subprocess.run(["schtasks"] + args, capture_output=True, text=True, timeout=25)
        return {"ok": p.returncode == 0, "out": (p.stdout or "").strip(), "err": (p.stderr or "").strip()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "out": "", "err": str(e)}


def schedule_status() -> dict:
    r = _schtasks(["/query", "/tn", TASK_NAME, "/fo", "LIST"])
    if not r["ok"]:
        return {"scheduled": False, "task": TASK_NAME}
    info = {}
    for line in r["out"].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    return {"scheduled": True, "task": TASK_NAME,
            "next_run": info.get("Next Run Time", ""), "status": info.get("Status", ""),
            "last_run": info.get("Last Run Time", "")}


_HHMM = r"([01]\d|2[0-3]):[0-5]\d"
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _schedule_args(kind: str, every: int, start: str, end: str, days: list[str]) -> tuple[list[str], dict, str]:
    """Translate a trigger choice into schtasks flags. Returns (flags, summary, error).
    Every value is validated here - nothing is interpolated into a shell string."""
    kind = (kind or "minute").lower().strip()
    if not re.fullmatch(_HHMM, str(start or "")):
        return [], {}, "Start time must be HH:MM (24h)."

    if kind == "minute":
        n = max(1, min(int(every or 30), 1439))
        if not re.fullmatch(_HHMM, str(end or "")):
            return [], {}, "End time must be HH:MM (24h)."
        return (["/sc", "minute", "/mo", str(n), "/st", start, "/et", end],
                {"summary": f"every {n} min, {start}–{end}"}, "")

    if kind == "hourly":
        n = max(1, min(int(every or 1), 23))
        args = ["/sc", "hourly", "/mo", str(n), "/st", start]
        summary = f"every {n} hour{'s' if n > 1 else ''} from {start}"
        if str(end or "").strip():
            if not re.fullmatch(_HHMM, str(end)):
                return [], {}, "End time must be HH:MM (24h)."
            args += ["/et", end]
            summary += f" until {end}"
        return args, {"summary": summary}, ""

    if kind == "daily":
        n = max(1, min(int(every or 1), 365))
        return (["/sc", "daily", "/mo", str(n), "/st", start],
                {"summary": f"every {n} day{'s' if n > 1 else ''} at {start}"}, "")

    if kind == "weekly":
        picked = [d.upper() for d in (days or []) if d.upper() in WEEKDAYS]
        if not picked:
            return [], {}, "Pick at least one weekday."
        n = max(1, min(int(every or 1), 52))
        return (["/sc", "weekly", "/mo", str(n), "/d", ",".join(picked), "/st", start],
                {"summary": f"{', '.join(picked)} at {start}" + (f" every {n} weeks" if n > 1 else "")}, "")

    return [], {}, f"Unknown trigger type '{kind}'."


def schedule_create(every_minutes: int = 30, start: str = "08:00", end: str = "17:30",
                    test_mode: bool = True, from_sheet: bool = False, push: bool = False,
                    kind: str = "minute", days: list[str] | None = None) -> dict:
    """Register the trigger. kind = minute | hourly | daily | weekly (n8n-style choices);
    V7's own cadence is minute/30 between 08:00 and 17:30."""
    args, info, err = _schedule_args(kind, every_minutes, start, end, days or [])
    if err:
        return {"ok": False, "error": err}
    flags = ""
    if test_mode:
        flags += " --test"
    if from_sheet:
        flags += " --from-sheet"
    if push:
        flags += " --push"
    runner = ROOT / "run-scheduled.bat"
    runner.write_text(
        "@echo off\r\n"
        f'cd /d "{ROOT}"\r\n'
        'set "PY=C:\\ClaudeDeps\\docpipeline-venv\\Scripts\\python.exe"\r\n'
        'if not exist "%PY%" set "PY=python"\r\n'
        f'"%PY%" scheduled_run.py{flags} >> "{ROOT / "data" / "scheduled.log"}" 2>&1\r\n',
        encoding="utf-8")
    r = _schtasks(["/create", "/tn", TASK_NAME, "/tr", f'"{runner}"'] + args + ["/f"])
    if not r["ok"]:
        return {"ok": False, "error": r["err"] or r["out"] or "schtasks failed"}
    return {"ok": True, "kind": kind, "summary": info.get("summary", ""),
            "test_mode": test_mode, "from_sheet": from_sheet, "push": push, **schedule_status()}


def schedule_delete() -> dict:
    r = _schtasks(["/delete", "/tn", TASK_NAME, "/f"])
    return {"ok": r["ok"], "error": "" if r["ok"] else (r["err"] or r["out"])}


# ── per-campaign schedules (V4 G): the engine's own clock OR one Windows task per lane ──
#
# `schedule.via` picks the ONE trigger that fires a lane, so it never runs twice. The app
# clock works on any server (Linux included); a Windows task also runs while the app is shut.

SCHEDULE_STATE = DATA / "schedule_state.json"    # last slot fired per lane: no double fire
SCHEDULE_LOG = DATA / "schedule.log"
TASKS_DIR = DATA / "tasks"                       # the .bat each Windows task starts
LANE_TASK_PREFIX = "LeadGen-"
TICK_SECONDS = 30
_SCHED_LOCK = threading.Lock()


def windows_available() -> bool:
    return os.name == "nt"


def _sched_log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    try:
        with SCHEDULE_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _lane_task_name(cid: str) -> str:
    return LANE_TASK_PREFIX + cid


def lane_task_status(cid: str) -> dict:
    if not windows_available():
        return {"exists": False}
    r = _schtasks(["/query", "/tn", _lane_task_name(cid), "/fo", "LIST"])
    if not r["ok"]:
        return {"exists": False}
    info = dict((k.strip(), v.strip()) for k, _s, v in
                (ln.partition(":") for ln in r["out"].splitlines() if ":" in ln))
    return {"exists": True, "name": _lane_task_name(cid), "next_run": info.get("Next Run Time", ""),
            "last_run": info.get("Last Run Time", ""), "status": info.get("Status", "")}


def lane_task_create(cid: str, s: dict) -> dict:
    """One Windows task for one lane. Every value passed to schtasks is validated by
    _schedule_args; the lane id is validated by campaigns.ID_RE before it gets here."""
    if not windows_available():
        return {"ok": False, "error": "Windows Task Scheduler only exists when the engine runs on Windows."}
    if s["kind"] in ("minute", "hourly") and s["days"]:
        return {"ok": False, "error": "A Windows task cannot limit an every-N-minutes or every-N-hours "
                                      "schedule to certain days. Clear the days, or let the app run it."}
    args, _info, err = _schedule_args(s["kind"], s["every"], s["start"], s["end"], s["days"])
    if err:
        return {"ok": False, "error": err}
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    bat = TASKS_DIR / f"{_lane_task_name(cid)}.bat"
    bat.write_text(
        "@echo off\r\n"
        f'cd /d "{ROOT}"\r\n'
        f'"{sys.executable}" scheduled_run.py --campaign {cid}{" --test" if s["test_mode"] else ""}'
        f' >> "{DATA / "scheduled.log"}" 2>&1\r\n', encoding="utf-8")
    r = _schtasks(["/create", "/tn", _lane_task_name(cid), "/tr", f'"{bat}"'] + args + ["/f"])
    if not r["ok"]:
        return {"ok": False, "error": r["err"] or r["out"] or "schtasks failed"}
    b = _task_allow_battery(_lane_task_name(cid))
    if not b["ok"]:
        _sched_log(f"{cid}: task created, but it may not start on battery — {b['err']}")
    return {"ok": True, **lane_task_status(cid)}


def _task_allow_battery(name: str) -> dict:
    """Let a task start (and keep running) on battery.

    schtasks /create leaves Windows' defaults on: "start only on AC power" and "stop if the
    computer switches to battery". On a laptop on battery the task is then SKIPPED in silence —
    Last Run Time never changes (found 2026-10-04, 93% battery, slot 19:35 never ran). schtasks
    cannot change these settings; PowerShell can. `name` is LeadGen-<id> with the id already
    checked against campaigns.ID_RE, so it holds only [a-z0-9_-]."""
    import subprocess
    if not re.fullmatch(r"LeadGen-[a-z0-9][a-z0-9_-]{0,62}", name):
        return {"ok": False, "err": "unexpected task name"}
    script = (f"$t = Get-ScheduledTask -TaskName '{name}'; $s = $t.Settings; "
              "$s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; "
              f"Set-ScheduledTask -TaskName '{name}' -Settings $s | Out-Null")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=30)
        return {"ok": p.returncode == 0, "err": (p.stderr or "").strip()[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": str(e)}


def lane_task_delete(cid: str) -> None:
    """Remove a lane's Windows task if it has one. Missing is fine — that is the goal."""
    if windows_available() and lane_task_status(cid)["exists"]:
        _schtasks(["/delete", "/tn", _lane_task_name(cid), "/f"])
    try:
        (TASKS_DIR / f"{_lane_task_name(cid)}.bat").unlink()
    except FileNotFoundError:
        pass


def _lane_running(cid: str) -> bool:
    return any(j.get("status") == "running" and j.get("campaign") == cid for j in JOBS.values())


def _live_spend_today() -> float:
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(float(h.get("spent_usd") or 0) for h in _read_json(HISTORY_FILE, [])
               if not h.get("test_mode") and str(h.get("when", "")).startswith(today))


def start_pipeline_campaign(camp, *, trigger: str, test_mode: bool = False, wait: bool = False) -> dict:
    """A pipeline campaign's Run button or its own schedule (2026-11-07): all 6 steps, now, on
    the campaign's own settings. There is no free test: every lead goes only into a Draft or
    Paused Instantly campaign (checked before each push), so nothing is ever sent."""
    if test_mode:
        return {"error": f"'{camp.name}' runs the 6-step pipeline, which has no free test. "
                         "It only adds leads to a Draft Instantly campaign, so nothing is sent. Use Run now."}
    if not camp.enabled:
        return {"error": f"'{camp.name}' is switched off. Switch it on first."}
    if not camp.instantly_campaign_id:
        return {"error": f"'{camp.name}' has no Instantly campaign. Choose one under “Send to”."}
    r = _start_chain(_stack_store(), trigger, list(ssched_mod.STEP_KEYS), source=f"campaign:{camp.id}",
                     pace=1.0, wait=wait)
    if not r.get("ok"):
        return {"error": r.get("error") or "The run did not start."}
    return {"run_id": r["run_id"], "pipeline": True, "source": f"campaign:{camp.id}"}


def fire_lane(camp, *, test_mode: bool, wait: bool = False, source: str = "app") -> dict:
    """Start one scheduled run (+ the push when the lane has auto_push). Same guards as a
    click: the lane is not already running, today's spend cap is not reached."""
    if _is_pipeline(camp):          # its schedule runs all 6 steps (always real, Draft-only push)
        snap = start_pipeline_campaign(camp, trigger=SCHEDULED_TRIGGER, wait=wait)
        _sched_log(f"{camp.id}: {source} " + (snap.get("error") or f"started pipeline run {snap['run_id']}"))
        return snap
    if not test_mode:
        cap = float(runner_mod.load_config_dir(CONFIG_DIR)["globals"].get("daily_spend_cap_usd") or 0)
        spent = _live_spend_today()
        if cap and spent >= cap:
            return {"error": f"today's spend cap is reached (${spent:.2f} of ${cap:.2f})"}
    snap = start_campaign_run(camp.id, test_mode=test_mode)
    if snap.get("error"):
        return snap
    run_id = snap["run_id"]
    _sched_log(f"{camp.id}: {source} started run {run_id} ({'test' if test_mode else 'live'})")
    if camp.auto_push:
        def push_after():
            wait_for_job(run_id)
            # live: the lane's whole backlog, so leads found while sending was off go too.
            # A test run's addresses are made up and never in the backlog: send just that run.
            p = (start_push(run_id, test_mode=True, confirm=True) if test_mode
                 else start_backlog_push(camp.id, test_mode=False, confirm=True))
            _sched_log(f"{camp.id}: auto-push after {run_id}: "
                       + (p.get("error") or f"push {p.get('run_id')} started"))
            if wait and not p.get("error"):
                wait_for_job(p["run_id"])
        if wait:
            push_after()
        else:
            threading.Thread(target=push_after, daemon=True).start()
    elif wait:
        wait_for_job(run_id)
    return snap


def _parse_ts(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def scheduler_tick(now: datetime | None = None) -> list[dict]:
    """Fire every app-scheduled lane whose slot has come. Returns what it did (for tests/logs).

    The slot is recorded BEFORE the run starts, so a crash mid-start can never fire it twice."""
    now = now or datetime.now()
    did = []
    with _SCHED_LOCK:
        state = _read_json(SCHEDULE_STATE, {})
        for camp in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]:
            s, problems = schedules_mod.normalize(camp.schedule)
            if problems or not (camp.enabled and s["enabled"] and s["via"] == "app"):
                continue
            st = state.setdefault(camp.id, {})
            slot, missed = schedules_mod.due(s, _parse_ts(st.get("last_fire")), now)
            if missed:
                _sched_log(f"{camp.id}: skipped {missed} missed run(s) — the engine was not running")
                st["last_fire"] = (now - schedules_mod.GRACE).isoformat(timespec="seconds")
            if slot is None:
                continue
            st["last_fire"] = slot.isoformat(timespec="seconds")
            _write_json(SCHEDULE_STATE, state)
            if _lane_running(camp.id):
                res = {"error": "it is still running from before"}
            else:
                try:
                    res = fire_lane(camp, test_mode=s["test_mode"])
                except Exception as e:  # noqa: BLE001 - one lane must not stop the clock
                    res = {"error": str(e)}
            st.update({"fired_at": now.isoformat(timespec="seconds"),
                       "result": res.get("error") or "started", "run_id": res.get("run_id", "")})
            if res.get("error"):
                _sched_log(f"{camp.id}: not started — {res['error']}")
            did.append({"campaign": camp.id, "slot": st["last_fire"], **st})
        _write_json(SCHEDULE_STATE, state)
    return did


def _scheduler_loop() -> None:
    _sched_log("app scheduler started")
    while True:
        try:
            scheduler_tick()
        except Exception as e:  # noqa: BLE001 - the clock keeps ticking
            _sched_log(f"scheduler error: {e}")
        try:
            stack_tick()             # build session 3: the per-step schedules (demo only)
        except Exception as e:  # noqa: BLE001
            _sched_log(f"stack scheduler error: {e}")
        time.sleep(TICK_SECONDS)


def lane_schedule_view(camp, state: dict | None = None, *, now: datetime | None = None) -> dict:
    s, problems = schedules_mod.normalize(camp.schedule)
    if s["enabled"] and s["via"] == "windows" and not windows_available():
        # a lane saved on the Windows PC and copied to a Linux server: nothing would ever fire it
        problems.append("set to run from Windows, but this server is not Windows — "
                        "open its Schedule tab and choose In the app")
    now = now or datetime.now()
    on = bool(camp.enabled and s["enabled"] and not problems)
    nxt = schedules_mod.next_after(s, now) if on else None
    st = (state if state is not None else _read_json(SCHEDULE_STATE, {})).get(camp.id, {})
    return {"schedule": s, "problems": problems, "summary": schedules_mod.summary(s),
            "active": on, "next_run": nxt.strftime("%Y-%m-%d %H:%M") if nxt else "",
            "last": st}


def save_lane_schedule(cid: str, raw: dict) -> dict:
    """Validate, set the ONE trigger (create the Windows task, or remove it), then save."""
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == cid), None)
    if camp is None:
        return {"ok": False, "problems": [f"no campaign '{cid}'"]}
    s, problems = schedules_mod.normalize(raw)
    if s["via"] == "windows" and not windows_available():
        problems.append("this engine is not running on Windows — use the app trigger")
    if problems:
        return {"ok": False, "problems": problems}

    if s["enabled"] and s["via"] == "windows":
        t = lane_task_create(cid, s)
        if not t["ok"]:
            return {"ok": False, "problems": [t["error"]]}
    else:
        lane_task_delete(cid)                     # switching to the app removes the other trigger

    out = save_campaign({"id": cid, "schedule": s})
    if not out.get("ok"):
        if s["via"] == "windows":
            lane_task_delete(cid)
        return {"ok": False, "problems": [i["issue"] for i in out.get("issues", [])]}
    if s["enabled"] and s["via"] == "app":
        # start counting from now: a slot from a few minutes ago must not fire on saving
        with _SCHED_LOCK:
            state = _read_json(SCHEDULE_STATE, {})
            state.setdefault(cid, {})["last_fire"] = datetime.now().isoformat(timespec="seconds")
            _write_json(SCHEDULE_STATE, state)
    camp.schedule = s
    return {"ok": True, **lane_schedule_view(camp)}


def latest_run(kind: str | None = None) -> dict | None:
    """Newest job. kind="run" skips push jobs, so the Dashboard keeps showing the
    enrichment run (and its credits) after you push."""
    live = [j for j in JOBS.values() if kind is None or j.get("kind", "run") == kind]
    if live:
        return _snapshot(max(live, key=lambda j: j["started"]))
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for fp in files:
        rec = _read_json(fp, None)
        if rec and (kind is None or rec.get("kind", "run") == kind):
            return get_run(fp.stem)
    return None


def get_run(run_id: str, since: int = 0) -> dict | None:
    if run_id in JOBS:
        return _snapshot(JOBS[run_id], since)
    rec = _read_json(_run_file(run_id), None)
    if not rec:
        return None
    rec["events"] = _read_events(run_id, since, limit=FEED_WINDOW)
    rec["credits"] = _credit_breakdown(
        load_config(), {} if rec.get("test_mode") else rec.get("counters", {}).get("credits", {}))
    return rec


# ───────────────────────── FastAPI ─────────────────────────

@asynccontextmanager
async def _lifespan(_app):
    # The app clock runs only inside the served engine, never when a script (scheduled_run.py,
    # plan.py, the evals) imports this module. LEADGEN_NO_SCHEDULER=1 switches it off.
    if os.environ.get("LEADGEN_NO_SCHEDULER") != "1":
        threading.Thread(target=_scheduler_loop, name="leadgen-scheduler", daemon=True).start()
    yield


app = FastAPI(title="Lead Gen Automation Engine", lifespan=_lifespan)


# ── login (V4 I): one password, only once one is set or the server requires it ──

AUTH_FILE = DATA / "auth.json"
_AUTH_OPEN = {"/api/auth/status", "/api/auth/login", "/api/auth/logout"}
_THROTTLE = auth_mod.Throttle()


def login_required() -> bool:
    return auth_mod.is_set(auth_mod.load(AUTH_FILE)) or os.environ.get("LEADGEN_REQUIRE_LOGIN") == "1"


def _signed_in(request: Request) -> bool:
    return auth_mod.valid(auth_mod.load(AUTH_FILE), request.cookies.get(auth_mod.COOKIE))


def _client(request: Request) -> str:
    # behind Next (and a proxy) the socket is always 127.0.0.1; the first forwarded address
    # is the browser's
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _set_session(resp: Response, request: Request, rec: dict) -> None:
    # behind Caddy + Next the engine cannot always see the browser's scheme, so a server says
    # so outright (deploy/leadgen.service); a Secure cookie over plain http would never return
    https = os.environ.get("LEADGEN_SECURE_COOKIE") == "1" or \
        request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(auth_mod.COOKIE, auth_mod.issue(rec), max_age=auth_mod.SESSION_SECONDS,
                    httponly=True, samesite="lax", secure=https, path="/")


@app.middleware("http")
async def _login_gate(request: Request, call_next):
    path = request.url.path
    if path in _AUTH_OPEN or not login_required() or _signed_in(request):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "Sign in first.", "login": True}, status_code=401)
    return HTMLResponse('<body style="font:15px system-ui;margin:12vh auto;max-width:30rem">'
                        '<p>Sign in first: <a href="/login">/login</a></p></body>', status_code=401)


@app.middleware("http")
async def _privacy_gate(request: Request, call_next):
    """Privacy switch on: every /api/stack/ JSON answer is masked (core/privacy.py) before it
    leaves the engine. The pipeline still runs on the real values."""
    resp = await call_next(request)
    if not request.url.path.startswith("/api/stack/") or "json" not in resp.headers.get("content-type", ""):
        return resp
    try:
        on = stack_presenting_get()["on"]
    except Exception:  # noqa: BLE001
        on = False
    if not on:
        return resp
    body = b"".join([chunk async for chunk in resp.body_iterator])
    try:
        data = privacy_mod.mask(json.loads(body or b"null"), _privacy_names())
    except ValueError:
        return Response(body, status_code=resp.status_code, media_type=resp.media_type)
    return JSONResponse(data, status_code=resp.status_code)


_PRIVACY_NAMES: dict = {"at": 0.0, "names": []}


def _privacy_names() -> list[str]:
    """Person names of every runnable source, kept for a minute."""
    if time.time() - _PRIVACY_NAMES["at"] < 60:
        return _PRIVACY_NAMES["names"]
    names: set[str] = set()
    for src in ["demo"] + [f"campaign:{c.id}" for c in _pipeline_camps()]:
        try:
            p = _stack_parts(src)
        except Exception:  # noqa: BLE001
            continue
        names.update(privacy_mod.names_from_rows(p["rows"]))
        names.update(privacy_mod.names_from_rows(
            [{"contact_name": v.get("contact", "")} for v in _stack_store().email_results(p["store_source"]).values()]))
    _PRIVACY_NAMES.update(at=time.time(), names=sorted(names, key=len, reverse=True))
    return _PRIVACY_NAMES["names"]


@app.get("/api/auth/status")
def api_auth_status(request: Request):
    rec = auth_mod.load(AUTH_FILE)
    return {"required": login_required(), "password_set": auth_mod.is_set(rec),
            "signed_in": _signed_in(request), "set_at": rec.get("set_at", ""),
            "server_requires": os.environ.get("LEADGEN_REQUIRE_LOGIN") == "1"}


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    rec = auth_mod.load(AUTH_FILE)
    if not auth_mod.is_set(rec):
        return {"ok": False, "error": "No password is set yet. On the server, run: python set_password.py"}
    who = _client(request)
    wait = _THROTTLE.blocked(who)
    if wait:
        return {"ok": False, "error": f"Too many wrong passwords. Try again in {wait // 60 + 1} min."}
    if not auth_mod.verify(rec, str((await request.json()).get("password") or "")):
        _THROTTLE.miss(who)
        return {"ok": False, "error": "Wrong password."}
    _THROTTLE.clear(who)
    resp = JSONResponse({"ok": True})
    _set_session(resp, request, rec)
    return resp


@app.post("/api/auth/logout")
def api_auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth_mod.COOKIE, path="/")
    return resp


@app.post("/api/auth/password")
async def api_auth_password(request: Request):
    """Set or change the password. Changing needs the current one; a new password signs
    every other browser out, and this one straight back in."""
    b = await request.json()
    rec = auth_mod.load(AUTH_FILE)
    if auth_mod.is_set(rec) and not auth_mod.verify(rec, str(b.get("current") or "")):
        return {"ok": False, "error": "The current password is wrong."}
    new = str(b.get("new") or "")
    why = auth_mod.check_strength(new)
    if why:
        return {"ok": False, "error": f"Not saved: {why}."}
    rec = auth_mod.make(new)
    auth_mod.save(AUTH_FILE, rec)
    resp = JSONResponse({"ok": True, "set_at": rec["set_at"]})
    _set_session(resp, request, rec)
    return resp


@app.post("/api/auth/clear")
async def api_auth_clear(request: Request):
    """Remove the password: the app is open again. Refused where the server requires a login."""
    if os.environ.get("LEADGEN_REQUIRE_LOGIN") == "1":
        return {"ok": False, "error": "This server requires a login, so the password cannot be removed."}
    rec = auth_mod.load(AUTH_FILE)
    if auth_mod.is_set(rec) and not auth_mod.verify(rec, str((await request.json()).get("current") or "")):
        return {"ok": False, "error": "The current password is wrong."}
    AUTH_FILE.unlink(missing_ok=True)
    return {"ok": True}


@app.middleware("http")
async def no_cache(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


# The screens are a separate Next.js app (web/) on their own port, which passes /api through
# to this engine. The V1 interface is untouched and stays reachable at /legacy — it is the
# fallback if anything about the new one misbehaves.
SCREENS_URL = os.environ.get("LEADGEN_SCREENS_URL", "http://127.0.0.1:3200/")


@app.get("/", response_class=HTMLResponse)
def index():
    # a page, not a redirect: if the screens are not running, a redirect lands on a browser
    # error that says nothing about why, or that /legacy still works
    return (
        "<body style=\"font:15px system-ui;max-width:38rem;margin:12vh auto;padding:0 1.5rem;"
        "line-height:1.6\"><h1>This is the engine</h1>"
        f"<p>The screens are at <a href=\"{SCREENS_URL}\">{SCREENS_URL}</a>. "
        "<code>start-app.bat</code> starts both.</p>"
        "<p><a href=\"/legacy\">Open the original interface instead &rarr;</a></p></body>"
    )


@app.get("/legacy", response_class=HTMLResponse)
def legacy_index():
    """The V1 interface, kept working so there is always a way back."""
    return (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/style.css")
def style():
    return FileResponse(WEBAPP_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
def appjs():
    return FileResponse(WEBAPP_DIR / "app.js", media_type="application/javascript")


@app.get("/api/config")
def api_get_config():
    cfg = dict(load_config())
    cfg["has_api_key"] = bool(_mv_key(cfg))
    cfg["keys_set"] = {f: bool(str(cfg.get(f, "")).strip()) for f in _KEY_FIELDS}
    for f in _KEY_FIELDS:                       # never send a real key to the browser
        v = str(cfg.get(f, ""))
        cfg[f] = ("*" * 6 + v[-4:]) if v else ""
    return cfg


@app.post("/api/config")
async def api_save_config(request: Request):
    patch = await request.json()
    for f in _KEY_FIELDS:                       # don't save the masked value back over a real key
        v = patch.get(f)
        if isinstance(v, str) and "*" in v:
            patch.pop(f, None)
    for bk in _BOOL_KEYS:
        if bk in patch:
            patch[bk] = bool(patch[bk])
    cfg = save_config(patch)
    return {"ok": True, "has_api_key": bool(_mv_key(cfg))}


@app.post("/api/leads/upload")
async def api_upload(files: list[UploadFile] = File(...)):
    cfg = load_config()
    all_rows: list[dict] = []
    names = []
    for f in files:
        raw = await f.read()
        (UPLOADS_DIR / f.filename).write_bytes(raw)
        all_rows.extend(_rows_from_csv_bytes(raw))
        names.append(f.filename)
    result = organize_mod.organize(all_rows, owned_companies=cfg.get("owned_companies"),
                                   owned_domains=cfg.get("owned_domains"),
                                   strict_status=bool(cfg.get("strict_status", True)))
    _attach_v7_fields(all_rows, result["firms"])
    payload = {"firms": result["firms"], "skipped": result["skipped"], "count": result["count"],
               "files": names, "rows_in": len(all_rows),
               "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(LEADS_FILE, payload)
    return _leads_view(payload)


@app.get("/api/leads")
def api_leads():
    return _leads_view(_read_json(LEADS_FILE, {}))


@app.post("/api/leads/clear")
def api_leads_clear():
    _write_json(LEADS_FILE, {})
    return {"ok": True}


@app.post("/api/run/start")
async def api_run_start(request: Request):
    body = await request.json()
    return JSONResponse(start_run(bool(body.get("test_mode", True))))


@app.get("/api/run/status")
def api_run_status(run_id: str = "", since: int = 0):
    snap = get_run(run_id, since) if run_id else latest_run(kind="run")
    return snap or {"status": "none"}


@app.post("/api/run/cancel")
async def api_run_cancel(request: Request):
    rid = (await request.json()).get("run_id")
    if rid in JOBS:
        JOBS[rid]["cancel"] = True
        return {"ok": True}
    return {"ok": False}


@app.get("/api/dashboard")
def api_dashboard(run_id: str = ""):
    snap = get_run(run_id) if run_id else latest_run(kind="run")
    if not snap:
        return {"status": "none"}
    results = snap.get("results", [])
    found = sum(1 for r in results if r.get("found_email"))
    iced = sum(1 for r in results if r.get("icebreaker"))
    status_counts = Counter(r.get("status", "") for r in results)
    pushed = sum(1 for r in results if r.get("pushed"))
    if not pushed:                        # enrichment runs don't push - take it from the ledger
        pushed = ledger_mod.Ledger(LEDGER_FILE).stats().get("pushed", 0)
    return {
        "run_id": snap.get("run_id"), "status": snap.get("status"), "when": snap.get("started"),
        "total": snap.get("total", 0), "processed": snap.get("processed", 0),
        "found": found, "verified": found, "pushed": pushed,
        "held": snap.get("counters", {}).get("held", 0),
        "credits": snap.get("credits"),
        "funnel": [
            {"label": "Organized", "value": snap.get("total", 0)},
            {"label": "Email found", "value": found},
            {"label": "Verified", "value": found},
            {"label": "Icebreaker", "value": iced},
            {"label": "Pushed", "value": pushed, "final": True},
        ],
        "status_breakdown": sorted(status_counts.items(), key=lambda kv: -kv[1]),
    }


def _results_csv(snap: dict) -> str:
    """Test-mode rows carry a SIMULATED column, because those addresses were generated
    from a name pattern and never checked against a mail server - mailing them would
    bounce and damage sending reputation."""
    sim = bool(snap.get("test_mode"))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow((["SIMULATED"] if sim else []) +
               ["Company", "Domain", "Selected Director", "Found Email", "Email Source",
                "Verification", "Status", "Ice Breaker", "Ice Style",
                "Oldest Director", "Director 2", "Director 3", "Phone", "City"])
    for r in snap.get("results", []):
        w.writerow((["NOT VERIFIED - test run"] if sim else []) +
                   [r.get("company"), r.get("domain"), r.get("selected_director"), r.get("found_email"),
                    r.get("email_source"), r.get("verification"), r.get("status"),
                    r.get("icebreaker"), r.get("ice_style"),
                    r.get("Oldest Director Name"), r.get("Director 2 Name"), r.get("Director 3 Name"),
                    r.get("phone"), r.get("city")])
    return buf.getvalue()


@app.get("/api/results")
def api_results(run_id: str = ""):
    snap = get_run(run_id) if run_id else latest_run(kind="run")
    return snap or {"status": "none"}


@app.get("/api/results/download")
def api_results_download(run_id: str = ""):
    snap = get_run(run_id) if run_id else latest_run(kind="run")
    if not snap:
        return PlainTextResponse("no results", status_code=404)
    prefix = "SIMULATED-" if snap.get("test_mode") else ""
    fname = f"{prefix}leads-{snap.get('run_id', 'run')}.csv"
    return Response(content=_results_csv(snap), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def _iter_run_meta():
    """(run_id, started) for the live jobs then recent files, newest first, de-duped."""
    seen = set()
    for j in sorted(JOBS.values(), key=lambda j: j["started"], reverse=True):
        seen.add(j["run_id"]); yield j["run_id"], j["started"], j
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for fp in files:
        rid = fp.stem
        if rid in seen:
            continue
        rec = _read_json(fp, None)
        yield rid, (rec or {}).get("started", ""), None


def _all_events(run_id: str = "", cap: int = LOG_SCAN_CAP) -> list[dict]:
    out = []
    for rid, started, job in _iter_run_meta():
        if run_id and rid != run_id:
            continue
        evs = list(job["events"]) if job else _read_events(rid)
        for e in reversed(evs):
            out.append({**e, "run_id": rid, "when": started})
            if len(out) >= cap:
                return out
    return out


@app.get("/api/log")
def api_log(filter: str = "all", search: str = "", run_id: str = "", limit: int = 300):
    events = _all_events(run_id)
    counts = Counter(e["status"] for e in events)
    fl = (filter or "all").lower()
    status_map = {"success": {"success"}, "failed": {"fail"}, "held": {"held"}, "skipped": {"skip"}}
    view = events
    if fl in status_map:
        view = [e for e in view if e["status"] in status_map[fl]]
    if search:
        s = search.lower()
        view = [e for e in view if s in (e.get("company", "") + " " + e.get("detail", "") + " " + e.get("email", "")).lower()]
    return {"events": view[:limit], "total": len(view), "scanned": len(events),
            "counts": {"success": counts.get("success", 0), "failed": counts.get("fail", 0),
                       "held": counts.get("held", 0), "skipped": counts.get("skip", 0)}}


@app.get("/api/log/download")
def api_log_download(run_id: str = ""):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Run", "When", "Time", "Company", "Stage", "Status", "Detail", "Email"])
    for e in _all_events(run_id, cap=1_000_000):
        w.writerow([e.get("run_id"), e.get("when"), e.get("ts"), e.get("company"),
                    e.get("stage"), e.get("status"), e.get("detail"), e.get("email")])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="event-log.csv"'})


@app.get("/api/history")
def api_history():
    return {"runs": _read_json(HISTORY_FILE, [])}


# ── Phase 3 endpoints ────────────────────────────────────────────────

@app.post("/api/sheets/load")
def api_sheets_load():
    try:
        return load_leads_from_sheet()
    except Exception as e:  # noqa: BLE001 - surface the reason to the UI
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/push/preview")
def api_push_preview(run_id: str = ""):
    """What a push would send - shown for confirmation BEFORE anything goes out.

    Campaign-aware: it previews the lane's OWN target id, its label table and its Instantly
    options, and it applies the same send gate the push does, so what you see here is
    exactly what would leave the machine."""
    cfg = load_config()
    snap = get_run(run_id) if run_id else latest_run(kind="run")
    if not snap:
        return {"status": "none", "ready": 0, "leads": []}

    camp, fm = None, None
    camp_id = str(snap.get("campaign") or "").strip()
    if camp_id:
        camp, fm = _campaign_and_fm(camp_id)

    found = [r for r in snap.get("results", []) if r.get("found_email")]
    found, already = _drop_already_pushed(found, fm, cfg, test_run=bool(snap.get("test_mode")))
    out = _push_preview(found, cfg, camp, fm)
    out.update({"run_id": snap.get("run_id"), "campaign": camp_id, "already_sent": already,
                "from_test": bool(snap.get("test_mode")),       # a free test's leads: dry run only
                "campaign_name": snap.get("campaign_name") or ""})
    return out


@app.get("/api/push/backlog/preview")
def api_backlog_preview(campaign: str = ""):
    """Everything a campaign found that never reached Instantly, across all its live runs."""
    camp, fm = _campaign_and_fm(campaign)
    if camp is None:
        return {"error": f"No campaign '{campaign}'.", "ready": 0, "leads": []}
    found, n_runs = campaign_backlog(camp.id, fm)
    out = _push_preview(found, load_config(), camp, fm)
    out.update({"campaign": camp.id, "campaign_name": camp.name, "runs": n_runs,
                "push_running": _push_running(camp.id)})
    return out


@app.post("/api/push/backlog/start")
async def api_backlog_start(request: Request):
    body = await request.json()
    return JSONResponse(start_backlog_push(str(body.get("campaign") or ""),
                                           test_mode=bool(body.get("test_mode", True)),
                                           confirm=bool(body.get("confirm", False))))


def _push_preview(found: list[dict], cfg: dict, camp, fm) -> dict:
    """The send gate + ice-breaker hold + the exact payloads, for any set of found leads."""
    labels = (camp.labels or None) if camp else None
    options = runner_mod.push_options(camp) if camp else None
    rows = _send_gate(found, cfg)
    send_ready = len(rows)
    unchecked = sum(1 for r in rows if str(r.get("verification") or "").strip().lower() == UNCHECKED_SHEET)
    waiting, ib_note = [], ""
    if camp is not None:
        rows, waiting, ib_note = _lane_icebreakers(cfg, camp, fm, rows)
    campaign = (camp.instantly_campaign_id if camp else "") or \
        str(cfg.get("instantly_campaign_id", "")).strip()
    return {
        "ready": len(rows), "unchecked": unchecked,
        "found": len(found), "held_not_send_ready": len(found) - send_ready,
        "waiting_icebreaker": len(waiting), "icebreaker_note": ib_note,
        "waiting_companies": [r.get("company", "") for r in waiting[:25]],
        "has_key": bool(str(cfg.get("instantly_api_key", "")).strip()),
        "campaign_id": campaign, "delay": cfg.get("push_delay_seconds", 3),
        "writeback": bool(cfg.get("sheet_writeback")),
        "leads": [instantly_mod.build_payload(
            runner_mod.label_source_row(r) if camp else r,
            campaign or "<campaign id not set>",
            labels=labels, fm=fm, options=options) for r in rows[:25]],
    }


@app.post("/api/push/start")
async def api_push_start(request: Request):
    body = await request.json()
    return JSONResponse(start_push(body.get("run_id", ""),
                                   test_mode=bool(body.get("test_mode", True)),
                                   confirm=bool(body.get("confirm", False))))


@app.get("/api/ledger")
def api_ledger():
    led = ledger_mod.Ledger(LEDGER_FILE)
    s = led.stats()
    s["recent"] = led.recent(25)
    return s


@app.post("/api/ledger/clear")
def api_ledger_clear():
    ledger_mod.Ledger(LEDGER_FILE).clear()
    return {"ok": True}


@app.get("/api/icebreaker")
def api_icebreaker_get():
    cfg = load_config()
    saved = cfg.get("icebreaker_templates") or {}
    return {"defaults": icebreaker_mod.DEFAULT_TEMPLATES,
            "templates": {**icebreaker_mod.DEFAULT_TEMPLATES, **saved},
            "customised": sorted(k for k, v in saved.items()
                                 if str(v).strip() != icebreaker_mod.DEFAULT_TEMPLATES.get(k, "")),
            "placeholders": sorted(icebreaker_mod.PLACEHOLDERS)}


@app.post("/api/icebreaker/preview")
async def api_icebreaker_preview(request: Request):
    b = await request.json()
    templates = b.get("templates") or {}
    problems = icebreaker_mod.validate_templates({**icebreaker_mod.DEFAULT_TEMPLATES, **templates})
    firms = _read_json(LEADS_FILE, {}).get("firms", [])
    samples = firms[:5] or [{"Company Name": "Smith & Co", "lead_director": "Ian Smith"}]
    out = []
    for mode, extra in (("offer", {}),
                        ("delivered", {"audit_mode": "delivered",
                                       "audit_opener_data": b.get("sample_finding") or "your site is slow to load on mobile"}),
                        ("clean", {"audit_mode": "clean", "audit_perf_score": "95"})):
        for f in samples[:3] if mode == "offer" else samples[:1]:
            ib = icebreaker_mod.build({**f, **extra}, f.get("found_email", ""), templates)
            out.append({"mode": mode, "style": ib["style"],
                        "company": f.get("Company Name", ""), "text": ib["text"]})
    return {"problems": problems, "previews": out}


@app.post("/api/icebreaker")
async def api_icebreaker_save(request: Request):
    b = await request.json()
    templates = {k: str(v) for k, v in (b.get("templates") or {}).items()
                 if k in icebreaker_mod.DEFAULT_TEMPLATES}
    problems = icebreaker_mod.validate_templates({**icebreaker_mod.DEFAULT_TEMPLATES, **templates})
    if problems:
        return JSONResponse({"ok": False, "problems": problems}, status_code=400)
    save_config({"icebreaker_templates": templates})
    return {"ok": True}


@app.post("/api/icebreaker/reset")
def api_icebreaker_reset():
    save_config({"icebreaker_templates": {}})
    return {"ok": True, "templates": icebreaker_mod.DEFAULT_TEMPLATES}


@app.get("/api/schedule")
def api_schedule():
    return schedule_status()


@app.post("/api/schedule/create")
async def api_schedule_create(request: Request):
    b = await request.json()
    return schedule_create(every_minutes=int(b.get("every", b.get("every_minutes", 30)) or 30),
                           start=str(b.get("start", "08:00")), end=str(b.get("end", "17:30")),
                           test_mode=bool(b.get("test_mode", True)),
                           from_sheet=bool(b.get("from_sheet", False)),
                           push=bool(b.get("push", False)),
                           kind=str(b.get("kind", "minute")),
                           days=b.get("days") or [])


@app.post("/api/schedule/delete")
def api_schedule_delete():
    return schedule_delete()


# ── campaigns ────────────────────────────────────────────────────────

@app.get("/api/campaigns")
def api_campaigns():
    return campaigns_view()


@app.get("/api/plan")
def api_plan(all: bool = False):
    """The free preview. Reads the sheet and applies the rules; spends nothing."""
    return build_plan(enabled_only=not all)


@app.get("/api/fieldmap")
def api_fieldmap(tab: str = ""):
    """Validate a tab's field map against the sheet's real header, before any spend."""
    cfg = load_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    lane = next((c for c in loaded["campaigns"] if not tab or c.tab == tab), None)
    if not lane:
        return {"error": f"No campaign uses tab '{tab}'."}
    cfg = cfg_for_campaign(cfg, lane)
    try:
        rows = _read_tab_for_display(cfg, lane.tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read tab '{lane.tab}': {e}"}
    heads = runner_mod.headers_of(rows)
    fm = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], heads)
    out = runner_mod.check_fieldmap(fm, heads)
    out.update({"tab": lane.tab, "rows": len(rows), "mapping": fm.to_dict()})
    return out


@app.get("/api/campaigns/detail")
def api_campaign_detail(id: str):
    """The raw config for one campaign — what the editor drawer loads."""
    body = _read_campaigns_raw()
    row = next((c for c in (body.get("campaigns") or []) if str(c.get("id")) == id), None)
    if row is None:
        return {"error": f"No campaign '{id}'."}
    c = campaigns_mod.Campaign(row)
    return {"campaign": row, "issues": campaigns_mod.validate([c], recipes=recipe_mod.load_dir(RECIPES_DIR)),
            "label_issues": instantly_mod.validate_label_specs(c.labels or None),
            "operators": sorted(rules_mod.OPS), "value_less": sorted(rules_mod.VALUE_LESS),
            "derived": sorted(instantly_mod.DERIVED), "label_types": list(instantly_mod.LABEL_TYPES)}


@app.post("/api/campaigns/save")
async def api_campaign_save(request: Request):
    return save_campaign(await request.json())


@app.post("/api/campaigns/globals")
async def api_campaign_globals(request: Request):
    return save_globals(await request.json())


@app.post("/api/campaigns/create")
async def api_campaign_create(request: Request):
    return create_campaign(await request.json())


@app.post("/api/campaigns/delete")
async def api_campaign_delete(request: Request):
    return delete_campaign(str((await request.json()).get("id") or ""))


@app.get("/api/fieldmap/detail")
def api_fieldmap_detail(tab: str = ""):
    return fieldmap_detail(tab)


@app.post("/api/fieldmap/save")
async def api_fieldmap_save(request: Request):
    b = await request.json()
    return save_fieldmap(str(b.get("file") or ""), b.get("mapping") or {})


@app.get("/api/campaigns/schedule")
def api_campaign_schedule(id: str):
    camp = next((c for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"] if c.id == id), None)
    if camp is None:
        return {"error": f"No campaign '{id}'."}
    view = lane_schedule_view(camp)
    view["windows_available"] = windows_available()
    view["task"] = lane_task_status(id) if view["schedule"]["via"] == "windows" else {"exists": False}
    return view


@app.post("/api/campaigns/schedule")
async def api_campaign_schedule_save(request: Request):
    b = await request.json()
    return save_lane_schedule(str(b.get("id") or ""), b.get("schedule") or {})


# ── V5 screens: dropdowns, connection tests, live counts, readiness, order ──

def sheet_info(cfg: dict | None = None) -> dict:
    """The Google Sheet's title and tab names (one metadata read). Without a service-account
    file the link-export route cannot list tabs, so the tabs the campaigns use are offered."""
    cfg = cfg or load_config()
    used = sorted({c.tab for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
                   if c.tab and not imports_mod.is_import_tab(c.tab)})
    parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
    if not parsed["doc_id"]:
        return {"ok": False, "detail": "no Google Sheet link saved yet", "title": "", "tabs": used}
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if not sa:
        return {"ok": False, "detail": "add the Google key file to list every tab", "title": "", "tabs": used}
    try:
        info = sheets_mod.SheetsClient(sa).info(parsed["doc_id"])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"could not open the sheet: {e}", "title": "", "tabs": used}
    n = len(info["tabs"])
    return {"ok": True, "detail": f"“{info['title']}” · {n} tab{'s' if n != 1 else ''}", **info}


def test_connection(service: str) -> dict:
    """One free read per service; never spends a credit."""
    cfg = load_config()
    if service == "sheet":
        r = sheet_info(cfg)
        return {"ok": r["ok"], "detail": r["detail"]}
    if service == "millionverifier":
        return conn_mod.test_millionverifier(_mv_key(cfg))
    if service == "instantly":
        return conn_mod.test_instantly(str(cfg.get("instantly_api_key") or "").strip())
    if service == "anymailfinder":
        return conn_mod.test_anymailfinder(str(cfg.get("anymailfinder_api_key") or "").strip())
    if service == "openai":
        return conn_mod.test_openai(str(cfg.get("openai_api_key") or "").strip())
    if service == "icypeas":
        has = bool(str(cfg.get("icypeas_api_key") or "").strip())
        return {"ok": None, "detail": ("saved — Icypeas has no free test; a refused key shows up in "
                                       "Activity after its first lookup") if has else "no Icypeas key saved yet"}
    return {"ok": False, "detail": f"unknown service '{service}'"}


def _fieldmap_for_raw(camp, loaded: dict, heads: list[str]):
    if camp.fieldmap and camp.fieldmap not in loaded["fieldmaps"]:
        # a new campaign can name a map file no saved campaign has loaded yet
        loaded["fieldmaps"][camp.fieldmap] = fieldmap_mod.load(CONFIG_DIR / camp.fieldmap)
    return runner_mod.fieldmap_for(camp, loaded["fieldmaps"], heads)


def campaign_preview(raw: dict) -> dict:
    """Live counts for a campaign as it stands on screen, saved or not. Free: reads the source
    and applies the filters, nothing more. Other campaigns higher in the order may still claim
    some of these rows; the Campaigns list shows the split."""
    camp = campaigns_mod.Campaign(raw or {})
    if not camp.tab:
        return {"error": "Choose a lead source first."}
    problems = rules_mod.validate_rules(camp.rules)
    if problems:
        return {"error": "A filter is not finished: " + "; ".join(problems)}
    cfg = cfg_for_campaign(load_config(), camp)
    try:
        rows = _read_tab_for_display(cfg, camp.tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read '{camp.tab}': {e}"}
    heads = runner_mod.headers_of(rows)
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    fm = _fieldmap_for_raw(camp, loaded, heads)
    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
    prep = runner_mod.prepare(camp, rows, fm, ledger=led, cfg=cfg)
    rate = float(cfg.get("mv_per_verification_usd", 0) or 0)
    return {"rows": len(rows), "matched": prep["matched"], "not_contacted": prep["available"],
            "done_before": prep["blocked_by_ledger"], "take": prep["selected"],
            "day_remaining": prep["day_remaining"], "per_run": camp.per_run,
            # the same estimate the plan uses: about 2 checks a lead
            "est_cost_per_run": round(camp.per_run * 2 * rate, 2),
            "est_cost_per_day": round((camp.per_day or camp.per_run) * 2 * rate, 2)}


def campaign_readiness(cid: str) -> dict:
    """The "Ready to go live" checklist. Each item says what to fix and which section fixes it."""
    cfg = load_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == cid), None)
    if camp is None:
        return {"error": f"No campaign '{cid}'."}
    cfg = cfg_for_campaign(cfg, camp)
    items = []

    def add(ok, text, fix=""):
        items.append({"ok": bool(ok), "text": text, "fix": "" if ok else fix})

    problems = [i["issue"] for i in campaigns_mod.validate([camp], recipes=recipe_mod.load_dir(RECIPES_DIR))]
    # a recipe problem is fixed in the Finding-recipe step, not in Who — point Fix there
    where = "finding" if any("recipe" in p for p in problems) else "who"
    add(not problems, "Settings are complete" if not problems else "Settings problem: " + "; ".join(problems), where)
    if _is_pipeline(camp):
        return _pipeline_readiness(camp, cfg, items, add)
    try:
        rows = _read_tab_for_display(cfg, camp.tab)
        heads = runner_mod.headers_of(rows)
        fm = _fieldmap_for_raw(camp, loaded, heads)
        check = runner_mod.check_fieldmap(fm, heads)
        led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
        prep = runner_mod.prepare(camp, rows, fm, ledger=led, cfg=cfg)
        add(prep["available"] > 0, f"Leads to work on: {prep['available']:,} fit the filters and were never contacted"
            if prep["available"] else "No leads left that fit the filters", "who")
        add(check["ok"], "Every column it needs is matched" if check["ok"]
            else "Column matching: " + "; ".join(check["blocking"]), "columns")
    except Exception as e:  # noqa: BLE001
        add(False, f"The lead source could not be read: {e}", "who")
    hist = _read_json(HISTORY_FILE, [])
    tested = any(h.get("campaign") == cid and h.get("kind", "run") == "run" and h.get("status") == "finished"
                 for h in hist)
    add(tested, "A test run finished" if tested else "No test run yet — run a free test first", "test")
    add(bool(_mv_key(cfg)), "Email checking (MillionVerifier) is connected" if _mv_key(cfg)
        else "Email checking is not connected", "settings")
    has_key = bool(str(cfg.get("instantly_api_key") or "").strip())
    add(has_key, "Instantly is connected" if has_key else "Instantly is not connected", "settings")
    add(bool(camp.instantly_campaign_id), "Instantly campaign chosen" if camp.instantly_campaign_id
        else "No Instantly campaign chosen", "send")
    add(camp.enabled, "Campaign is switched on" if camp.enabled else "Campaign is switched off", "on")
    return {"campaign": cid, "items": items, "done": sum(i["ok"] for i in items), "total": len(items)}


def _pipeline_readiness(camp, cfg, items, add) -> dict:
    """The checklist for a 6-step campaign: no free test (it has none), but a live template."""
    try:
        p, st = _stack_parts(f"campaign:{camp.id}"), _stack_store()
        rows = _campaign_filter(camp, st.overlay(p["rows"], p["store_source"], p["fm"].header("row_key") or "lead_id"),
                                p["fm"])
        new = sum(1 for r in rows if not r.get("email_status"))
        add(new > 0, f"Leads to work on: {new:,} fit the filters and were never searched" if new
            else "No new leads left that fit the filters", "who")
        # the pipeline only READS the sheet (results stay in the app), so only the columns it
        # reads matter here, not where the old engine would write
        missing = p["fm"].validate(p["headers"])["missing_required"]
        add(not missing, "Every column it reads is matched" if not missing
            else "Column matching: no column for " + ", ".join(missing), "columns")
        live = tpl_mod.live(st, p["store_source"])
        add(bool(live), "An email template is live" if live
            else "No email template is live yet", "template")
    except Exception as e:  # noqa: BLE001
        add(False, f"The lead source could not be read: {e}", "who")
    add(bool(_mv_key(cfg)), "Email checking (MillionVerifier) is connected" if _mv_key(cfg)
        else "Email checking is not connected", "settings")
    has_key = bool(str(cfg.get("instantly_api_key") or "").strip())
    add(has_key, "Instantly is connected" if has_key else "Instantly is not connected", "settings")
    add(bool(camp.instantly_campaign_id), "Instantly campaign chosen" if camp.instantly_campaign_id
        else "No Instantly campaign chosen", "send")
    add(camp.enabled, "Campaign is switched on" if camp.enabled else "Campaign is switched off", "on")
    return {"campaign": camp.id, "items": items, "done": sum(i["ok"] for i in items), "total": len(items),
            "pipeline": True}


def pipeline_steps(cid: str) -> dict:
    """The campaign page's "The 6 steps" card: each step, the setting it uses, where to change it."""
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == cid), None)
    if camp is None or not _is_pipeline(camp):
        return {"error": "This campaign is not in the 6-step pipeline."}
    src = f"campaign:{camp.id}"
    q = f"?source={src}"
    try:
        p, st = _stack_parts(src), _stack_store()
        rs = _demo_ruleset(st, p)
        live = tpl_mod.live(st, p["store_source"])
        rec_name = (p["recipe"] or {}).get("name") or camp.recipe or "none"
        rungs = len(rs.get("rungs") or [])
        tpl = (f"{len(live)} template{'s' if len(live) != 1 else ''} live" if live else "no template live yet")
    except Exception as e:  # noqa: BLE001
        return {"error": f"The lead source could not be read: {e}"}
    room = f"{camp.per_run} new leads per run" + (f", at most {camp.per_day} a day" if camp.per_day else "")
    s, _ = schedules_mod.normalize(camp.schedule)
    when = (schedules_mod.summary(s) if s.get("enabled") and camp.enabled
            else "Runs only when you press Run now (“Run by itself” is off)" if not s.get("enabled")
            else "Its schedule is set, but the campaign is switched off")
    steps = [
        ("find", "Find email", f"{room} · recipe “{rec_name}”. A lead with an email in the sheet is used as it is.", "/find" + q),
        ("research", "Website research", "Only leads that got an email. Skipped when the sheet already has an ice breaker.", "/research" + q),
        # these two pages open one campaign with ?open= (not ?source=)
        ("ice", "Ice breakers", f"Rule set “{rs.get('name', '')}” ({rungs} rules, then the Default line). A sheet ice breaker is used as it is.", f"/ice?open={src}"),
        ("email", "Email template", f"{tpl} · scored against the copy rules", f"/email?open={src}"),
        ("send", "Sending", "Adds each ready lead to the Instantly campaign below, only while it is Draft or Paused"
         + ("; then Found Email, Ice Breaker and Status are written to your sheet"
            if (camp.writeback or {}).get("enabled") is not False else "; your sheet is not updated (switch off)"),
         "/send" + q),
        ("replies", "Replies", "Reads replies from that Instantly campaign", "/replies" + q),
    ]
    return {"campaign": camp.id, "source": src, "when": when,
            "steps": [{"key": k, "title": t, "setting": d, "href": h} for k, t, d, h in steps]}


def sheet_writeback(source: str) -> dict:
    """A 6-step campaign's results → its own Google Sheet (Found Email, Ice Breaker, Status).
    Empty cells only (Status: also over its own earlier words). Off when the campaign's
    "Update my Google Sheet" switch is off."""
    p = _stack_parts(source)
    camp = p.get("camp")
    if p["demo"] or camp is None or not _is_pipeline(camp):
        return {"ok": False, "error": "Only a 6-step campaign writes back to its sheet."}
    if (camp.writeback or {}).get("enabled") is False:
        return {"ok": True, "cells": 0, "off": True}
    cfg = cfg_for_campaign(load_config(), camp)
    if not tab_source(cfg, camp.tab).get("live"):        # an uploaded file or local CSV: no sheet
        return {"ok": True, "cells": 0, "off": True}
    parsed = sheets_mod.parse_sheet_url(str(cfg.get("sheet_url") or ""))
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if not parsed["doc_id"] or not sa:
        return {"ok": False, "error": "The sheet is not connected for writing (Settings → Connections)."}
    try:
        r = swb_mod.apply(sheets_mod.SheetsClient(sa), parsed["doc_id"], camp.tab, p["fm"], _stack_store(),
                          p["store_source"])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"The sheet was not updated: {str(e)[:200]}"}
    _TAB_CACHE.clear()               # the screens read the new cells, not a minute-old copy
    return r


def reorder_campaigns(ids: list[str]) -> dict:
    """The Campaigns list's drag order becomes priority: first = 10, then 20, 30 … A lane not
    named keeps its place after the named ones."""
    body = _read_campaigns_raw()
    rows = body.get("campaigns") or []
    known = {str(c.get("id")) for c in rows}
    order = [i for i in ids if i in known]
    if len(set(order)) != len(order) or not order:
        return {"ok": False, "issues": [{"campaign": "", "issue": "the order must name each campaign once"}]}
    rest = [str(c.get("id")) for c in sorted(rows, key=lambda c: int(c.get("priority", 100) or 0))
            if str(c.get("id")) not in order]
    prio = {cid: (n + 1) * 10 for n, cid in enumerate(order + rest)}
    for c in rows:
        c["priority"] = prio[str(c.get("id"))]
    body["campaigns"] = rows
    return _write_campaigns_raw(body)


def schedule_preview(raw: dict, *, now: datetime | None = None, count: int = 3) -> dict:
    """A schedule as it stands on screen: its sentence, its problems, its next few runs — from
    the same code the clock uses, so the screen can never promise a time the clock won't keep."""
    s, problems = schedules_mod.normalize(raw)
    if s["via"] == "windows" and not windows_available():
        problems.append("this engine is not running on Windows — choose the app")
    nxt, t = [], now or datetime.now()
    if not problems:
        for _ in range(count):
            slot = schedules_mod.next_after(s, t)
            if slot is None:
                break
            nxt.append(slot.strftime("%Y-%m-%d %H:%M"))
            t = slot
    return {"summary": schedules_mod.summary(s), "problems": problems, "next": nxt, "schedule": s,
            "windows_available": windows_available()}


@app.post("/api/schedules/preview")
async def api_schedule_preview(request: Request):
    return schedule_preview(await request.json())


@app.get("/api/sheets/info")
def api_sheet_info():
    return sheet_info()


@app.get("/api/instantly/options")
def api_instantly_options():
    return conn_mod.instantly_options(str(load_config().get("instantly_api_key") or "").strip())


@app.post("/api/connections/test")
async def api_connection_test(request: Request):
    return test_connection(str((await request.json()).get("service") or ""))


@app.post("/api/campaigns/preview")
async def api_campaign_preview(request: Request):
    return campaign_preview(await request.json())


@app.get("/api/campaigns/readiness")
def api_campaign_readiness(id: str):
    return campaign_readiness(id)


@app.get("/api/campaigns/pipeline_steps")
def api_campaign_pipeline_steps(id: str):
    return pipeline_steps(id)


@app.post("/api/campaigns/sheet_writeback")
async def api_campaign_sheet_writeback(request: Request):
    b = await request.json()
    return sheet_writeback(f"campaign:{str(b.get('id') or '')}")


@app.post("/api/campaigns/reorder")
async def api_campaign_reorder(request: Request):
    return reorder_campaigns([str(i) for i in ((await request.json()).get("ids") or [])])


# ── V6: Finding Recipes — who to email, in what order (docs/RECIPE-BUILDER.md) ──
#
# A recipe is a shared library file, not a campaign setting: one recipe serves the 5 CH
# tabs. A campaign stores only its id, so editing a recipe changes every lane that uses
# it — which is the point, and why `delete` refuses while a lane still points at it.

def _recipe_users(rid: str, campaigns=None) -> list[dict]:
    """Which campaigns use this recipe. Deleting one is refused while this is not empty."""
    camps = campaigns if campaigns is not None else runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
    return [{"id": c.id, "name": c.name, "enabled": c.enabled} for c in camps if c.recipe == rid]


def recipes_view() -> dict:
    """Every saved recipe: who uses it, when it changed, and any problem with it."""
    recipes = recipe_mod.load_dir(RECIPES_DIR)
    camps = runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
    out = []
    for rid, r in sorted(recipes.items(), key=lambda kv: kv[1].name.lower()):
        out.append({
            "id": rid, "name": r.name, "note": r.note, "updated": r.updated,
            "people": [{"label": p.label, "name_from": p.name_from,
                        "name_pick": p.name_pick, "address_from": p.address_from,
                        "only_if_same_as": p.only_if_same_as,
                        "how": [w.method for w in p.how]} for p in r.people],
            "write_columns": r.write_columns(),
            "stop_when": r.stop_when, "last_resort": r.last_resort,
            "issues": recipe_mod.validate(r),
            "used_by": _recipe_users(rid, camps),
        })
    # a campaign pointing at a recipe that is gone: say so here, not mid-run
    missing = sorted({c.recipe for c in camps if c.recipe and c.recipe not in recipes})
    return {"recipes": out, "missing": missing,
            "methods": recipe_mod.METHODS, "pattern_modes": list(recipe_mod.PATTERN_MODES),
            "verify_modes": recipe_mod.VERIFY_MODES, "stop_options": recipe_mod.STOP_WHEN,
            "write_options": recipe_mod.WRITE_WHEN,
            "operators": sorted(rules_mod.OPS), "value_less": sorted(rules_mod.VALUE_LESS)}


def recipe_detail(rid: str) -> dict:
    """One recipe, plus the columns of every tab a campaign using it reads, so the editor's
    dropdowns offer real headers and can show a real example from his sheet."""
    r = recipe_mod.load(RECIPES_DIR / f"{rid}.json")
    if r is None:
        return {"error": f"There is no recipe '{rid}'."}
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camps = loaded["campaigns"]
    users = _recipe_users(rid, camps)
    headers: list[str] = []
    sample: dict = {}
    resolved: dict = {}
    tab = ""
    if users:
        lane = next((c for c in camps if c.recipe == rid), None)
        cfg = cfg_for_campaign(load_config(), lane)
        tab = lane.tab if lane else ""
        try:
            rows = _read_tab_for_display(cfg, tab)
            headers = runner_mod.headers_of(rows)
            sample = rows[0] if rows else {}
            # engine field -> this sheet's real header, so the editor can show a real
            # example ("Ian Smith → ian.smith@smithco.co.uk") instead of a made-up one
            resolved = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], headers).to_dict()
        except Exception:  # noqa: BLE001 — the editor still works with no sheet
            headers = []
    check = recipe_mod.check_against_sheet(r, headers) if headers else \
        {"ok": True, "blocking": [], "warnings": [], "missing_read": [], "missing_write": []}
    return {"recipe": r.to_dict(), "used_by": users, "tab": tab, "headers": headers,
            "sample": sample, "resolved": resolved, "sheet_check": check,
            "issues": recipe_mod.validate(r)}


def save_recipe(raw: dict) -> dict:
    """Validate, then write one recipe file. Nothing is saved while a problem remains."""
    raw = dict(raw or {})
    if not str(raw.get("name") or "").strip():
        return {"ok": False, "issues": ["give the recipe a name"]}
    rid = str(raw.get("id") or "").strip() or recipe_mod.slug(raw.get("name") or "")
    raw["id"] = rid
    issues = recipe_mod.validate(raw)
    if issues:
        return {"ok": False, "issues": issues}
    try:
        recipe_mod.save(RECIPES_DIR, raw, today=datetime.now().strftime("%Y-%m-%d"))
    except (ValueError, OSError) as e:
        return {"ok": False, "issues": [str(e)]}
    return {"ok": True, "id": rid, "used_by": _recipe_users(rid)}


def create_recipe(name: str, copy_from: str = "") -> dict:
    """A new recipe, blank or copied. A copy never takes the original's id."""
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "issues": ["give the recipe a name"]}
    rid = recipe_mod.slug(name)
    if (RECIPES_DIR / f"{rid}.json").exists():
        return {"ok": False, "issues": [f"there is already a recipe called '{name}'"]}
    if copy_from:
        src = recipe_mod.load(RECIPES_DIR / f"{copy_from}.json")
        if src is None:
            return {"ok": False, "issues": [f"there is no recipe '{copy_from}' to copy"]}
        raw = json.loads(json.dumps(src.to_dict()))
        raw["note"] = (src.note + " (copy)").strip()
    else:
        raw = recipe_mod.blank(name)
    raw.update({"id": rid, "name": name})
    try:
        recipe_mod.save(RECIPES_DIR, raw, today=datetime.now().strftime("%Y-%m-%d"))
    except (ValueError, OSError) as e:
        return {"ok": False, "issues": [str(e)]}
    return {"ok": True, "id": rid}


def delete_recipe(rid: str) -> dict:
    """Refused while any campaign still uses it — otherwise that lane would silently fall
    back to the app's own order on its next run."""
    users = _recipe_users(rid)
    if users:
        names = ", ".join(u["name"] or u["id"] for u in users)
        return {"ok": False, "issues": [f"'{rid}' is still used by {names}. Point those "
                                        "campaigns at another recipe first."]}
    p = RECIPES_DIR / f"{rid}.json"
    if not p.exists():
        return {"ok": False, "issues": [f"there is no recipe '{rid}'"]}
    p.unlink()
    return {"ok": True}


def try_recipe(raw: dict, tab: str = "", limit: int = 10) -> dict:
    """"Try on 10 rows" — FREE. No key is used, no credit is spent, nothing is written.

    It runs the same `plan_for_row` the real run uses, so what this shows is what would
    happen. The credit numbers are a CEILING: Icypeas charges only when it finds somebody,
    and a run stops at the first address that passes."""
    rec = recipe_mod.Recipe(raw or {})
    issues = recipe_mod.validate(rec)
    if issues:
        return {"error": "Fix these first: " + "; ".join(issues)}
    tab = str(tab or "")
    if not tab.strip():
        return {"error": "No lead source to try this on. Point a campaign at this recipe "
                         "first, or choose a source."}
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    lane = next((c for c in loaded["campaigns"] if c.tab == tab), None)
    cfg = cfg_for_campaign(load_config(), lane)
    try:
        rows = _read_tab_for_display(cfg, tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read '{tab}': {e}"}
    if not rows:
        return {"error": f"'{tab}' has no rows."}

    heads = runner_mod.headers_of(rows)
    fm = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], heads) if lane else \
        fieldmap_mod.FieldMap({}).completed(heads)
    sheet_check = recipe_mod.check_against_sheet(rec, heads)

    # the rows this lane would actually take next, so the preview is not a random sample
    take = max(1, min(int(limit or 10), 50))
    picked = rows
    if lane is not None:
        matched = [r for r in rows if rules_mod.match(r, lane.rules, fm)[0]]
        picked = rules_mod.sort_rows(matched, lane.order, fm) or matched or rows

    out, checks, credits = [], 0, 0
    for row in picked[:take]:
        org = organize_mod.organize([row], fm=fm, keep_raw=True)
        firm = (org["firms"] or [{}])[0]
        plan = recipe_mod.plan_for_row(rec, row, firm, fm)
        est = recipe_mod.estimate_row(plan)
        checks += est["max_checks"]
        credits += est["max_icypeas_credits"]
        out.append({
            "lead_id": fm.get(row, "row_key"),
            "company": fm.get(row, "company_name") or firm.get("Company Name", ""),
            "website": firm.get("lead_domain", ""),
            "skip": plan["skip"], "why": plan["skip_reason"],
            "people": [{
                "label": p["label"], "name": p["name"], "from": p["name_column"],
                "address": p["address"],
                "ways": [{"method": w["method"], "ok": w["ok"], "why": w["why"],
                          "verify": w["verify"]} for w in p["ways"]],
            } for p in plan["people"]],
            "dropped": plan["dropped"],
            "max_checks": est["max_checks"], "max_credits": est["max_icypeas_credits"],
        })

    usable = [r for r in out if r["people"]]
    mv_rate = float(cfg.get("mv_per_verification_usd", 0.0) or 0)
    ic_rate = float(cfg.get("icypeas_usd_per_credit", 0.0) or 0)
    return {
        "tab": tab, "rows": out, "tried": len(out), "rows_in_tab": len(rows),
        "with_someone": len(usable), "with_nobody": len(out) - len(usable),
        "max_checks": checks, "max_credits": credits,
        "max_cost_usd": round(checks * mv_rate + credits * ic_rate, 4),
        "sheet_check": sheet_check,
        "note": "A ceiling, not a bill: a run stops at the first address that passes, and "
                "Icypeas charges only when it finds somebody.",
    }


@app.get("/api/recipes")
def api_recipes():
    return recipes_view()


@app.get("/api/recipes/detail")
def api_recipe_detail(id: str):
    return recipe_detail(id)


@app.post("/api/recipes/save")
async def api_recipe_save(request: Request):
    return save_recipe((await request.json()).get("recipe") or {})


@app.post("/api/recipes/create")
async def api_recipe_create(request: Request):
    b = await request.json()
    return create_recipe(str(b.get("name") or ""), str(b.get("copy_from") or ""))


@app.post("/api/recipes/delete")
async def api_recipe_delete(request: Request):
    return delete_recipe(str((await request.json()).get("id") or ""))


@app.post("/api/recipes/preview")
async def api_recipe_preview(request: Request):
    b = await request.json()
    return try_recipe(b.get("recipe") or {}, str(b.get("tab") or ""), int(b.get("limit") or 10))


# ── import: a CSV becomes a tab a lane can read (V4 F) ───────────────

def _lanes_reading(tab: str) -> list[dict]:
    return [{"id": c.id, "name": c.name, "enabled": c.enabled}
            for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"] if c.tab == tab]


def import_preview(tab: str, campaign: str = "") -> dict:
    """Any tab — an upload or a sheet tab by name — with its first rows and what a lane would
    find in it: duplicates, suppressed firms, leads the ledger already handled. Free.

    `campaign` (an id) says whose tab this is. A lane may name its own spreadsheet, so the tab
    is read from THAT sheet, exactly as the run reads it (`cfg_for_campaign`)."""
    # never strip: a tab may really end in a space ("Construction " in the Northwind sheet)
    tab = str(tab or "")
    if not tab.strip():
        return {"error": "Give a tab name."}
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    lane = next((c for c in loaded["campaigns"] if campaign and c.id == campaign), None) \
        or next((c for c in loaded["campaigns"] if c.tab == tab), None)
    cfg = cfg_for_campaign(load_config(), lane)
    try:
        rows = _read_tab_for_display(cfg, tab)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read '{tab}': {e}"}
    heads = runner_mod.headers_of(rows)
    fm = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], heads) if lane else \
        fieldmap_mod.FieldMap({}).completed(heads)
    led = ledger_mod.Ledger(LEDGER_FILE) if cfg.get("use_ledger", True) else None
    st = imports_mod.stats(rows, owned_companies=cfg.get("owned_companies"),
                           owned_domains=cfg.get("owned_domains"), ledger=led, fm=fm,
                           retry_not_found=bool(cfg.get("retry_not_found", False)))
    meta = imports_mod.load_index(IMPORTS_DIR).get(tab[len(imports_mod.PREFIX):]) \
        if imports_mod.is_import_tab(tab) else None
    return {"tab": tab, "source": tab_source(cfg, tab), "import": meta, "headers": heads,
            "sample": rows[:10], "stats": st, "check": runner_mod.check_fieldmap(fm, heads),
            "lanes": _lanes_reading(tab),
            "hold_without_icebreaker": bool(cfg.get("hold_without_icebreaker", True))}


@app.get("/api/imports")
def api_imports():
    lanes = runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
    out = []
    for rec in sorted(imports_mod.load_index(IMPORTS_DIR).values(),
                      key=lambda r: r.get("uploaded", ""), reverse=True):
        out.append({**rec, "fieldmap": import_fieldmap_file(rec["tab"]), "lanes": [{"id": c.id, "name": c.name, "enabled": c.enabled}
                                     for c in lanes if c.tab == rec["tab"]]})
    sheet_tabs = sorted({c.tab for c in lanes if c.tab and not imports_mod.is_import_tab(c.tab)})
    return {"imports": out, "sheet_tabs": sheet_tabs}


@app.post("/api/imports/upload")
async def api_imports_upload(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        rec = imports_mod.save_upload(IMPORTS_DIR, file.filename or "upload.csv", raw)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True, "import": rec}


@app.get("/api/imports/preview")
def api_imports_preview(tab: str = "", campaign: str = ""):
    return import_preview(tab, campaign)


@app.post("/api/imports/delete")
async def api_imports_delete(request: Request):
    b = await request.json()
    slug = str(b.get("slug") or "").strip()
    users = _lanes_reading(imports_mod.PREFIX + slug)
    if users:
        return {"ok": False, "error": "Campaigns still read this file: "
                + ", ".join(u["name"] for u in users) + ". Delete them or point them at another tab first."}
    rec = imports_mod.remove(IMPORTS_DIR, slug, delete_file=bool(b.get("delete_file", False)))
    if rec is None:
        return {"ok": False, "error": f"No import '{slug}'."}
    return {"ok": True, "removed": rec["name"]}


@app.post("/api/campaign/run")
async def api_campaign_run(request: Request):
    b = await request.json()
    return start_campaign_run(str(b.get("campaign") or ""),
                              test_mode=bool(b.get("test_mode", True)))


# ── the full stack, build session 1: Lead sources, Leads, Website research, Find email ──
# Screens read through core/stack_view.py. Only the demo (12 fake firms, stand-in services,
# $0) can RUN a step in this version; a live sheet or an uploaded file is listed and read,
# never written. Nothing here adds a column to any sheet.

from core import store as store_mod          # noqa: E402
from core import stack_view as stack_mod     # noqa: E402
from core import demo_services as demo_mod   # noqa: E402
from core import live_services as live_mod   # noqa: E402
from core import privacy as privacy_mod   # noqa: E402
from core import research as research_mod    # noqa: E402
from core import find_email as find_email_mod  # noqa: E402

STACK_DB = DATA / "stack.db"
# 2026-11-07: production wording. A campaign runs here once its "Run in the 6-step pipeline"
# switch is on (campaign page); the old "later update / Demo firms" words are gone.
NOT_IN_PIPELINE = ("This campaign is not in the pipeline yet. Turn on “Run in the 6-step pipeline” "
                   "on its campaign page.")
NOT_YET_SHEET = NOT_IN_PIPELINE
NOT_YET_FILE = NOT_IN_PIPELINE


def _stack_store():
    return store_mod.Store(STACK_DB)


def _demo_parts() -> dict:
    fm = fieldmap_mod.load(demo_mod.DEMO_FIELDMAP)
    rows = demo_mod.demo_rows()
    return {"id": "demo", "name": "Demo firms", "rows": rows, "fm": fm, "store_source": demo_mod.DEMO_SOURCE,
            "recipe": json.loads(Path(demo_mod.DEMO_RECIPE).read_text(encoding="utf-8")),
            "headers": runner_mod.headers_of(rows), "runnable": True, "why": "", "demo": True}


def _stack_parts(source: str) -> dict:
    """Rows, field map, recipe and store key for one picker entry ('demo' or 'campaign:<id>')."""
    source = str(source or "").strip()
    if source in ("", "demo"):
        return _demo_parts()
    if not source.startswith("campaign:"):
        raise ValueError(f"Unknown lead source '{source}'.")
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camp = next((c for c in loaded["campaigns"] if c.id == source[len("campaign:"):]), None)
    pipeline = camp is not None and _is_pipeline(camp)
    if stack_presenting_get()["on"] and not pipeline:
        raise ValueError(HIDDEN_IN_DEMO)
    if camp is None:
        raise ValueError("That campaign no longer exists.")
    rows = _read_tab_for_display(cfg_for_campaign(load_config(), camp), camp.tab)
    heads = runner_mod.headers_of(rows)
    fm = runner_mod.fieldmap_for(camp, loaded["fieldmaps"], heads)
    rec = recipe_mod.load(RECIPES_DIR / f"{camp.recipe}.json") if camp.recipe else None
    live = tab_source(load_config(), camp.tab).get("live", False)
    # a pipeline campaign keeps its results under its own id: its tab name ("Firms") may be
    # shared with another document
    return {"id": source, "name": camp.name, "rows": rows, "fm": fm,
            "store_source": f"campaign:{camp.id}" if pipeline else camp.tab,
            "recipe": rec.to_dict() if rec is not None else None, "headers": heads,
            "runnable": pipeline, "why": "" if pipeline else (NOT_YET_SHEET if live else NOT_YET_FILE),
            "demo": False, "camp": camp}


def _is_pipeline(camp) -> bool:
    """A campaign the new pipeline pages may RUN (real services, Draft-only push)."""
    return bool((getattr(camp, "raw", None) or {}).get("pipeline"))


def _pipeline_camps() -> list:
    try:
        return [c for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"] if _is_pipeline(c)]
    except Exception:  # noqa: BLE001
        return []


def _services(p):
    """Demo stand-ins for Demo firms; the real services for a pipeline campaign."""
    if p["demo"]:
        return demo_mod.DemoServices()
    cfg = load_config()
    return live_mod.LiveServices(_mv_key(cfg),str(cfg.get("icypeas_api_key") or "").strip())


def _platform(p):
    if p["demo"]:
        return demo_mod.DemoSendingPlatform()
    cfg = load_config()
    return live_mod.InstantlyDraftPlatform(str(cfg.get("instantly_api_key") or "").strip(),
                                           p["camp"].instantly_campaign_id, p["name"])


def _inbox(p, st):
    if p["demo"]:
        return demo_mod.DemoInbox()
    cfg = load_config()
    email_of = {k: v.get("email", "") for k, v in st.pushes(p["store_source"]).items()}
    return live_mod.InstantlyInbox(str(cfg.get("instantly_api_key") or "").strip(),
                                   p["camp"].instantly_campaign_id, email_of)


def stack_pickers() -> dict:
    out = [{"id": "demo", "name": "Demo firms", "demo": True, "runnable": True, "why": ""}]
    pipes = _pipeline_camps()
    out += [{"id": f"campaign:{c.id}", "name": c.name, "demo": False, "runnable": True, "why": ""} for c in pipes]
    if stack_presenting_get()["on"]:
        return {"pickers": out, "hidden": _live_campaign_count() - len(pipes)}
    cfg = load_config()
    for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]:
        if _is_pipeline(c):
            continue
        live = tab_source(cfg, c.tab).get("live", False) if c.tab else False
        out.append({"id": f"campaign:{c.id}", "name": c.name, "demo": False, "runnable": False,
                    "why": NOT_YET_SHEET if live else NOT_YET_FILE})
    return {"pickers": out}


def _plain_read_error(e: Exception) -> str:
    m = re.search(r"Unable to parse range: '?([^'\"]+)'?", str(e))
    if m:
        return (f"The tab '{m.group(1)}' is not in this campaign's Google Sheet. Open the campaign "
                "and check its lead source.")
    return f"Could not read this lead source: {str(e)[:200]}"


def _wrap(source: str, fn) -> dict:
    try:
        p = _stack_parts(source)
    except Exception as e:  # noqa: BLE001
        return {"error": _plain_read_error(e)}
    body = fn(p)
    return {**body, "name": p["name"], "demo": p["demo"], "runnable": p["runnable"], "why": p["why"]}


def stack_leads(source: str) -> dict:
    return _wrap(source, lambda p: stack_mod.leads_view(p["rows"], p["fm"], _stack_store(), p["store_source"]))


def stack_lead(source: str, key: str) -> dict:
    return _wrap(source, lambda p: {"lead": stack_mod.lead_record(
        p["rows"], p["fm"], _stack_store(), p["store_source"], key, p["headers"])})


def stack_research(source: str) -> dict:
    return _wrap(source, lambda p: stack_mod.research_view(p["rows"], p["fm"], _stack_store(), p["store_source"]))


def stack_find(source: str) -> dict:
    return _wrap(source, lambda p: stack_mod.find_view(p["rows"], p["fm"], _stack_store(),
                                                       p["store_source"], p["recipe"]))


def _refuse_unless_demo(source: str) -> dict | None:
    """None when this source may RUN: Demo firms, or a pipeline campaign."""
    if str(source or "demo") == "demo":
        return None
    try:
        p = _stack_parts(source)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": _plain_read_error(e)}
    return None if p["runnable"] else {"ok": False, "error": p["why"]}


def _out(r: dict, full: bool) -> dict:
    """A step's tally for the screen; `full` keeps the per-lead results (chain runs)."""
    return r if full else {k: v for k, v in r.items() if k != "results"}


def stack_run_research(source: str = "demo", st=None, full: bool = False) -> dict:
    refused = _refuse_unless_demo(source)
    if refused:
        return refused
    p, st = _stack_parts(source), st or _stack_store()
    # step 2: only leads Find email found an address for have their website read
    key = p["fm"].header("row_key") or "lead_id"
    # a lead whose sheet already has an ice breaker is not researched: its line is used as it is
    rows = [r for r in st.overlay(p["rows"], p["store_source"], key)
            if r.get("email_status") in ice_mod.USABLE_EMAIL and not ice_mod.sheet_icebreaker(p["fm"], r)]
    with _services(p) as svc:
        r = research_mod.run(rows, p["fm"], st, p["store_source"], svc.fetch)
    return {"ok": True, **_out(r, full), "with_email": len(rows), "would_cost": 0.0}


def stack_run_find(source: str = "demo", st=None, full: bool = False) -> dict:
    refused = _refuse_unless_demo(source)
    if refused:
        return refused
    p, st = _stack_parts(source), st or _stack_store()
    key = p["fm"].header("row_key") or "lead_id"
    rows = st.overlay(p["rows"], p["store_source"], key)     # step 1: every lead, website or not
    rec = recipe_mod.Recipe(p["recipe"])
    if p["demo"]:
        with _services(p) as svc:
            r = find_email_mod.run(rows, p["fm"], rec, st, p["store_source"], svc.verify, svc.find)
        return {"ok": True, **_out(r, full), "would_cost": round(svc.would_cost(), 2)}
    # 2026-11-07: a real campaign obeys ITS OWN page: the filters ("Who"), then "Leads per run",
    # "Leads per day" and "Most it may spend per run" ("How many"). The recipe only says HOW.
    rows = _campaign_filter(p["camp"], rows, p["fm"])
    limit, why = _campaign_room(p["camp"], st, p["store_source"])
    if limit <= 0:
        return {"ok": True, "processed": 0, "found": 0, "not_found": 0, "no_website": 0, "checks": 0,
                "finder_calls": 0, "already_done": 0, "would_cost": 0.0, "message": why,
                **({"results": []} if full else {})}
    with _services(p) as svc:
        r = find_email_mod.run(rows, p["fm"], rec, st, p["store_source"], svc.verify, svc.find, limit=limit,
                               budget=p["camp"].max_spend_usd, spent=svc.would_cost)
    return {"ok": True, **_out(r, full), "would_cost": round(svc.would_cost(), 2)}


def _campaign_filter(camp, rows: list[dict], fm) -> list[dict]:
    """The campaign's "Who" filters and order, on the pipeline's rows."""
    if camp.rules:
        rows = [r for r in rows if rules_mod.match(r, camp.rules, fm)[0]]
    if camp.order:
        rows = rules_mod.sort_rows(rows, camp.order, fm) or rows
    return rows


def _campaign_room(camp, st, store_source: str, today=None) -> tuple[int, str]:
    """How many NEW leads this run may take: "Leads per run", less what today already took
    when "Leads per day" is set. (0, reason) when there is no room."""
    per_run = camp.per_run
    if not per_run:
        return 0, "“Leads per run” is 0 on the campaign page."
    if not camp.per_day:
        return per_run, ""
    day = (today or _date.today()).isoformat()
    done = sum(1 for e in st.email_results(store_source).values() if str(e.get("updated") or "").startswith(day))
    room = max(0, camp.per_day - done)
    if not room:
        return 0, f"Today's limit is reached ({done} of {camp.per_day} leads). The next run takes new leads tomorrow."
    return min(per_run, room), ""


def stack_reset_demo() -> dict:
    _demo_stop()                       # a Live demo that is counting down or running ends first
    _stack_store().reset(demo_mod.DEMO_SOURCE)
    return {"ok": True}


def _csv_rows_count(path: Path) -> int:
    try:
        return len(_rows_from_csv_bytes(path.read_bytes()))
    except Exception:  # noqa: BLE001
        return -1


def stack_sources() -> dict:
    """Every lead source, for the Lead sources page. Reads names and counts only."""
    cfg = load_config()
    camps = runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
    used: Counter = Counter(c.tab for c in camps if c.tab)
    items = [{"id": "demo", "kind": "demo", "name": "Demo firms",
              "sub": f"Local file · {len(demo_mod.demo_rows())} rows · sample data on .example domains",
              "campaigns": 0, "access": {"label": "Results kept in app", "tone": ""},
              "href": "/leads?source=demo", "action": "Open leads"}]
    for c in (x for x in camps if _is_pipeline(x)):        # names only: no sheet read here
        items.append({"id": f"campaign:{c.id}", "kind": "pipeline", "name": c.name,
                      "sub": f"Google Sheet · tab {c.tab} · read only", "campaigns": 1,
                      "access": {"label": "Runs in the pipeline", "tone": "good"},
                      "href": f"/leads?source=campaign:{c.id}", "action": "Open leads"})
    if stack_presenting_get()["on"]:
        return {"sources": items, "columns": list(lead_record_mod.COLUMNS), "hidden": _live_campaign_count()}
    for rec in sorted(imports_mod.load_index(IMPORTS_DIR).values(), key=lambda r: r.get("uploaded", ""), reverse=True):
        items.append({"id": rec["tab"], "kind": "upload", "name": rec.get("name", rec["tab"]),
                      "sub": f"Uploaded file · {rec.get('rows', 0):,} rows · {str(rec.get('uploaded', ''))[:10]}",
                      "campaigns": used.get(rec["tab"], 0), "access": {"label": "Results kept in app", "tone": ""},
                      "href": f"/sources/{rec['tab']}", "action": "Open"})
    for tab, path in sorted((cfg.get("local_tabs") or {}).items()):
        p = Path(str(path))
        n = _csv_rows_count(p) if p.exists() else -1
        items.append({"id": tab, "kind": "local", "name": tab,
                      "sub": f"Local file · {p.name}" + (f" · {n:,} rows" if n >= 0 else ""),
                      "campaigns": used.get(tab, 0),
                      "access": {"label": "Available", "tone": "good"} if n >= 0 else {"label": "File missing", "tone": "bad"},
                      "href": f"/sources/{tab}", "action": "Open"})
    info = sheet_info(cfg)
    sheet_tabs = [t for t in info.get("tabs") or [] if t not in (cfg.get("local_tabs") or {})]
    if info.get("title") or sheet_tabs:
        items.append({"id": "sheet", "kind": "sheet", "name": info.get("title") or "Google Sheet",
                      "sub": f"Google Sheet · {len(sheet_tabs)} tab{'s' if len(sheet_tabs) != 1 else ''}",
                      "campaigns": sum(used.get(t, 0) for t in sheet_tabs),
                      "access": {"label": "Connected", "tone": "good"} if info.get("ok")
                      else {"label": "Not fully connected", "tone": "warn"},
                      "detail": "" if info.get("ok") else info.get("detail", ""),
                      "tabs": [{"tab": t, "campaigns": used.get(t, 0), "href": f"/sources/{t}"} for t in sheet_tabs],
                      "href": "", "action": "Tabs"})
    return {"sources": items, "columns": list(lead_record_mod.COLUMNS)}


def _missing_columns(heads: list[str]) -> list[str]:
    return [c for c in lead_record_mod.COLUMNS if not lead_record_mod.header(None, c, heads)]


def _matched_basics(heads: list[str]) -> dict:
    fm = fieldmap_mod.FieldMap({}).completed(heads)
    want = [("company_name", "company name"), ("website", "website"),
            ("contact_name", "contact name"), ("reference_email", "contact email")]
    got = [w for f, w in want if fm.header(f)]
    return {"matched": got, "of": len(want)}


def stack_check_sheet(link: str) -> dict:
    """Connect Google Sheet: check access and list the tabs. READ ONLY — it never adds a
    column, never writes a cell and saves nothing."""
    parsed = sheets_mod.parse_sheet_url(str(link or ""))
    if not parsed["doc_id"]:
        return {"ok": False, "error": "That is not a Google Sheet link. Paste the link from the browser's address bar."}
    sa = str(load_config().get("sheet_service_account_file") or "").strip()
    if not sa:
        return {"ok": False, "error": "Add the Google key file in Settings → Connections first. Without it the app cannot list a sheet's tabs."}
    try:
        client = sheets_mod.SheetsClient(sa)
        info = client.info(parsed["doc_id"])
        tabs = []
        for t in info["tabs"][:12]:
            heads = client._header(parsed["doc_id"], t)
            tabs.append({"tab": t, "columns": len(heads), "missing": _missing_columns(heads), **_matched_basics(heads)})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"The app could not open that sheet: {e}. Share it with the app's robot address (Settings → Connections)."}
    return {"ok": True, "title": info["title"], "tab_count": len(info["tabs"]), "tabs": tabs,
            "robot": getattr(client, "client_email", ""), "saved": False}


def _local_name_clash(name: str) -> str:
    cfg = load_config()
    camps = runner_mod.load_config_dir(CONFIG_DIR)["campaigns"]
    taken = {c.tab for c in camps if c.tab} | set(sheet_info(cfg).get("tabs") or [])
    if name in taken:
        return f"'{name}' is already a Google Sheet tab name. A local file with that name would replace the sheet tab, so choose another name."
    if name in (cfg.get("local_tabs") or {}):
        return f"There is already a local file called '{name}'."
    if imports_mod.is_import_tab(name) or name in ("demo", "sheet"):
        return f"'{name}' is a name the app uses itself. Choose another."
    return ""


def stack_check_local(path: str, name: str = "") -> dict:
    p = Path(str(path or "").strip().strip('"'))
    if not str(p) or not p.is_absolute():
        return {"ok": False, "error": "Paste the full path of the file, for example C:\\Leads\\new-firms.csv."}
    if p.suffix.lower() != ".csv":
        return {"ok": False, "error": "Only CSV files can be linked in this version. Save the file as CSV first."}
    if not p.exists():
        return {"ok": False, "error": "There is no file at that path."}
    rows = _rows_from_csv_bytes(p.read_bytes())
    heads = runner_mod.headers_of(rows)
    nm = str(name or p.stem).strip()
    return {"ok": True, "path": str(p), "name": nm, "rows": len(rows), "columns": len(heads),
            "basics": _matched_basics(heads), "missing": _missing_columns(heads),
            "clash": _local_name_clash(nm)}


def stack_save_local(path: str, name: str) -> dict:
    chk = stack_check_local(path, name)
    if not chk.get("ok"):
        return chk
    if chk["clash"]:
        return {"ok": False, "error": chk["clash"]}
    tabs = dict(load_config().get("local_tabs") or {})
    tabs[chk["name"]] = chk["path"]
    save_config({"local_tabs": tabs})
    return {"ok": True, "name": chk["name"], "rows": chk["rows"]}


@app.get("/api/stack/pickers")
def api_stack_pickers():
    return stack_pickers()


@app.get("/api/stack/sources")
def api_stack_sources():
    return stack_sources()


@app.get("/api/stack/leads")
def api_stack_leads(source: str = "demo"):
    return stack_leads(source)


@app.get("/api/stack/lead")
def api_stack_lead(source: str = "demo", key: str = ""):
    return stack_lead(source, key)


@app.get("/api/stack/research")
def api_stack_research(source: str = "demo"):
    return stack_research(source)


@app.get("/api/stack/find")
def api_stack_find(source: str = "demo"):
    return stack_find(source)


@app.get("/api/stack/labels")
def api_stack_labels():
    return {"labels": stack_mod.labels()}


@app.post("/api/stack/research/run")
async def api_stack_research_run(request: Request):
    b = await request.json()
    return stack_run_research(str(b.get("source") or "demo"))


@app.post("/api/stack/find/run")
async def api_stack_find_run(request: Request):
    b = await request.json()
    return stack_run_find(str(b.get("source") or "demo"))


@app.post("/api/stack/demo/reset")
def api_stack_demo_reset():
    return stack_reset_demo()


@app.post("/api/stack/sheet/check")
async def api_stack_sheet_check(request: Request):
    b = await request.json()
    return stack_check_sheet(str(b.get("link") or ""))


@app.post("/api/stack/local/check")
async def api_stack_local_check(request: Request):
    b = await request.json()
    return stack_check_local(str(b.get("path") or ""), str(b.get("name") or ""))


@app.post("/api/stack/local/save")
async def api_stack_local_save(request: Request):
    b = await request.json()
    return stack_save_local(str(b.get("path") or ""), str(b.get("name") or ""))


# ── the full stack, build session 2: Ice breakers, Cold email, Sending, Replies ──
# Same rule as session 1: only the demo runs. Sending is TEST MODE ONLY and the only
# platform it is given is the demo stand-in, which keeps a list in memory. Each step writes
# only its own column through core/lead_record.py (icebreaker_status, push_status,
# reply_status). Nothing here touches a sheet, Instantly or `Status`.

from core import icebreakers as ice_mod      # noqa: E402
from core import templates as tpl_mod        # noqa: E402
from core import sheet_writeback as swb_mod  # noqa: E402
from core import sending as send_mod         # noqa: E402
from core import replies as replies_mod      # noqa: E402
from core import copy_score as score_mod     # noqa: E402
from core import stack_steps as steps_mod    # noqa: E402
from core import lead_record as lead_record_mod  # noqa: E402

TEST_MODE_ONLY = True        # this version has no way to switch it off
DEMO_RULESET_ID = "practices-ladder"
NOT_YET_STEP = NOT_IN_PIPELINE


def _demo_ruleset(st, p=None) -> dict:
    """The source's ice breaker rule set; a new source starts from the default ladder."""
    src = p["store_source"] if p else demo_mod.DEMO_SOURCE
    rs = st.ruleset(src, DEMO_RULESET_ID)
    if rs is None:
        rs = json.loads(Path(demo_mod.RULESET_FILE).read_text(encoding="utf-8"))
        st.save_ruleset(src, rs)
    return rs


def _demo_templates_file() -> dict:
    return tpl_mod.load_demo(demo_mod.TEMPLATES_FILE)


def _demo_seeded(st, p=None) -> dict:
    """Demo firms: the sample templates, seeded once. A pipeline campaign gets NO seeded
    templates: its copy comes through the request queue. Returns the approved figures."""
    if p is not None and not p["demo"]:
        return {"approved_figures": list((p["camp"].raw.get("approved_figures") or []))}
    demo = _demo_templates_file()
    tpl_mod.ensure_seeded(st, demo_mod.DEMO_SOURCE, demo)
    return demo


def _live_campaign_count() -> int:
    """How many live campaigns cannot run steps 3-6 yet. The step pages show only this
    number, not their names: their names carry client brands."""
    try:
        return sum(1 for c in runner_mod.load_config_dir(CONFIG_DIR)["campaigns"] if not _is_pipeline(c))
    except Exception:  # noqa: BLE001 - the step pages still show the demo
        return 0


def _later(n: int) -> dict:
    return {"count": n, "why": NOT_YET_STEP}


def _only_demo(source: str) -> dict | None:
    """None when steps 3-6 may run on `source`. A pipeline campaign that cannot be read says
    why; anything else gets the plain "not in this version" answer."""
    r = _refuse_unless_demo(source)
    if r is None:
        return None
    pipe = any(f"campaign:{c.id}" == str(source) for c in _pipeline_camps())
    return {"ok": False, "error": (r.get("error") if pipe else "") or NOT_YET_STEP}


def _demo_ctx(source: str = "demo"):
    p, st = _stack_parts(source), _stack_store()
    return p, st


def _step_tiles(view) -> list[dict]:
    """One tile per source that can run a step: Demo firms, then each pipeline campaign.
    `view(p, st)` gives the step's own numbers for that source."""
    st, out = _stack_store(), []
    for src in ["demo"] + [f"campaign:{c.id}" for c in _pipeline_camps()]:
        try:
            p = _stack_parts(src)
        except Exception:  # noqa: BLE001 - an unreadable sheet hides its tile, not the page
            continue
        out.append({"id": src, "name": p["name"], "demo": p["demo"], "runnable": True, "why": "", **view(p, st)})
    return out


def stack_mode() -> dict:
    return {"test_mode": TEST_MODE_ONLY, "title": "Safe sending",
            "text": "Leads go only to Draft or Paused campaigns. Emails are not sent.", "can_change": False}


# step 3
def stack_ice() -> dict:
    def view(p, st):
        rs = _demo_ruleset(st, p)
        v = steps_mod.ice_camp(p["rows"], p["fm"], st, p["store_source"], rs)
        return {"ruleset": rs["name"], "counts": v["counts"], "_rs": rs}
    tiles = _step_tiles(view)
    rulesets = []
    for t in tiles:
        rs = t.pop("_rs")
        on = sum(1 for r in rs.get("rungs") or [] if r.get("on", True))
        rulesets.append({"id": rs["id"], "name": rs["name"], "rungs": len(rs.get("rungs") or []), "on": on,
                         "used_by": [t["name"]], "written": t["counts"]["written"]})
    real = [r for r, t in zip(rulesets, tiles) if not t["demo"]]     # his campaign's rule set first
    return {"campaigns": tiles, "later": _later(_live_campaign_count()), "rulesets": (real or rulesets)[:1]}


def stack_ice_camp(source: str = "demo") -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    rs = _demo_ruleset(st, p)
    return {**steps_mod.ice_camp(p["rows"], p["fm"], st, p["store_source"], rs), "name": p["name"], "demo": p["demo"]}


def stack_ice_run(source: str = "demo", keys=None, rewrite: bool = False, st=None, full: bool = False) -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    p, st = _stack_parts(source), st or _stack_store()
    if rewrite and not keys:
        return {"ok": False, "error": "Select the leads to rewrite first."}
    r = ice_mod.run(p["rows"], p["fm"], st, p["store_source"], _demo_ruleset(st, p),
                    keys=keys or None, rewrite=bool(rewrite))
    if not r["processed"] and not r["skipped_sent"]:
        return {"ok": False, "error": "No lead is waiting. A lead needs an email address and website research first."}
    return {"ok": True, **_out(r, full)}


def stack_ice_ruleset(source: str = "demo", body: dict | None = None) -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    st, p = _stack_store(), _stack_parts(source)
    cur = _demo_ruleset(st, p)
    new = {**cur, **{k: v for k, v in (body or {}).items() if k in ("name", "rungs", "shared_ground", "default", "template")}}
    new["id"] = cur["id"]
    try:
        clean = ice_mod.validate(new)
    except ice_mod.RuleSetError as e:
        return {"ok": False, "error": str(e)}
    st.save_ruleset(p["store_source"], clean)
    return {"ok": True, "ruleset": clean}


def stack_ice_preview(source: str = "demo", key: str = "") -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    return steps_mod.ice_preview(p["rows"], p["fm"], st, p["store_source"], _demo_ruleset(st, p), key)


# step 4
def stack_email() -> dict:
    def view(p, st):
        _demo_seeded(st, p)
        v = steps_mod.email_camp(p["rows"], p["fm"], st, p["store_source"])
        return {"live": v["live"], "drafts": v["drafts"], "top_score": v["top_score"]}
    return {"campaigns": _step_tiles(view), "later": _later(_live_campaign_count())}


def stack_email_camp(source: str = "demo") -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    demo = _demo_seeded(st, p)
    return {**steps_mod.email_camp(p["rows"], p["fm"], st, p["store_source"]), "name": p["name"], "demo": p["demo"],
            "approved_figures": demo.get("approved_figures") or []}


def stack_email_request(source: str = "demo", kind: str = "", instructions: str = "") -> dict:
    """Demo firms: the stand-in writer answers at once. A pipeline campaign: the request
    waits in the queue until Claude Code answers it (answer_template.py)."""
    refused = _only_demo(source)
    if refused:
        return refused
    st, p = _stack_store(), _stack_parts(source)
    demo = _demo_seeded(st, p)
    try:
        r = tpl_mod.request(st, p["store_source"], kind, instructions, demo.get("approved_figures") or [],
                            writer=demo_mod.demo_writer() if p["demo"] else None,
                            auto_approve=stack_approvals_get()["auto_approve"])
    except tpl_mod.TemplateError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, **r}


def stack_email_answer(source: str, rid: int, subject: str, body: str) -> dict:
    """Claude Code's answer to a waiting request: scored, and live by itself at 90+."""
    refused = _only_demo(source)
    if refused:
        return refused
    st, p = _stack_store(), _stack_parts(source)
    req = next((r for r in st.requests(p["store_source"]) if r["id"] == int(rid)), None)
    if req is None:
        return {"ok": False, "error": "That request does not exist."}
    if req.get("state") != "queued":
        return {"ok": False, "error": "That request was already answered."}
    figs = _demo_seeded(st, p).get("approved_figures") or []
    return {"ok": True, **tpl_mod.attach_draft(st, p["store_source"], int(rid), {"subject": subject, "body": body},
                                               figs, auto_approve=stack_approvals_get()["auto_approve"])}


def stack_email_template(source: str = "demo", tid: int = 0, action: str = "", subject: str = "", body: str = "") -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    st, p = _stack_store(), _stack_parts(source)
    demo = _demo_seeded(st, p)
    src = p["store_source"]
    try:
        if action == "approve":
            return tpl_mod.approve(st, src, tid)
        if action == "reject":
            return tpl_mod.reject(st, src, tid)
        if action == "edit":
            return tpl_mod.edit(st, src, tid, subject, body, demo.get("approved_figures") or [])
    except tpl_mod.TemplateError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Choose approve, edit or reject."}


def stack_email_score(subject: str = "", body: str = "") -> dict:
    return tpl_mod.scored({"subject": subject, "body": body}, _demo_templates_file().get("approved_figures") or [])


def stack_email_preview(source: str = "demo", key: str = "", tid: int = 0) -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    _demo_seeded(st, p)
    return steps_mod.email_preview(p["rows"], p["fm"], st, p["store_source"], key, tid)


# step 5
def _sending_campaign(p) -> str:
    return demo_mod.DEMO_SENDING_CAMPAIGN if p["demo"] else f"{p['name']} · Draft campaign"


def stack_send(source: str = "demo") -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    _demo_seeded(st, p)
    v = steps_mod.send_view(p["rows"], p["fm"], st, p["store_source"], campaign_name=p["name"],
                            sending_campaign=_sending_campaign(p))

    def row(q, s):
        _demo_seeded(s, q)
        return steps_mod.send_view(q["rows"], q["fm"], s, q["store_source"], campaign_name=q["name"],
                                   sending_campaign=_sending_campaign(q))["row"]
    rows = [{**t, **row(_stack_parts(t["id"]), _stack_store()), "source": t["id"]} for t in _step_tiles(lambda q, s: {})]
    return {**v, "rows": rows, "later": _later(_live_campaign_count()),
            "test_mode": TEST_MODE_ONLY, "demo": p["demo"], "name": p["name"], "source": source}


def stack_send_run(source: str = "demo", st=None, full: bool = False) -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    p, st = _stack_parts(source), st or _stack_store()
    _demo_seeded(st, p)
    platform = _platform(p)
    try:
        r = send_mod.run(p["rows"], p["fm"], st, p["store_source"], platform, test_mode=TEST_MODE_ONLY)
    except send_mod.SendRefused as e:
        return {"ok": False, "error": str(e)}
    if not r["pushed"] and not r["held"] and not r["failed"]:
        return {"ok": False, "error": "No lead is ready. Write ice breakers first."}
    return {"ok": True, **_out(r, full), "test_mode": True, "platform_received": len(platform.added),
            "platform_status": getattr(platform, "status", "")}


# step 6
def stack_replies(source: str = "demo") -> dict:
    refused = _only_demo(source)
    if refused:
        return {"error": refused["error"]}
    p, st = _demo_ctx(source)
    return {**steps_mod.replies_view(st, p["store_source"], campaign_name=p["name"]), "name": p["name"], "demo": p["demo"]}


def stack_replies_check(source: str = "demo", st=None) -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    p, st = _stack_parts(source), st or _stack_store()
    try:
        r = replies_mod.check(p["rows"], p["fm"], st, p["store_source"], _inbox(p, st))
    except Exception as e:  # noqa: BLE001 - the inbox could not be read
        return {"ok": False, "error": f"Could not read the replies: {str(e)[:160]}"}
    return {"ok": True, **r}


def stack_replies_update(source: str = "demo", rid: int = 0, category: str = "", handled=None) -> dict:
    refused = _only_demo(source)
    if refused:
        return refused
    st, src = _stack_store(), _stack_parts(source)["store_source"]
    try:
        if category:
            replies_mod.recategorise(st, src, rid, category)
        if handled is not None:
            replies_mod.mark_handled(st, src, rid, bool(handled))
    except (ValueError, lead_record_mod.WriteRefused) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


@app.get("/api/stack/mode")
def api_stack_mode():
    return stack_mode()


@app.get("/api/stack/ice")
def api_stack_ice():
    return stack_ice()


@app.get("/api/stack/ice/camp")
def api_stack_ice_camp(source: str = "demo"):
    return stack_ice_camp(source)


@app.get("/api/stack/ice/preview")
def api_stack_ice_preview(source: str = "demo", key: str = ""):
    return stack_ice_preview(source, key)


@app.post("/api/stack/ice/run")
async def api_stack_ice_run(request: Request):
    b = await request.json()
    keys = [str(k) for k in (b.get("keys") or [])]
    return stack_ice_run(str(b.get("source") or "demo"), keys, bool(b.get("rewrite")))


@app.post("/api/stack/ice/ruleset")
async def api_stack_ice_ruleset(request: Request):
    b = await request.json()
    return stack_ice_ruleset(str(b.get("source") or "demo"), b.get("ruleset") or {})


@app.get("/api/stack/email")
def api_stack_email():
    return stack_email()


@app.get("/api/stack/email/camp")
def api_stack_email_camp(source: str = "demo"):
    return stack_email_camp(source)


@app.get("/api/stack/email/preview")
def api_stack_email_preview(source: str = "demo", key: str = "", template: int = 0):
    return stack_email_preview(source, key, template)


@app.post("/api/stack/email/request")
async def api_stack_email_request(request: Request):
    b = await request.json()
    return stack_email_request(str(b.get("source") or "demo"), str(b.get("kind") or ""), str(b.get("instructions") or ""))


@app.get("/api/stack/email/queue")
def api_stack_email_queue(source: str = "demo"):
    """Requests waiting for Claude Code to write a draft (answer_template.py reads this)."""
    refused = _only_demo(source)
    if refused:
        return refused
    p = _stack_parts(source)
    return {"ok": True, "name": p["name"],
            "waiting": [r for r in _stack_store().requests(p["store_source"]) if r.get("state") == "queued"]}


@app.post("/api/stack/email/answer")
async def api_stack_email_answer(request: Request):
    b = await request.json()
    return stack_email_answer(str(b.get("source") or ""), _int(b.get("request")), str(b.get("subject") or ""),
                              str(b.get("body") or ""))


@app.post("/api/stack/email/template")
async def api_stack_email_template(request: Request):
    b = await request.json()
    return stack_email_template(str(b.get("source") or "demo"), _int(b.get("id")), str(b.get("action") or ""),
                                str(b.get("subject") or ""), str(b.get("body") or ""))


@app.post("/api/stack/email/score")
async def api_stack_email_score(request: Request):
    b = await request.json()
    return stack_email_score(str(b.get("subject") or ""), str(b.get("body") or ""))


@app.get("/api/stack/send")
def api_stack_send(source: str = "demo"):
    return stack_send(source)


@app.post("/api/stack/send/run")
async def api_stack_send_run(request: Request):
    b = await request.json()
    return stack_send_run(str(b.get("source") or "demo"))


@app.get("/api/stack/replies")
def api_stack_replies(source: str = "demo"):
    return stack_replies(source)


@app.post("/api/stack/replies/check")
async def api_stack_replies_check(request: Request):
    b = await request.json()
    return stack_replies_check(str(b.get("source") or "demo"))


@app.post("/api/stack/replies/update")
async def api_stack_replies_update(request: Request):
    b = await request.json()
    return stack_replies_update(str(b.get("source") or "demo"), _int(b.get("id")), str(b.get("category") or ""),
                                b.get("handled"))


# ── the full stack, build session 3: Schedules, Health, Live demo ────
# Same rules again: only the demo runs, test mode only. A chain run (core/stack_run.py) runs
# the real step functions above, one after the other, with every write guarded by the health
# agent (core/health.py). Per-step schedules fire only from the app clock, which is OFF in
# the test engine (LEADGEN_NO_SCHEDULER=1). The Live demo's one-time trigger is its own timer,
# so the demo works with the clock off; it touches demo data only.

from datetime import date as _date, timedelta as _timedelta   # noqa: E402

from core import stack_schedule as ssched_mod  # noqa: E402
from core import health as health_mod          # noqa: E402
from core import stack_run as srun_mod         # noqa: E402

HIDDEN_IN_DEMO = "Hidden while Privacy is on. Client campaigns are not shown."
LOCKED_WHY = "Locked off: leads go to Draft campaigns only, so no email is sent."
DEMO_TRIGGER = "Live demo"
DEMO_COUNTDOWN = 10          # seconds from Start demo to the trigger
DEMO_PACE = 2.0              # seconds of activity per step, so a person can watch
FOUND_EMAIL = ("as-is", "enriched", "fallback")

_STACK_LOCK = threading.Lock()
_STACK_ALIVE: set[str] = set()       # chain runs this process is running (or counting down to)
_STACK_STOP: set[str] = set()        # runs asked to stop between steps (Reset)
_STACK_TIMERS: dict[str, threading.Timer] = {}


def _stamp(t: datetime | None = None) -> str:
    return (t or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


# Live demo mode and approval rules
def stack_presenting_get() -> dict:
    return {"on": bool(_stack_store().setting("presenting", False))}


def stack_presenting_set(on) -> dict:
    _stack_store().set_setting("presenting", bool(on))
    return {"ok": True, "on": bool(on)}


def stack_approvals_get() -> dict:
    a = _stack_store().setting("approvals") or {}
    return {"auto_approve": bool(a.get("auto_approve", True)), "auto_reply": False, "allow_spend": False,
            "locked": ["auto_reply", "allow_spend"], "locked_why": LOCKED_WHY}


def stack_approvals_set(body: dict) -> dict:
    body = body or {}
    if body.get("auto_reply") or body.get("allow_spend"):
        return {"ok": False, "error": LOCKED_WHY}
    if "auto_approve" in body:
        _stack_store().set_setting("approvals", {"auto_approve": bool(body["auto_approve"])})
    return {"ok": True, **stack_approvals_get()}


# the demo's rows in plain words
def _demo_names(p) -> dict[str, str]:
    return {str(p["fm"].get(r, "row_key")): str(p["fm"].get(r, "company_name") or "") for r in p["rows"]}


def _demo_counts(st, p) -> dict:
    stat = st.statuses(p["store_source"])
    vals = lambda col: [v.get(col, "") for v in stat.values()]          # noqa: E731
    return {"leads": len(p["rows"]),
            "websites": sum(1 for v in vals("website_status") if v == "found"),
            "emails": sum(1 for v in vals("email_status") if v in FOUND_EMAIL),
            "icebreakers": sum(1 for v in vals("icebreaker_status") if v == "written"),
            "sent": sum(1 for v in vals("push_status") if v == "pushed"),
            "replies": sum(1 for v in vals("reply_status") if v),
            "interested": sum(1 for v in vals("reply_status") if v == "interested")}


# ── what each step says in the Activity log ──
def _lbl(col: str, value: str) -> str:
    return stack_mod.pill(col, value)["label"].lower()


def _step_research(st, names, source="demo"):
    health_mod.Agent(st, _stack_parts(source)["store_source"]).due_site_retries()   # a next-day retry that has come
    r = stack_run_research(source, st=st, full=True)
    lines = [(f"{x['company']}: website {_lbl('website_status', x['website_status'])}", "")
             for x in r.get("results") or [] if x["website_status"] != "found"]
    if not r.get("processed"):
        why = "no lead has an email yet, so no website was read" if not r.get("with_email") \
            else "every lead with an email was researched in the last 30 days"
        return {"summary": why, "lines": [], **_out(r, False)}
    return {"summary": f"{r['found']} of {r['processed']} websites found", "lines": lines, **_out(r, False)}


def _step_find(st, names, source="demo"):
    r = stack_run_find(source, st=st, full=True)
    if not r.get("ok"):
        return {"summary": r.get("error", ""), "lines": []}
    if r.get("message"):                       # the campaign's limits leave no room this run
        return {"summary": r["message"], "lines": [], **_out(r, False)}
    lines = [(f"{x['company']}: email {_lbl('email_status', x['email_status'])}", "")
             for x in r.get("results") or [] if x.get("email")]
    if r.get("stopped_at_budget"):
        lines.append(("Stopped: the campaign's spend limit per run was reached.", "warn"))
    return {"summary": f"{r['found']} emails found, {r['processed'] - r['found']} not found",
            "lines": lines, **_out(r, False)}


def _step_ice(st, names, source="demo"):
    r = stack_ice_run(source, st=st, full=True)
    if not r.get("ok"):
        return {"summary": r.get("error", ""), "lines": []}
    lines = []
    for x in r.get("results") or []:
        who = names.get(str(x["key"]), x["key"])
        if x["status"] == "written":
            lines.append((f"{who}: ice breaker written ({x.get('rung') or 'Default'})", ""))
    floor = sum(1 for x in r.get("results") or [] if x["status"] == "written" and x.get("rung") == "Default")
    sheet = int(r.get("from_sheet") or 0)
    return {"summary": f"{r['written']} written, {floor} from the Default line"
                       + (f", {sheet} already in the sheet" if sheet else ""), "lines": lines, **_out(r, False)}


def _step_email(st, names, source="demo"):
    p = _stack_parts(source)
    _demo_seeded(st, p)
    v = steps_mod.email_camp(p["rows"], p["fm"], st, p["store_source"])
    live = [t["name"] for t in v["templates"] if t["state"]["value"] == "live"]
    prepared = len(v["preview"])
    waiting = sum(1 for r in st.requests(p["store_source"]) if r.get("state") == "queued")
    lines = [(f"{v['drafts']} new template waiting for approval", "")] if v["drafts"] else []
    if waiting:
        lines.append((f"{waiting} template request waiting for Claude Code", ""))
    used = " and ".join(live) if live else "no live template"
    return {"summary": f"{len(live)} template{'s' if len(live) != 1 else ''} live, {prepared} leads matched ({used})",
            "lines": lines, "prepared": prepared, "live": len(live), "drafts": v["drafts"]}


def _step_send(st, names, source="demo"):
    r = stack_send_run(source, st=st, full=True)
    if not r.get("ok"):
        return {"summary": r.get("error", ""), "lines": []}
    where = "queued in test mode" if source == "demo" else "added to the Draft campaign (nothing is sent)"
    lines = []
    for x in r.get("results") or []:
        who = names.get(str(x["key"]), x["key"])
        if x["status"] == "pushed":
            lines.append((f"{who}: {where} ({x.get('template', '')})", ""))
        elif x["status"] == "held":
            lines.append((f"{who}: held. {x.get('reason', '')}".strip(), ""))
    return {"summary": f"{r['pushed']} leads {where.split(' (')[0]}, {r['held']} held", "lines": lines,
            **_out(r, False)}


def _step_replies(st, names, source="demo"):
    r = stack_replies_check(source, st=st)
    lines = [("Collecting replies. Sample replies are used in demo mode.", "")] if source == "demo" else \
        [("Reading replies from Instantly. The campaign is a Draft, so none are expected.", "")]
    if not r.get("ok"):
        lines.append((r.get("error", ""), "bad"))
    for x in sorted(st.replies(_stack_parts(source)["store_source"]), key=lambda x: x["id"]):
        tone = "good" if x["category"] == "interested" else ""
        lines.append((f"{x['company'] or names.get(x['row_key'], x['row_key'])} replied: "
                      f"{stack_mod.pill('reply_status', x['category'])['label']}", tone))
    return {"summary": f"{r.get('new', 0)} new replies", "lines": lines, "new": r.get("new", 0)}


_STEP_FNS = {"research": _step_research, "find": _step_find, "ice": _step_ice, "email": _step_email,
             "send": _step_send, "replies": _step_replies}


def _chain_steps(keys: list[str], source: str = "demo") -> list[tuple]:
    names = _demo_names(_stack_parts(source))
    return [(ssched_mod.STEP_KEYS.index(k), k, ssched_mod.LABEL[k],
             (lambda st, f=_STEP_FNS[k]: f(st, names, source))) for k in keys]


# ── decisions, summary, health check ──
def stack_decisions_list(st=None, src: str = demo_mod.DEMO_SOURCE) -> list[dict]:
    st = st or _stack_store()
    out = []
    for r in st.replies(src):
        if r["category"] == "interested" and not r["handled"]:
            out.append({"kind": "reply", "text": f"{r['company']} replied: interested", "short": r["company"],
                        "href": f"/replies?open={r['id']}", "button": "Open reply"})
    drafts = [t for t in st.templates(src) if t["state"] == "draft"]
    if drafts:
        n = len(drafts)
        out.append({"kind": "template", "text": f"{n} new email template{'s are' if n > 1 else ' is'} waiting for approval",
                    "href": f"/email?open={src}", "button": "Review"})
    for i in st.incidents(src):
        if i["result"] in (health_mod.ESCALATED, health_mod.OPEN):
            out.append({"kind": "health", "text": f"{i['issue']}. {i['action']}", "href": "/health", "button": "Details"})
    return out


def _summary_decisions(dec: list[dict]) -> list[dict]:
    replies = [d["short"] for d in dec if d["kind"] == "reply"]
    out = []
    if replies:
        out.append({"text": f"{len(replies)} interested repl{'y' if len(replies) == 1 else 'ies'} ({', '.join(replies)})"})
    out += [{"text": d["text"]} for d in dec if d["kind"] == "template"]
    return out


def _write_summary(st, day: _date | None = None, source: str = "demo") -> dict:
    day = day or _date.today()
    p = _stack_parts(source)
    body = health_mod.summary(day, st.incidents(p["store_source"]), _demo_counts(st, p),
                              _summary_decisions(stack_decisions_list(st, p["store_source"])),
                              sent_word="sent (test mode)" if p["demo"] else "pushed to a Draft campaign")
    st.save_summary(p["store_source"], day.isoformat(), body)
    return body


def _health_check(st, agent=None, log=None, source: str = "demo") -> list[dict]:
    """One sweep of the health agent over one source. Also used by the clock every 5 minutes."""
    p = _stack_parts(source)
    src = p["store_source"]
    agent = agent or health_mod.Agent(st, src)
    for r in st.runs(src, ("scheduled",)):
        if r["id"] not in _STACK_ALIVE:      # the engine restarted before this trigger fired
            st.update_run(r["id"], state="stopped", finished=_stamp(), message="The engine restarted before the trigger fired.")
    stat = st.statuses(src)
    blocked = [k for k, v in stat.items() if v.get("website_status") == "blocked"]
    waiting = sum(1 for v in stat.values() if v.get("icebreaker_status") == "written" and not v.get("push_status"))
    live = len(tpl_mod.live(st, src)) if st.templates(src) else None

    def resume(run):
        keys = ssched_mod.STEP_KEYS[int(run.get("step") or 0): int(run.get("end_step") or 5) + 1]
        r = _start_chain(st, f"Resumed after a restart ({run['id']})", keys, source=source)
        return r.get("run_id", "")

    new = agent.check(alive=frozenset(_STACK_ALIVE), resume=resume, names=_demo_names(p), blocked_keys=blocked,
                      live_templates=live, waiting_leads=waiting)
    for i in new:
        if log:
            log(f"Health check: {i['issue']}. {i['action']}", "good" if i["result"] == health_mod.RESOLVED else "bad")
    return new


def stack_health_check() -> dict:
    st = _stack_store()
    new = _health_check(st)
    return {"ok": True, "new": len(new)}


# ── chain runs ──
def _run_sources() -> list[str]:
    """Store keys a chain can run on: Demo firms and each pipeline campaign."""
    return [demo_mod.DEMO_SOURCE] + [f"campaign:{c.id}" for c in _pipeline_camps()]


def _active_runs(st) -> list[dict]:
    return [r for src in _run_sources() for r in st.runs(src, ("scheduled", "running")) if r["id"] in _STACK_ALIVE]


def _start_chain(st, trigger: str, keys: list[str], *, delay: float = 0, pace: float = 0, waits=None,
                 wrap=None, wait: bool = False, sleep=time.sleep, source: str = "demo") -> dict:
    """Start one chain run of `keys` on `source`, now or after `delay` seconds. One run at a time."""
    if not keys:
        return {"ok": False, "error": "No step to run."}
    src = _stack_parts(source)["store_source"]
    with _STACK_LOCK:
        if _active_runs(st):
            return {"ok": False, "error": "A pipeline run is already in progress. Wait for it to finish, or select Reset."}
        rid = srun_mod.new_id()
        due = datetime.now() + _timedelta(seconds=delay)
        idx = [ssched_mod.STEP_KEYS.index(k) for k in keys]
        st.add_run({"id": rid, "source": src, "trigger": trigger,
                    "state": "scheduled" if delay else "running", "step": idx[0], "start_step": idx[0],
                    "end_step": idx[-1], "due": due.isoformat(sep=" ", timespec="milliseconds")})
        _STACK_ALIVE.add(rid)
    log = srun_mod.logger(st, rid)
    if delay:
        log(f"Trigger scheduled: {'full pipeline' if len(keys) == 6 else ssched_mod.LABEL[keys[0]]}, once at {due:%H:%M:%S}")

    def finish(agent, flog):
        if source != "demo":                 # 2026-11-07: results go back to the campaign's sheet
            wb = sheet_writeback(source)
            if wb.get("error"):
                flog(wb["error"], "warn")
            elif not wb.get("off"):
                flog(f"Google Sheet updated: {wb.get('cells', 0)} cells "
                     "(Found Email, Ice Breaker, Status).", "good")
        _health_check(st, agent, flog, source)
        _write_summary(st, source=source)
        flog("Daily summary updated.")

    def go():
        try:
            if rid in _STACK_STOP:
                return
            log("Trigger fired. Pipeline started.", "good")
            srun_mod.run_chain(st, src, rid, _chain_steps(keys, source), pace=pace, sleep=sleep,
                               stop=lambda: rid in _STACK_STOP, wrap=wrap, waits=waits, finish=finish)
        except Exception as e:  # noqa: BLE001 - a chain must never take the engine down
            st.update_run(rid, state="failed", finished=_stamp(), message=str(e)[:300])
        finally:
            _STACK_ALIVE.discard(rid)
            _STACK_STOP.discard(rid)
            _STACK_TIMERS.pop(rid, None)

    if wait:
        if delay:
            time.sleep(delay)
        go()
    elif delay:
        t = threading.Timer(delay, go)
        t.daemon = True
        _STACK_TIMERS[rid] = t
        t.start()
    else:
        threading.Thread(target=go, name=f"stack-{rid}", daemon=True).start()
    return {"ok": True, "run_id": rid, "due": _stamp(due)}


def _demo_stop(timeout: float = 6.0) -> None:
    for rid, t in list(_STACK_TIMERS.items()):
        t.cancel()
        _STACK_TIMERS.pop(rid, None)
        _STACK_ALIVE.discard(rid)
    _STACK_STOP.update(_STACK_ALIVE)
    end = time.time() + timeout
    while _STACK_ALIVE and time.time() < end:
        time.sleep(0.05)


def stack_demo_start(countdown: float = DEMO_COUNTDOWN, pace: float = DEMO_PACE, waits=None,
                     wait: bool = False, sleep=time.sleep) -> dict:
    """Start demo: reset the demo, then ONE one-time trigger `countdown` seconds ahead runs
    steps 1–6 by themselves. The stand-in sheet refuses one Find-email write, so the health
    agent has a known issue to fix."""
    stack_reset_demo()
    return _start_chain(_stack_store(), DEMO_TRIGGER, list(ssched_mod.STEP_KEYS), delay=countdown, pace=pace,
                        waits=waits, wrap=lambda s: demo_mod.DemoWriteLimit(s), wait=wait, sleep=sleep)


RUN_TRIGGER = "Scheduled run"
RUN_NOW_TRIGGER = "Campaign: Run now"            # the campaign page's Run button
SCHEDULED_TRIGGER = "Campaign schedule"          # the campaign's own "Run by itself"
RUN_TRIGGERS = (DEMO_TRIGGER, RUN_TRIGGER, RUN_NOW_TRIGGER, SCHEDULED_TRIGGER)


def stack_run_start(source: str = "demo", countdown: float = DEMO_COUNTDOWN, pace: float = 1.0) -> dict:
    """Pipeline run page: Demo firms → the Live demo (reset + one known issue). A pipeline
    campaign → a one-time trigger `countdown` seconds ahead runs steps 1–6 for real. Nothing
    is reset: leads already done are skipped by every step."""
    if str(source or "demo") == "demo":
        return stack_demo_start(countdown=countdown)
    refused = _refuse_unless_demo(source)
    if refused:
        return refused
    return _start_chain(_stack_store(), RUN_TRIGGER, list(ssched_mod.STEP_KEYS), delay=countdown, pace=pace,
                        source=source)


def _produced(k: str, leads: list[dict], res: dict, demo: bool) -> str:
    """What one step PRODUCED, in words: not how many leads it looked at."""
    v = lambda col, *vals: sum(1 for x in leads if x[col]["value"] in vals)   # noqa: E731
    has = lambda col: sum(1 for x in leads if x[col]["value"])               # noqa: E731
    if k == "find":            # step 1: every lead searched so far, website or not (2026-11-07);
        # leads waiting for a later run (the per-run limit) are not counted as "in"
        got = v("email", *FOUND_EMAIL)
        return f"{has('email')} in → {got} emails found · {has('email') - got} not found"
    if k == "research":        # step 2: only the leads that got an email
        mailed = [x for x in leads if x["email"]["value"] in FOUND_EMAIL]
        read = sum(1 for x in mailed if x["website"]["value"] == "found")
        looked = sum(1 for x in mailed if x["website"]["value"])
        return f"{len(mailed)} in → {read} websites read · {looked - read} no site or not readable"
    if k == "ice":
        got = v("ice", "written")
        floor = int((res.get("ice") or {}).get("default") or 0)
        sheet = int((res.get("ice") or {}).get("from_sheet") or 0)
        return (f"{v('email', *FOUND_EMAIL)} in → {got} written · {floor} from the Default line"
                + (f" · {sheet} already in the sheet" if sheet else ""))
    if k == "email":
        e = res.get("email") or {}
        live = int(e.get("live") or 0)
        return f"{live} template{'s' if live != 1 else ''} live · {int(e.get('prepared') or 0)} leads matched"
    if k == "send":
        word = "queued (test)" if demo else "pushed to Draft"
        return f"{v('sent', 'pushed', 'pushed_by_hand')} {word} · {v('sent', 'held')} held"
    n = has("reply")
    return f"{n} repl{'y' if n == 1 else 'ies'}" + ("" if demo or n else " (campaign is Draft)")


def _demo_leads(st, p) -> list[dict]:
    rows = st.overlay(p["rows"], p["store_source"], p["fm"].header("row_key") or "lead_id")
    pushes = st.pushes(p["store_source"])
    tnames = {t["id"]: t["name"] for t in st.templates(p["store_source"])}
    out = []
    for r in rows:
        key = str(p["fm"].get(r, "row_key"))
        tid = (pushes.get(key) or {}).get("template_id")
        out.append({"key": key, "company": str(p["fm"].get(r, "company_name") or ""),
                    "website": stack_mod.pill("website_status", r.get("website_status", "")),
                    "email": stack_mod.pill("email_status", r.get("email_status", "")),
                    "ice": stack_mod.pill("icebreaker_status", r.get("icebreaker_status", "")),
                    "template": tnames.get(tid, "") if r.get("push_status") == "pushed" else "",
                    "sent": stack_mod.pill("push_status", r.get("push_status", "")),
                    "reply": stack_mod.pill("reply_status", r.get("reply_status", ""))})
    return out


def stack_demo_status(now: datetime | None = None, source: str = "demo") -> dict:
    st, p = _stack_store(), _stack_parts(source)
    now = now or datetime.now()
    runs = [r for r in st.runs(p["store_source"]) if r["trigger"] in RUN_TRIGGERS]
    run = runs[0] if runs else None
    leads = _demo_leads(st, p)
    col = {"research": "website", "find": "email", "ice": "ice", "send": "sent", "replies": "reply"}
    res = (run or {}).get("result") or {}
    chain = []
    for i, (k, label) in enumerate(ssched_mod.STEPS):
        if k == "email":
            n = int((res.get("email") or {}).get("prepared") or 0)
        else:
            n = sum(1 for x in leads if x[col[k]]["value"])
        state = "pending"
        if run:
            if run["state"] == "done" or i < int(run["step"] or 0):
                state = "done"
            elif run["state"] == "running" and i == int(run["step"] or 0):
                state = "run"
            elif run["state"] == "waiting" and i == int(run["step"] or 0):
                state = "waiting"
        chain.append({"key": k, "label": label, "n": n, "state": state,
                      "text": _produced(k, leads, res, p["demo"]) if state != "pending" else ""})
    out = {"run": None, "chain": chain, "leads": leads, "total": len(leads), "progress": 0, "result": None,
           "source": source, "name": p["name"], "demo": p["demo"]}
    if not run:
        return out
    due = datetime.fromisoformat(run["due"]) if run.get("due") else now
    done_steps = sum(1 for c in chain if c["state"] == "done")
    out["progress"] = 100 if run["state"] == "done" else round(100 * done_steps / len(chain))
    out["run"] = {"id": run["id"], "state": run["state"], "step": run["step"], "due": f"{due:%H:%M:%S}",
                  "seconds_left": max(0, int((due - now).total_seconds() + 0.999)) if run["state"] == "scheduled" else 0,
                  "message": run.get("message", ""), "events": list(reversed(run["events"]))[:200],
                  "started": run.get("started", ""), "finished": run.get("finished", "")}
    if run["state"] == "done":
        c = _demo_counts(st, p)
        secs = 0
        if run.get("started") and run.get("finished"):
            secs = int((datetime.fromisoformat(run["finished"]) - datetime.fromisoformat(run["started"])).total_seconds())
        out["result"] = {"seconds": secs, "leads": c["leads"], "websites": c["websites"], "emails": c["emails"],
                         "sent": c["sent"], "interested": c["interested"],
                         "would_cost": float((res.get("find") or {}).get("would_cost") or 0),
                         "summary": st.latest_summary(p["store_source"])}
    return out


# ── the pages ──
def _jobs(st) -> dict:
    return ssched_mod.all_jobs(st.setting("stack_schedules"))


def stack_schedules(now: datetime | None = None) -> dict:
    st = _stack_store()
    now = now or datetime.now()
    jobs = _jobs(st)
    rows = []
    for r in _active_runs(st):
        due = datetime.fromisoformat(r["due"])
        left = max(0, int((due - now).total_seconds() + 0.999))
        try:
            who = _stack_parts(r["source"])["name"]
        except Exception:  # noqa: BLE001
            who = ""
        rows.append({"job": "demo-run", "step": f"Pipeline run · {who}" if who else "Pipeline run", "trigger": "time",
                     "schedule": f"Once at {due:%H:%M:%S}",
                     "next": f"In {left} seconds" if r["state"] == "scheduled" else "Running now",
                     "enabled": True, "demo": True, "raw": None, "can_follow": False})
    for k in ssched_mod.JOBS:
        j = jobs[k]
        n = ssched_mod.STEP_KEYS.index(k) + 1 if k in ssched_mod.STEP_KEYS else 0
        rows.append({"job": k, "step": f"{n} · {ssched_mod.LABEL[k]}" if n else ssched_mod.LABEL[k],
                     "trigger": j["trigger"], "schedule": ssched_mod.words(j),
                     "next": ssched_mod.next_words(k, j, now), "enabled": j["enabled"], "demo": False,
                     "raw": j.get("schedule"), "can_follow": ssched_mod.can_follow(k)})
    clock = os.environ.get("LEADGEN_NO_SCHEDULER") != "1"
    camps = []
    for src in _run_sources():
        try:
            camps.append({"id": src, "name": _stack_parts(src)["name"], "demo": src == demo_mod.DEMO_SOURCE})
        except Exception:  # noqa: BLE001 - an unreadable sheet is left out of the picker
            continue
    return {"rows": rows, "campaigns": camps, "source": _sched_source(st), "later": _later(_live_campaign_count()),
            "approvals": stack_approvals_get(), "clock_on": clock,
            "clock_text": "" if clock else "The app clock is off in this test engine, so no step starts by itself. "
                                           "A pipeline run still starts: its trigger is a one-time job."}


def stack_schedules_save(job: str, body: dict) -> dict:
    st = _stack_store()
    try:
        clean = ssched_mod.clean(job, body)
    except ssched_mod.ScheduleError as e:
        return {"ok": False, "error": str(e)}
    saved = dict(st.setting("stack_schedules") or {})
    saved[job] = clean
    st.set_setting("stack_schedules", saved)
    last = dict(st.setting("stack_last_fire") or {})
    last[job] = _stamp().replace(" ", "T")        # count from now: saving never fires an old slot
    st.set_setting("stack_last_fire", last)
    return {"ok": True, **stack_schedules()}


def _sched_source(st) -> str:
    """The campaign the per-step schedules run on (chosen on Schedules). The sample firms
    until he picks one: a schedule never starts spending on a real campaign by itself."""
    src = str(st.setting("stack_schedule_source") or "")
    return src if src in _run_sources() else demo_mod.DEMO_SOURCE


def stack_schedules_source(source: str) -> dict:
    if source not in _run_sources():
        return {"ok": False, "error": "This campaign cannot run the pipeline. Turn on “Run in the 6-step pipeline” on its page first."}
    _stack_store().set_setting("stack_schedule_source", source)
    return {"ok": True, **stack_schedules()}


def stack_tick(now: datetime | None = None, *, wait: bool = False) -> list[str]:
    """The app clock's look at the per-step schedules (every 30 s, only when the clock is on).
    Returns the jobs it fired."""
    st = _stack_store()
    src = _sched_source(st)
    now = now or datetime.now()
    jobs = _jobs(st)
    last = dict(st.setting("stack_last_fire") or {})
    for k in ssched_mod.JOBS:
        last.setdefault(k, now.isoformat(timespec="seconds"))
    due = ssched_mod.due_jobs(jobs, last, now)
    for k, slot in due:
        last[k] = slot.isoformat(timespec="seconds")
    st.set_setting("stack_last_fire", last)
    fired = []
    for k, _slot in due:
        if k == "health":
            _health_check(st, source=src)
        elif k == "summary":
            _write_summary(st, now.date(), source=src)
        else:
            r = _start_chain(st, f"Schedule: {ssched_mod.LABEL[k]} ({ssched_mod.words(jobs[k])})",
                             ssched_mod.chain(jobs, k), wait=wait, source=src)
            if not r.get("ok"):
                _sched_log(f"stack {k}: not started — {r.get('error')}")
                continue
        fired.append(k)
    return fired


def stack_health(now: datetime | None = None) -> dict:
    st = _stack_store()
    now = now or datetime.now()
    src = _home_source(st)
    inc = st.incidents(src)
    log = [{"id": i["id"], "time": str(i["at"])[11:16], "day": str(i["at"])[:10], "step": i["step"],
            "issue": i["issue"], "action": i["action"], "result": i["result"]} for i in reversed(inc)]
    clock = os.environ.get("LEADGEN_NO_SCHEDULER") != "1"
    return {"tiles": health_mod.tiles(inc, now.date()), "log": log[:100],
            "allowed": list(dict.fromkeys(health_mod.ALLOWED.values())), "escalated": health_mod.ESCALATED_LIST,
            "summary": st.latest_summary(src), "source": src,
            "last_check": st.setting(f"health_last_check:{src}", ""), "clock_on": clock,
            "clock_text": "" if clock else "The app clock is off in this test engine. The health agent checks at "
                                           "the end of every pipeline run instead of every 5 minutes."}


def _home_source(st) -> str:
    """The source Home and Health report on: the real campaign with the newest pipeline run.
    The sample firms only when no real campaign has run (2026-11-07: a production app shows
    his campaigns, never the sample set). Its store key is also its picker id."""
    best = ("", demo_mod.DEMO_SOURCE)
    for src in _run_sources()[1:]:
        runs = st.runs(src)
        if runs:
            when = str(runs[0].get("started") or runs[0].get("due") or "")
            best = max(best, (when, src))
    if best[0]:
        return best[1]
    for src in _run_sources():
        runs = st.runs(src)
        if runs:
            when = str(runs[0].get("started") or runs[0].get("due") or "")
            best = max(best, (when, src))
    return best[1]


def stack_decisions() -> dict:
    st = _stack_store()
    src = _home_source(st)
    inc = st.incidents(src)
    p = _stack_parts(src)
    return {"decisions": stack_decisions_list(st, src), "health": health_mod.tiles(inc, _date.today()),
            "counts": _demo_counts(st, p), "presenting": stack_presenting_get()["on"],
            "source": src, "name": p["name"], "demo": p["demo"]}


@app.get("/api/stack/presenting")
def api_stack_presenting():
    return stack_presenting_get()


@app.post("/api/stack/presenting")
async def api_stack_presenting_set(request: Request):
    b = await request.json()
    return stack_presenting_set(bool(b.get("on")))


@app.get("/api/stack/schedules")
def api_stack_schedules():
    return stack_schedules()


@app.post("/api/stack/schedules/save")
async def api_stack_schedules_save(request: Request):
    b = await request.json()
    return stack_schedules_save(str(b.get("job") or ""), b)


@app.post("/api/stack/schedules/source")
async def api_stack_schedules_source(request: Request):
    return stack_schedules_source(str((await request.json()).get("source") or ""))


@app.post("/api/stack/approvals")
async def api_stack_approvals(request: Request):
    return stack_approvals_set(await request.json())


@app.get("/api/stack/health")
def api_stack_health():
    return stack_health()


@app.get("/api/stack/decisions")
def api_stack_decisions():
    return stack_decisions()


@app.get("/api/stack/demo/status")
def api_stack_demo_status(source: str = "demo"):
    try:
        return stack_demo_status(source=source)
    except Exception as e:  # noqa: BLE001
        return {"error": _plain_read_error(e)}


@app.post("/api/stack/demo/start")
def api_stack_demo_start():
    return stack_demo_start()


@app.post("/api/stack/run/start")
async def api_stack_run_start(request: Request):
    b = await request.json()
    return stack_run_start(str(b.get("source") or "demo"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8771)
