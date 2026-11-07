"""
privacy.py — the Privacy switch (2026-11-06; it replaced "Live demo mode").

With the switch on, every /api/stack/ answer passes through `mask()` before it leaves the
engine, so the browser never even receives the real values:

  email address      sarah.jones@smithcpa.com → s***@smithcpa.com
  person name        Sarah Jones              → Sarah J.     (only names the app knows: the
                                                              contact columns of the sources)
  client brands      Northwind · Northwind Outsourcing · Fabrikam · Contoso → removed from text,
                     "client" inside a longer word or domain (northwind.example → client.co.uk)
  firm names         unchanged (public businesses)

Only VALUES are masked, never keys. The pipeline itself runs on the real data.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
BRAND_WORD = re.compile(r"\b(?:northwind\s+outsourcing|northwind|fabrikam|contoso)\b[\s:·\-–]*", re.I)
BRAND_INSIDE = re.compile(r"northwind|fabrikam|contoso", re.I)
NAME_COLUMNS = ("contact_1_name", "contact_2_name", "contact_name", "person_name", "director",
                "selected_director", "found_for")


def short_name(full: str) -> str:
    parts = [p for p in re.split(r"\s+", str(full or "").strip()) if p]
    if len(parts) < 2:
        return str(full or "")
    return f"{parts[0]} {parts[-1][0]}."


def names_from_rows(rows) -> list[str]:
    """Full person names held in the rows' contact columns (2+ words only)."""
    out = set()
    for r in rows or []:
        for k, v in (r or {}).items():
            if str(k).strip().lower() in NAME_COLUMNS:
                s = re.sub(r"\s+", " ", str(v or "")).strip()
                if len(s.split(" ")) >= 2:
                    out.add(s)
    return sorted(out, key=len, reverse=True)       # longest first: "Mary Ann Lee" before "Ann Lee"


def mask_text(s: str, names=()) -> str:
    if not s:
        return s
    s = EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", s)
    for n in names:
        if n in s:
            s = s.replace(n, short_name(n))
    s = BRAND_WORD.sub("", s)
    s = BRAND_INSIDE.sub("client", s)
    return s


def mask(obj, names=()):
    """A copy of `obj` (JSON-like) with every string value masked; keys untouched."""
    if isinstance(obj, str):
        return mask_text(obj, names)
    if isinstance(obj, list):
        return [mask(x, names) for x in obj]
    if isinstance(obj, dict):
        return {k: mask(v, names) for k, v in obj.items()}
    return obj
