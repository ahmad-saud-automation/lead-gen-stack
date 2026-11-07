"""
imports.py — a CSV becomes a tab a lane can read.

V1 took one CSV straight into one run. A lane reads a TAB, so an upload is registered as a
tab of its own, `import:<slug>`, and every lane, the plan and the field map read it exactly
like a sheet tab. Nothing about the rules, the ledger or the push changes.

Two things differ from a sheet tab, on purpose:
  * there is no sheet to write back to, so the run and the push skip write-back and say so;
  * a CSV usually has no Status column, which the engine requires (blank = process it).
    The upload adds an empty one, so every row starts as "not done yet".

The registry is its own file (data/imports/index.json), not `local_tabs`: Settings saves
`local_tabs` whole, so keeping imports there would let a Settings save drop them.

Everything here is pure except `save_upload` / `load_index` / `save_index`, which take the
folder as an argument so tests can point them at a temp dir.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

from . import fieldmap as fieldmap_mod
from . import organize as organize_mod

PREFIX = "import:"
STATUS_COL = "Status"
MAX_BYTES = 50 * 1024 * 1024        # 50 MB — far beyond any lead list, small enough to refuse junk


def is_import_tab(tab: str) -> bool:
    return str(tab or "").startswith(PREFIX)


def slug_for(filename: str, taken) -> str:
    """'Leads — London (2).csv' -> 'leads-london-2', made unique against `taken`."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(filename or "").strip())
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48] or "import"
    taken = set(taken or ())
    s, n = base, 2
    while s in taken:
        s = f"{base}-{n}"
        n += 1
    return s


def parse_csv(raw: bytes) -> tuple[list[str], list[dict]]:
    """(headers, rows). Same delimiter sniffing as V1's upload, so a file that worked there
    works here. Blank header cells are dropped; fully blank rows are skipped."""
    text = raw.decode("utf-8-sig", "replace")
    sample = text[:4096]
    delim = ","
    if sample.count(";") > sample.count(",") and sample.count(";") > sample.count("\t"):
        delim = ";"
    elif sample.count("\t") > sample.count(","):
        delim = "\t"
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    rows = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() if isinstance(v, str) else "" for k, v in row.items()
                 if (k or "").strip()}
        if any(clean.values()):
            rows.append(clean)
    return headers, rows


def with_status(headers: list[str], rows: list[dict]) -> tuple[list[str], list[dict], bool]:
    """Add an empty Status column when the file has none -> (headers, rows, added)."""
    if any(h.strip().lower() == STATUS_COL.lower() for h in headers):
        return headers, rows, False
    return headers + [STATUS_COL], [{**r, STATUS_COL: ""} for r in rows], True


def to_csv_bytes(headers: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({h: r.get(h, "") for h in headers})
    return buf.getvalue().encode("utf-8")


def stats(rows: list[dict], *, owned_companies=None, owned_domains=None, ledger=None,
          fm=None, retry_not_found: bool = False) -> dict:
    """What the file holds, before anything is spent on it.

    duplicates   rows whose firm (key or domain) already appeared higher up the file
    suppressed   a firm you own (Settings → suppression lists)
    in_ledger    already handled in an earlier run — a lane would skip them
    no_company   no firm name: the engine cannot work on them at all
    with_icebreaker  rows that already carry an Icebreaker Studio line
    """
    headers = _headers(rows)
    fm = (fm or fieldmap_mod.FieldMap({})).completed(headers)
    owned_c = {organize_mod._norm_company(c) for c in (owned_companies or []) if c}
    owned_d = {organize_mod.clean_domain(d) for d in (owned_domains or []) if d}
    ib_col = fm.header("icebreaker") or "Ice Breaker"

    seen_keys, seen_domains = set(), set()
    dup = sup = no_co = ib = 0
    for r in rows:
        company = fm.get(r, "company_name")
        if not company:
            no_co += 1
            continue
        key = organize_mod._norm_company(fm.get(r, "row_key") or company)
        dom = organize_mod.clean_domain(fm.get(r, "website"))
        if key in seen_keys or (dom and dom in seen_domains):
            dup += 1
        seen_keys.add(key)
        if dom:
            seen_domains.add(dom)
        if organize_mod._norm_company(company) in owned_c or (dom and dom in owned_d):
            sup += 1
        if str(r.get(ib_col) or "").strip():
            ib += 1

    in_ledger = 0
    if ledger is not None:
        _pending, in_ledger = ledger.filter_pending(rows, fm, retry_not_found=retry_not_found)

    return {"rows": len(rows), "duplicates": dup, "suppressed": sup, "in_ledger": in_ledger,
            "no_company": no_co, "with_icebreaker": ib, "has_icebreaker_column": ib_col in headers}


def _headers(rows: list[dict]) -> list[str]:
    seen, out = set(), []
    for r in rows[:50]:
        for k in r:
            if k not in seen:
                seen.add(k)
                out.append(k)
    return out


# ───────────────────────── the registry (data/imports/index.json) ─────────────────────────

def load_index(folder) -> dict:
    p = Path(folder) / "index.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_index(folder, index: dict) -> None:
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def path_for(folder, tab: str) -> Path | None:
    """The file behind an `import:<slug>` tab, or None when no such import is registered."""
    if not is_import_tab(tab):
        return None
    meta = load_index(folder).get(tab[len(PREFIX):])
    return Path(folder) / meta["file"] if meta else None


def save_upload(folder, filename: str, raw: bytes) -> dict:
    """Parse, add Status when missing, store, register -> the new import's record.
    Raises ValueError with a reason a person can act on."""
    if len(raw) > MAX_BYTES:
        raise ValueError(f"The file is {len(raw) // (1024 * 1024)} MB; the limit is "
                         f"{MAX_BYTES // (1024 * 1024)} MB.")
    if not str(filename or "").lower().endswith((".csv", ".tsv", ".txt")):
        raise ValueError("Only .csv files can be imported (export the sheet as CSV first).")
    headers, rows = parse_csv(raw)
    if not headers:
        raise ValueError("The file has no header row.")
    if not rows:
        raise ValueError("The file has a header row but no data rows.")
    headers, rows, added = with_status(headers, rows)

    folder = Path(folder)
    index = load_index(folder)
    slug = slug_for(filename, index.keys())
    fname = f"{slug}.csv"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / fname).write_bytes(to_csv_bytes(headers, rows))
    rec = {"slug": slug, "tab": PREFIX + slug, "name": str(filename), "file": fname,
           "rows": len(rows), "columns": len(headers), "status_added": added,
           "uploaded": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    index[slug] = rec
    save_index(folder, index)
    return rec


def remove(folder, slug: str, *, delete_file: bool = False) -> dict | None:
    """Unregister an import -> its old record, or None if there was none."""
    folder = Path(folder)
    index = load_index(folder)
    rec = index.pop(slug, None)
    if rec is None:
        return None
    save_index(folder, index)
    if delete_file:
        try:
            (folder / rec["file"]).unlink()
        except FileNotFoundError:
            pass
    return rec
