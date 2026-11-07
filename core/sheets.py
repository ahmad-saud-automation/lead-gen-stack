"""
sheets.py — Google Sheets source + status write-back (V7's "Load Endole Lead List"
and "Update Sheet — Pushed to Instantly").

Two access paths, so reading works with zero setup:

  1. CSV export (read-only, NO credentials) — works when the sheet is shared
     "anyone with the link can view". Just paste the sheet URL.
  2. Service account (read + WRITE) — needed to write statuses back. Requires
     `google-auth` + `google-api-python-client` and a service-account JSON whose
     client_email is shared as an Editor on the sheet.

`update_statuses` matches rows by Company Name (V7's key) and writes only the V7
columns, leaving every other column untouched.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.request

from . import emailgen
from . import lead_record
from . import net

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# The columns V7 writes back after a successful push.
#
# Matches northwind/docs/15-google-sheet-architecture.md (2026-08-31):
#   * "Selected Director" is now "Contact Name" — most of these people are not directors.
#   * "send_ready" and "mv_date" are new. Nothing may be pushed unless send_ready = yes;
#     mv_date exists because B2B email decays about 2% a month.
#   * The Oldest / Youngest / Director 1-3 slots are GONE. The sheet carries exactly one
#     backup person ("Contact 2 ..."), released by hand through verify_contact_2, so
#     MillionVerifier can never auto-spend on a second contact.
#
# Only columns present in the sheet header are written, so a name that does not match is
# silently dropped — keep this list and the sheet in step.
WRITEBACK_COLUMNS = [
    "Status", "Final Status", "send_ready",
    "Found Email", "Contact Name", "Email Source", "Email Type",
    "Verification Status", "mv_date", "Alternate Emails",
    "Campaign Type", "Ice Breaker",
    "Contact 2 Email",
    "email_status",     # Find email's own column (core/lead_record.py), 2026-11-06
]

# The same list, as V7 column name -> engine field. `to_sheet_row` uses it to rewrite a
# write-back row into whatever the target sheet actually calls those columns, so the
# engine can write to a sheet that uses none of V7's names.
WRITEBACK_FIELDS = {
    "Status": "status", "Final Status": "final_status", "send_ready": "send_gate",
    "Found Email": "found_email", "Contact Name": "contact_name",
    "Email Source": "email_source", "Email Type": "email_type",
    "Verification Status": "verification_status", "mv_date": "mv_date",
    "Alternate Emails": "alternate_emails", "Campaign Type": "campaign_type",
    "Ice Breaker": "icebreaker", "Contact 2 Email": "contact_2_email",
}


def to_sheet_row(row: dict, fm) -> dict:
    """A V7-named write-back row -> the real headers in YOUR sheet.

    An engine field the map does not resolve is DROPPED, deliberately. Writing to a
    column that does not exist is silently discarded by Google Sheets — no error, just a
    blank cell — so a missing mapping must fail loudly at validate time, never quietly
    here."""
    out: dict = {}
    for v7_name, field in WRITEBACK_FIELDS.items():
        if v7_name not in row:
            continue
        header = fm.header(field)
        if header:
            out[header] = row[v7_name]
    if "email_status" in row:
        out[lead_record.header(fm, "email_status")] = row["email_status"]
    key_header = fm.header("row_key")
    if key_header:
        out[key_header] = (row.get("lead_id") or row.get("row_key")
                           or row.get("Company Name") or "")
    return out


def writeback_headers(fm) -> list[str]:
    """Every sheet header this map allows the engine to write."""
    heads = [fm.header(f) for f in WRITEBACK_FIELDS.values()]
    heads.append(lead_record.header(fm, "email_status"))
    return [h for h in heads if h]


def parse_sheet_url(url: str) -> dict:
    """Pull the document id and gid out of any Google Sheets URL (or accept a bare id)."""
    s = str(url or "").strip()
    doc = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    gid = re.search(r"[#&?]gid=(\d+)", s)
    if not doc and re.fullmatch(r"[a-zA-Z0-9-_]{20,}", s):
        return {"doc_id": s, "gid": ""}
    return {"doc_id": doc.group(1) if doc else "", "gid": gid.group(1) if gid else ""}


def csv_export_url(doc_id: str, gid: str = "") -> str:
    u = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv"
    return u + (f"&gid={gid}" if gid else "")


def read_via_csv_export(doc_id: str, gid: str = "", *, timeout: int = 30, opener=None) -> list[dict]:
    """Read rows with no credentials — requires the sheet to be link-viewable."""
    url = csv_export_url(doc_id, gid)
    if opener:
        text = opener(url)
    else:
        with urllib.request.urlopen(urllib.request.Request(url, headers=net.headers()),
                                    timeout=timeout) as r:
            if "text/csv" not in (r.headers.get("Content-Type") or "") and r.geturl().find("accounts.google.com") != -1:
                raise PermissionError("Sheet is not link-viewable — share it or use a service account.")
            text = r.read().decode("utf-8-sig", "replace")
    if text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:400].lower():
        raise PermissionError("Sheet is not link-viewable — share it (Anyone with link) or use a service account.")
    return [{(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))]


# ── service-account client (read + write) ────────────────────────────

def a1_tab(tab: str) -> str:
    """A tab name as A1 notation wants it: always quoted, inner quotes doubled.

    Unquoted, a name with a space at the end ("Construction ", "Clinics " in the Northwind sheet) or
    other punctuation fails with 400 "Unable to parse range" (found 2026-10-05). Quoting is
    always valid, so every range is built through here."""
    return "'" + str(tab).replace("'", "''") + "'"


class SheetsClient:
    """Thin wrapper over the Sheets REST API using a service-account JSON."""

    def __init__(self, service_account_file: str):
        try:
            from google.oauth2 import service_account  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as e:  # noqa: BLE001
            raise RuntimeError(
                "Writing to Google Sheets needs the Google libraries. Install them with:\n"
                "  pip install google-auth google-api-python-client"
            ) from e
        creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        self._svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.client_email = getattr(creds, "service_account_email", "")

    def read(self, doc_id: str, tab: str = "Combined") -> list[dict]:
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=doc_id, range=a1_tab(tab)).execute()
        values = res.get("values", [])
        if not values:
            return []
        header = [str(h).strip() for h in values[0]]
        rows = []
        for raw in values[1:]:
            padded = list(raw) + [""] * (len(header) - len(raw))
            rows.append({header[i]: padded[i] for i in range(len(header))})
        return rows

    def info(self, doc_id: str) -> dict:
        """The spreadsheet's title and its tab names — one metadata read, no cell data."""
        res = self._svc.spreadsheets().get(
            spreadsheetId=doc_id, fields="properties.title,sheets.properties.title").execute()
        return {"title": (res.get("properties") or {}).get("title", ""),
                "tabs": [s["properties"]["title"] for s in res.get("sheets", [])
                         if (s.get("properties") or {}).get("title")]}

    def _header(self, doc_id: str, tab: str) -> list[str]:
        res = self._svc.spreadsheets().values().get(spreadsheetId=doc_id, range=f"{a1_tab(tab)}!1:1").execute()
        return [str(h).strip() for h in (res.get("values") or [[]])[0]]

    def open_writer(self, doc_id: str, tab: str, key_column: str = "Company Name",
                    allowed: list | None = None):
        """Read the header + row index ONCE, then write rows one at a time as each
        lead is pushed — same live behaviour as n8n's per-item Update Sheet node.

        `allowed` is the write allow-list. Defaults to V7's fixed column names; pass
        `writeback_headers(fm)` to write to a sheet that uses its own names."""
        writable = set(allowed if allowed is not None else WRITEBACK_COLUMNS)
        header = self._header(doc_id, tab)
        if key_column not in header:
            raise ValueError(f"'{key_column}' column not found in tab '{tab}'")
        rows = self.read(doc_id, tab)
        norm = lambda v: re.sub(r"\s+", " ", str(v or "").strip().lower())
        index = {norm(r.get(key_column)): i for i, r in enumerate(rows)}
        cols = {c: i for i, c in enumerate(header)}

        def col_letter(i: int) -> str:
            return chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26)

        def write_row(update: dict) -> dict:
            """Push one row's V7 columns to the sheet immediately."""
            row_i = index.get(norm(update.get(key_column)))
            if row_i is None:
                return {"ok": False, "reason": "row not found", "key": update.get(key_column)}
            sheet_row = row_i + 2                       # +1 header, +1 for 1-based rows
            data = [{"range": f"{a1_tab(tab)}!{col_letter(cols[c])}{sheet_row}", "values": [[v]]}
                    for c, v in update.items()
                    if c != key_column and c in writable and c in cols]
            if not data:
                return {"ok": False, "reason": "no writable columns"}
            self._svc.spreadsheets().values().batchUpdate(
                spreadsheetId=doc_id,
                body={"valueInputOption": "RAW", "data": data}).execute()
            return {"ok": True, "row": sheet_row, "cells": len(data)}

        return write_row

    def update_statuses(self, doc_id: str, tab: str, updates: list[dict],
                        key_column: str = "Company Name", allowed: list | None = None) -> dict:
        """updates = [{'Company Name': ..., 'Status': ..., ...}]. Matches existing rows by
        key_column and writes only allowed columns that exist in the sheet header.
        `allowed` defaults to V7's names; pass `writeback_headers(fm)` for your own."""
        writable = set(allowed if allowed is not None else WRITEBACK_COLUMNS)
        header = self._header(doc_id, tab)
        if key_column not in header:
            return {"ok": False, "error": f"'{key_column}' column not found in {tab}", "updated": 0}
        rows = self.read(doc_id, tab)
        norm = lambda v: re.sub(r"\s+", " ", str(v or "").strip().lower())
        index = {norm(r.get(key_column)): i for i, r in enumerate(rows)}
        col_letter = lambda i: (chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26))

        data, updated, missing = [], 0, []
        for up in updates:
            row_i = index.get(norm(up.get(key_column)))
            if row_i is None:
                missing.append(up.get(key_column))
                continue
            sheet_row = row_i + 2                      # +1 header, +1 to 1-based
            for col, val in up.items():
                if col == key_column or col not in writable or col not in header:
                    continue
                a1 = f"{a1_tab(tab)}!{col_letter(header.index(col))}{sheet_row}"
                data.append({"range": a1, "values": [[val]]})
            updated += 1
        if data:
            self._svc.spreadsheets().values().batchUpdate(
                spreadsheetId=doc_id,
                body={"valueInputOption": "RAW", "data": data}).execute()
        return {"ok": True, "updated": updated, "cells": len(data), "not_found": missing}


def rung_index(label: str) -> str:
    """A rung label -> what goes in his `final_contact_index` column.

    The label is the only thing that knows which contact won, so it carries the answer
    in plain sight: "as-is contact 3" -> "3", "fallback email column" -> "fallback".
    Anything else returns blank rather than a guess."""
    s = str(label or "").strip().lower()
    digits = re.search(r"\d+", s)
    if digits:
        return digits.group(0)
    return "fallback" if "fallback" in s else ""


def rung_source(label: str) -> str:
    """A rung label -> what goes in his `final_email_source` column: the label's first
    word, which every rung in the Organized recipe starts with on purpose
    ('as-is contact 1', 'enriched contact 1', 'fallback email column')."""
    return str(label or "").strip().split(" ")[0].lower()


def build_recipe_writeback_row(result: dict, recipe, *, key_header: str = "") -> dict:
    """A Finding Recipe's result -> ONLY the columns that recipe may write.

    These keys are the sheet's REAL headers, the ones the recipe itself names, so this
    does not go through `to_sheet_row`: a recipe already speaks the sheet's own language.

    ⛔ THIS IS THE GUARD ON HIS SHEET. `Contact Name` and `Email Source` cannot be reached
    from here at all, which is what stops the old write-back overwriting the columns he
    fills by hand. The writer is opened with the same headers as its allow-list, so even
    a bug in here cannot put anything in a column the recipe did not name.

    Four columns always, plus `index_to` / `first_name_to` when the recipe asks for them.
    With `words: "source"` the method and status columns are written in his sheet's own
    vocabulary — as-is / enriched / fallback, and no_email when a row finds nothing —
    taken from the winning rung's label, never from the finder's internal words.

    The two rules from `build_writeback_row` still hold: a lead that found nothing writes
    only its status, and a blank is never written over something already there.
    """
    t = recipe.write_targets()
    email = str(result.get("found_email") or "").strip()
    if not email and recipe.write_when == "on_find":
        return {}                     # "only when something is found"
    plain = recipe.write_words == "source"
    rung = str(result.get("found_rung") or "")
    # ⛔ 2026-11-06: `status_to` is Find email's own `email_status` column, written in the
    # shared vocabulary (core/lead_record.py) whatever `words` says. It used to carry the
    # engine word ('email_found') into `Status`, which Icebreaker Studio reads as "finished".
    status = lead_record.email_status_for(result)
    out = {
        key_header or "lead_id": result.get("lead_id") or result.get("row_key") or "",
        t["status_to"]: status,
    }
    if email:
        words = emailgen.spoken_words(result.get("contact_name") or "")
        out[t["email_to"]] = email
        # `found_for` is "Ian Smith (as-is contact 1)" - right for his Found For column,
        # wrong for final_contact_name, which holds the person and nothing else.
        out[t["person_to"]] = (" ".join(words) if plain
                               else (result.get("found_for") or ""))
        out[t["method_to"]] = rung_source(rung) if plain else (result.get("found_by") or "")
        if "index_to" in t:
            out[t["index_to"]] = rung_index(rung)
        if "first_name_to" in t:
            out[t["first_name_to"]] = words[0] if words else ""
    out = {k: v for k, v in out.items() if str(v or "").strip() != ""}
    return lead_record.guard("find_email", out, key_header=key_header or "lead_id")


def build_writeback_row(result: dict, status: str, *, write_icebreaker: bool = True,
                        stage: str = "sending") -> dict:
    """One result row -> the sheet update payload.

    `stage="find_email"` is the run's own write (no_website / not found / held): it writes
    `email_status` (core/lead_record.py) and NEVER `Status` / `Final Status`. The default,
    "sending", is the push's write and is unchanged until build session 2 moves it to
    `push_status`.

    `write_icebreaker=False` for campaign lanes: the Ice Breaker column belongs to
    Icebreaker Studio, and the engine must never write over its line (decided 2026-09-29).

    Matches docs/15-google-sheet-architecture.md. `send_ready` is the send gate: only a
    MillionVerifier PASS sets it to yes, so an address that was merely guessed can never
    be pushed. `Contact 2 Email` is filled only when the row was released by hand.

    ⛔ THE ENGINE ONLY EVER ADDS INFORMATION. Two rules, both learned the hard way on
    2026-09-06 when a live run wiped two paid-for `apollo_old` addresses:

      1. A lead that found NOTHING writes only its status. A failed search tells us our
         attempt failed — it tells us nothing about the address already on the row, so
         that address, its source, its verification and its ice breaker are left alone.
      2. A blank value is never written over anything. Empty means "we did not learn
         this", not "delete what is there".
    """
    src = result.get("email_source") or "selected"
    email = str(result.get("found_email") or "").strip()
    ver = result.get("verification", "")
    accepted = bool(result.get("accepted", email and str(ver).strip().lower() in
                               ("good", "ok", "valid", "deliverable", "verified")))

    if stage == "find_email":
        row = _legacy_row(result, status, email, src, ver, accepted, write_icebreaker)
        row.pop("Status", None)
        row.pop("Final Status", None)
        row["email_status"] = lead_record.email_status_for({**result, "status": status})
        return lead_record.guard("find_email", row, key_header="lead_id")
    return _legacy_row(result, status, email, src, ver, accepted, write_icebreaker)


def _legacy_row(result, status, email, src, ver, accepted, write_icebreaker) -> dict:
    if not email:
        # nothing was found: record the attempt and touch nothing else
        out = {
            "lead_id": result.get("lead_id", "") or result.get("row_key", ""),
            "Company Name": result.get("company", ""),
            "Status": status, "Final Status": status,
        }
        camp = str(result.get("campaign_type") or "").strip()
        if camp:
            out["Campaign Type"] = camp
        return out

    row = {
        # lead_id carries the sheet's own key when there is one; to_sheet_row reads it
        "lead_id": result.get("lead_id", "") or result.get("row_key", ""),
        "Company Name": result.get("company", ""),
        "Status": status, "Final Status": status,
        "send_ready": "yes" if accepted else "no",
        "Found Email": email,
        "Contact Name": result.get("contact_name")
                        or result.get("selected_director", ""),
        "Email Source": src,
        "Email Type": result.get("email_type", "director"),
        "Verification Status": ver,
        "mv_date": result.get("mv_date", ""),
        "Alternate Emails": result.get("alternate_emails", ""),
        "Campaign Type": result.get("campaign_type", "director_main_campaign"),
        "Ice Breaker": result.get("icebreaker", "") if write_icebreaker else "",
        "Contact 2 Email": result.get("contact_2_email", ""),
    }
    # rule 2: never write a blank over something that is already there
    # (which is also what keeps Studio's line: a blank Ice Breaker is dropped here)
    return {k: v for k, v in row.items() if str(v or "").strip() != ""}
