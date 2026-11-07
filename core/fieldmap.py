"""
fieldmap.py — the column-name translator.

V1 guessed ~30 English header names inside `organize.py` (`_get(row, "Company Name",
"Organization", ...)`). That works for the Endole sheet V7 was built on and silently
half-works everywhere else: the Northwind sheet deliberately removed `Director Names`, so the
director path found nothing and fell through to a single-name fallback. It looked fine.

A FieldMap makes the translation explicit and editable:

    engine field   ->   the real header in YOUR sheet
    contact_name   ->   "Contact Name"
    seniority_rank ->   "seniority_label"

Rules:
  * An explicit mapping ALWAYS wins. If the mapped cell is blank, the value is blank —
    the engine never falls back to guessing behind your back.
  * An UNMAPPED field falls back to the V1 alias list, so an existing V7-shaped sheet
    keeps working with no map at all.
  * `validate()` reports a mapped header that does not exist in the sheet. That is the
    trap behind "a Google Sheets write to a column that does not exist is silently
    discarded" — no error, just a blank cell.
"""
from __future__ import annotations

import re

READ, WRITE, BOTH = "read", "write", "both"

# name · direction · required · aliases (V1's hard-coded guesses, preserved)
FIELDS: list[dict] = [
    {"name": "row_key", "dir": READ, "required": True,
     "aliases": ["lead_id", "Lead ID", "Reg Number", "Registration Number", "Company Name"],
     "note": "unique per row — the ledger key AND the write-back key"},
    {"name": "company_name", "dir": READ, "required": True,
     "aliases": ["Company Name", "Organization", "Organisation", "Company", "lead_company"],
     "note": "the firm"},
    {"name": "status", "dir": BOTH, "required": True,
     "aliases": ["Status"],
     "note": "the memory. blank = process it, anything = skip"},

    {"name": "reg_number", "dir": READ, "required": False,
     "aliases": ["Reg Number", "Registration Number", "Company Number", "company_number"],
     "note": "preferred dedupe key"},
    {"name": "website", "dir": READ, "required": False,
     "aliases": ["Website", "lead_website", "URL", "Domain", "Clean Website Domain", "Company Website"],
     "note": "no website = pattern guessing is skipped for that row"},
    {"name": "contact_name", "dir": BOTH, "required": False,
     "aliases": ["Contact Name", "Selected Director", "Name", "Full Name", "Director",
                 "Director Names", "Director Name", "Directors"],
     "note": "the person we email"},
    {"name": "contact_first", "dir": READ, "required": False,
     "aliases": ["First Name", "first_name", "Firstname"], "note": "derived if absent"},
    {"name": "contact_last", "dir": READ, "required": False,
     "aliases": ["Last Name", "last_name", "Surname", "Lastname"], "note": "derived if absent"},
    {"name": "job_title", "dir": READ, "required": False,
     "aliases": ["Job Title", "Title", "Role", "Position", "Seniority"],
     "note": "sent to Instantly as job_title, and used for ranking when seniority_rank is absent"},
    {"name": "seniority_rank", "dir": READ, "required": False,
     "aliases": ["seniority_label", "seniority_tier", "Seniority Label"],
     "note": "when mapped the engine TRUSTS it and does not re-rank"},
    {"name": "contact_age", "dir": READ, "required": False,
     "aliases": ["Director's Age", "Director Age", "Directors Age", "Age"],
     "note": "V7's oldest-director tie-break"},

    {"name": "send_gate", "dir": BOTH, "required": False,
     "aliases": ["send_ready", "Send Ready", "sendable"],
     "note": "must read 'yes' before anything is pushed"},
    {"name": "found_email", "dir": BOTH, "required": False,
     "aliases": ["Found Email", "Original Endole email", "Email", "found_email"],
     "note": "read as an existing candidate, overwritten on a hit"},
    {"name": "reference_email", "dir": READ, "required": False,
     "aliases": ["Company Email", "endole_raw_email", "Generic Email"],
     "note": "reference only — NEVER sent to (54% are info@)"},

    {"name": "phone", "dir": READ, "required": False,
     "aliases": ["Telephone", "Phone", "Phone Number", "phone"]},
    {"name": "address", "dir": READ, "required": False, "aliases": ["Address"]},
    {"name": "region", "dir": READ, "required": False, "aliases": ["Region", "City", "Town"]},
    {"name": "employees", "dir": READ, "required": False,
     "aliases": ["Employees", "employee_count", "Staff", "# Employees"]},
    {"name": "industry", "dir": READ, "required": False, "aliases": ["Industry", "Industries", "SIC"]},
    {"name": "trading_years", "dir": READ, "required": False,
     "aliases": ["Trading Years", "Years Trading", "lead_years"]},
    {"name": "campaign_tag", "dir": READ, "required": False, "aliases": ["campaign", "Campaign"]},
    {"name": "gateway_provider", "dir": READ, "required": False,
     "aliases": ["Email Security Gateway Provider", "Security Gateway Provider", "Security Gateway"]},

    {"name": "final_status", "dir": WRITE, "required": False, "aliases": ["Final Status"]},
    {"name": "email_source", "dir": WRITE, "required": False, "aliases": ["Email Source"]},
    {"name": "email_type", "dir": WRITE, "required": False, "aliases": ["Email Type"]},
    {"name": "verification_status", "dir": WRITE, "required": False, "aliases": ["Verification Status"]},
    {"name": "mv_date", "dir": WRITE, "required": False, "aliases": ["mv_date", "MV Date"]},
    {"name": "alternate_emails", "dir": WRITE, "required": False, "aliases": ["Alternate Emails"]},
    {"name": "campaign_type", "dir": WRITE, "required": False, "aliases": ["Campaign Type"]},
    {"name": "contact_2_email", "dir": WRITE, "required": False, "aliases": ["Contact 2 Email"]},
    {"name": "icebreaker", "dir": BOTH, "required": False,
     "aliases": ["Ice Breaker", "Icebreaker", "ice_breaker", "personalization"]},
]

BY_NAME = {f["name"]: f for f in FIELDS}
ALIASES = {f["name"]: tuple(f["aliases"]) for f in FIELDS}
REQUIRED = tuple(f["name"] for f in FIELDS if f["required"])
# fields worth warning about: without them a whole capability is silently dead
RECOMMENDED = ("website", "contact_name", "send_gate", "found_email")

# fields the engine can WRITE back to the sheet
WRITABLE = tuple(f["name"] for f in FIELDS if f["dir"] in (WRITE, BOTH))


def _norm(h) -> str:
    """Header comparison key: case, spaces and punctuation do not matter."""
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def suggest(headers) -> dict:
    """Auto-match every engine field against a sheet's real headers.
    First alias that exists wins, so the alias order is the preference order."""
    index = {}
    for h in headers:
        index.setdefault(_norm(h), str(h).strip())
    out = {}
    for f in FIELDS:
        for alias in f["aliases"]:
            hit = index.get(_norm(alias))
            if hit:
                out[f["name"]] = hit
                break
    return out


class FieldMap:
    """engine field -> sheet header. An empty map behaves exactly like V1."""

    def __init__(self, mapping: dict | None = None, *, name: str = ""):
        self.name = name
        self.mapping = {str(k).strip(): str(v).strip()
                        for k, v in (mapping or {}).items() if str(v or "").strip()}

    # ── reading ──────────────────────────────────────────────────

    def header(self, field: str) -> str:
        """The sheet header this field is mapped to, or '' when unmapped."""
        return self.mapping.get(field, "")

    def get(self, row: dict, field: str, default: str = "") -> str:
        """Read one engine field out of a raw sheet row.

        An explicit mapping is authoritative: if it is mapped and the cell is blank,
        the answer is blank. Only an UNMAPPED field falls back to the alias list."""
        h = self.mapping.get(field)
        if h:
            v = row.get(h)
            return str(v).strip() if v is not None and str(v).strip() else default
        for alias in ALIASES.get(field, ()):
            v = row.get(alias)
            if v is not None and str(v).strip():
                return str(v).strip()
        return default

    def resolve(self, row: dict, field_or_header: str, default: str = "") -> str:
        """Rules can name either an engine field ('employees') or a raw sheet header
        ('Trading Years'). Engine fields win; anything else is read straight off the row."""
        if field_or_header in BY_NAME:
            return self.get(row, field_or_header, default)
        v = row.get(field_or_header)
        return str(v).strip() if v is not None and str(v).strip() else default

    def has(self, field: str) -> bool:
        """True when the field is explicitly mapped (aliases do not count)."""
        return bool(self.mapping.get(field))

    # ── validation ───────────────────────────────────────────────

    def validate(self, headers) -> dict:
        """Check a map against the sheet's real headers BEFORE a run spends anything."""
        real = {_norm(h): str(h).strip() for h in headers}
        missing_required, missing_recommended, bad_targets, resolved = [], [], [], {}

        for f in FIELDS:
            name = f["name"]
            mapped = self.mapping.get(name)
            if mapped:
                if _norm(mapped) not in real:
                    # the silent-discard trap: a write here vanishes with no error
                    bad_targets.append({"field": name, "header": mapped})
                else:
                    resolved[name] = mapped
                continue
            for alias in f["aliases"]:                       # unmapped -> can an alias save it?
                if _norm(alias) in real:
                    resolved[name] = real[_norm(alias)]
                    break
            if name not in resolved:
                if f["required"]:
                    missing_required.append(name)
                elif name in RECOMMENDED:
                    missing_recommended.append(name)

        used = {_norm(v) for v in resolved.values()}
        unused = sorted(real[k] for k in real if k not in used)
        return {
            "ok": not missing_required and not bad_targets,
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
            "bad_targets": bad_targets,
            "resolved": resolved,
            "unused_headers": unused,
        }

    def completed(self, headers) -> "FieldMap":
        """A copy where every field that COULD be auto-matched is now written down.

        The auto-suggest-then-override pattern: run this once after reading the sheet
        header and the map becomes explicit, so `header()` is reliable and write-back
        never has to guess which column it meant."""
        merged = {**suggest(headers), **self.mapping}     # an explicit mapping always wins
        return FieldMap(merged, name=self.name)

    def to_dict(self) -> dict:
        return dict(self.mapping)


def load(path) -> FieldMap:
    """Read a field map from JSON: {"name": ..., "mapping": {engine_field: header}}."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return FieldMap({}, name="(none)")
    raw = json.loads(p.read_text(encoding="utf-8")) or {}
    return FieldMap(raw.get("mapping") or {}, name=raw.get("name") or p.stem)
