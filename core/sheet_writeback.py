"""
sheet_writeback.py — the 6-step pipeline writes its results back to the campaign's Google
Sheet (2026-11-07, his yes). Before this, results stayed only in the app database.

Three columns, one row per lead (matched on the row key, e.g. lead_id):
  Found Email   the address Find email found              — written only into an EMPTY cell
  Ice Breaker   the line Ice breakers wrote               — written only into an EMPTY cell
                (the column the field map uses for `icebreaker`, when the sheet has one)
  Status        "Added to Instantly (Draft) 2026-11-07", "Held: …", "No email found",
                "Push failed" — written into an empty cell, or over a value THIS module wrote
                before (so "Held" can become "Added"); anything a person typed is left alone

Missing columns are added at the end of the header row. No row is ever deleted or moved.
`plan()` is pure (testable offline); `apply()` talks to Google.
"""
from __future__ import annotations

import time

from . import icebreakers as ICE
from . import lead_record as LR

FOUND = "Found Email"
ICE_COL = "Ice Breaker"
STATUS = "Status"
OURS = ("Added to Instantly", "Held:", "No email found", "Push failed")
NO_EMAIL = ("no_email", "no_person", "no_website")


def _ice_header(fm, header: list[str]) -> str:
    h = fm.header("icebreaker") if fm is not None else ""
    if h and h in header:
        return h
    for alias in ("Ice Breaker", "Icebreaker", "ice_breaker"):
        if alias in header:
            return alias
    return ICE_COL


def status_for(s: dict, push: dict) -> str:
    """The Status words for one lead ('' = nothing to say yet)."""
    state = str(push.get("state") or s.get("push_status") or "")
    if state in ("pushed", "pushed_by_hand"):
        day = str(push.get("pushed_on") or "")[:10]
        return f"Added to Instantly (Draft){' ' + day if day else ''}"
    if state == "held":
        return f"Held: {push.get('reason') or 'not ready'}"
    if state == "failed":
        return "Push failed"
    if s.get("email_status") in NO_EMAIL:
        return "No email found"
    return ""


def plan(header: list[str], rows: list[dict], fm, store, source: str) -> dict:
    """What to write: {"add": [new headers], "cells": [(row_index, header, value)]}.
    `rows` are the sheet's rows in sheet order (row_index 0 = sheet row 2)."""
    key_h = fm.header("row_key") or "lead_id"
    ice_h = _ice_header(fm, header)
    stored, emails = store.statuses(source), store.email_results(source)
    lines, pushes = store.icebreakers(source), store.pushes(source)
    add = [h for h in (FOUND, ice_h, STATUS) if h not in header]
    cells = []
    for i, row in enumerate(rows):
        key = str(row.get(key_h, "")).strip()
        if not key or key not in stored:
            continue
        s = {c: (stored.get(key) or {}).get(c, "") for c in LR.COLUMNS}
        cur = lambda h: str(row.get(h, "") or "").strip()  # noqa: E731
        email = str((emails.get(key) or {}).get("email") or "") if s["email_status"] in ICE.USABLE_EMAIL else ""
        if email and not cur(FOUND):
            cells.append((i, FOUND, email))
        line = str((lines.get(key) or {}).get("line") or "") if s["icebreaker_status"] == "written" else ""
        if line and not cur(ice_h):
            cells.append((i, ice_h, line))
        words = status_for(s, pushes.get(key) or {})
        now = cur(STATUS)
        if words and words != now and (not now or now.startswith(OURS)):
            cells.append((i, STATUS, words))
    return {"add": add, "cells": cells}


def col_letter(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def apply(client, doc_id: str, tab: str, fm, store, source: str, *, tries: int = 3, sleep=time.sleep) -> dict:
    """Read the tab, add missing columns, write the planned cells in one batch. A refused
    write (Google's per-minute limit) is tried again, up to `tries` times."""
    from .sheets import a1_tab
    svc = client._svc
    header = client._header(doc_id, tab)
    rows = client.read(doc_id, tab)
    p = plan(header, rows, fm, store, source)
    if not p["cells"]:
        return {"ok": True, "cells": 0, "added_columns": []}
    full = header + [h for h in p["add"]]
    if p["add"]:
        meta = svc.spreadsheets().get(spreadsheetId=doc_id, fields="sheets.properties").execute()
        prop = next(s["properties"] for s in meta["sheets"] if s["properties"]["title"] == tab)
        have = int((prop.get("gridProperties") or {}).get("columnCount") or 26)
        if len(full) > have:
            svc.spreadsheets().batchUpdate(spreadsheetId=doc_id, body={"requests": [{"appendDimension": {
                "sheetId": prop["sheetId"], "dimension": "COLUMNS", "length": len(full) - have}}]}).execute()
    data = [{"range": f"{a1_tab(tab)}!{col_letter(len(header) + j)}1", "values": [[h]]} for j, h in enumerate(p["add"])]
    data += [{"range": f"{a1_tab(tab)}!{col_letter(full.index(h))}{i + 2}", "values": [[v]]} for i, h, v in p["cells"]]
    for attempt in range(tries):
        try:
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=doc_id, body={"valueInputOption": "RAW", "data": data}).execute()
            break
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1 or "429" not in str(e):
                raise
            sleep(20 * (attempt + 1))
    return {"ok": True, "cells": len(p["cells"]), "added_columns": p["add"]}
