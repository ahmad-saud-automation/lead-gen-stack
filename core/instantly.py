"""
instantly.py — a faithful port of V7's "Prepare Instantly Data" + "Add lead to campaign".

Two halves, both testable offline:
  * build_payload(row, campaign_id)  — pure. Cleans the icebreaker exactly as V7 does
    (strip wrapping quotes, drop quote chars, newlines -> spaces, collapse spaces, NO
    sentence truncation) and derives Title-Cased first/last from "Selected Director"
    for Instantly's {{firstName}} greeting.
  * push_lead(...)                   — POST /api/v2/leads. test_mode uses a no-spend
    stub so the whole flow runs without touching the real campaign.

Also `pushed_status(source)` -> the exact V7 sheet status: pushed_to_instantly_<source>.

Nothing here sends anything unless test_mode is False AND a key + campaign id are set.
"""
from __future__ import annotations

import json
import re
import urllib.request

from . import emailgen
from . import net
from . import retry as retry_mod

INSTANTLY_URL = "https://api.instantly.ai/api/v2/leads"


def clean_icebreaker(text: str) -> str:
    """V7's cleaner: unwrap quotes, remove quote chars, flatten newlines, collapse spaces."""
    s = str(text or "").strip()
    s = re.sub(r'^["\'“”]+|["\'“”]+$', "", s)
    s = re.sub(r'["“”]', "", s)
    s = re.sub(r"[\r\n]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_case_name(name: str) -> str:
    s = re.sub(r"\s+", " ", str(name or "").strip()).lower()
    return re.sub(r"\b[a-z]", lambda m: m.group(0).upper(), s)


def split_display_name(director: str) -> dict:
    parts = [p for p in str(director or "").strip().split(" ") if p]
    first = title_case_name(parts[0]) if parts else ""
    last = title_case_name(parts[-1]) if len(parts) > 1 else ""
    return {"first": first, "last": last, "full": " ".join(x for x in (first, last) if x)}


def pushed_status(source: str) -> str:
    """V7 writes pushed_to_instantly_<email_source> to both Status and Final Status."""
    return f"pushed_to_instantly_{str(source or 'selected').strip() or 'selected'}"


# Fields POST /api/v2/leads accepts beyond the core ones. V1 sent none of these, which
# is why job_title never reached Instantly even though the sheet has the column, and why
# blocklist_id — the API-level suppression gate — was never used.
OPTIONAL_ID_FIELDS = ("list_id", "blocklist_id", "assigned_to")
OPTIONAL_FLAG_FIELDS = ("verify_leads_on_import", "verify_leads_for_lead_finder")


def build_payload(row: dict, campaign_id: str, *, labels=None, fm=None,
                  options: dict | None = None) -> dict:
    """The body sent to Instantly for one verified lead.

    With no `labels`, `fm` or `options` this is byte-for-byte what V7 sent. Pass a
    campaign's label table to send your own variables, and `options` to use the API
    fields V1 ignored (blocklist_id, list_id, the skip flags)."""
    opts = dict(options or {})
    name_raw = ""
    if fm is not None:
        name_raw = fm.get(row, "contact_name")
    name_raw = (name_raw or row.get("contact_name") or row.get("Contact Name")
                or row.get("selected_director") or row.get("Selected Director") or "")
    # A recipe row (only those carry `found_for`) holds the WINNER in contact_name. The
    # field map's contact_name is the sheet's contact 1, so a lead found for contact 2-5
    # went out under contact 1's first name (found on C1, 2026-10-13). Same words the
    # sheet's final_first_name gets, so Instantly and the sheet agree.
    if "found_for" in row and str(row.get("contact_name") or "").strip():
        name_raw = " ".join(emailgen.spoken_words(row["contact_name"]))
    name = split_display_name(name_raw)

    job_title = ""
    if fm is not None:
        job_title = fm.get(row, "job_title")
    job_title = job_title or row.get("job_title") or row.get("Job Title") or row.get("primary_title") or ""

    payload = {
        "campaign": campaign_id,
        "email": row.get("found_email") or row.get("final_email") or "",
        "first_name": name["first"],
        "last_name": name["last"],
        "company_name": row.get("company") or row.get("Company Name") or "",
        "job_title": str(job_title or "").strip(),
        "website": row.get("lead_website") or row.get("domain") or "",
        "phone": row.get("phone") or "",
        "personalization": clean_icebreaker(row.get("icebreaker") or row.get("ice_breaker") or ""),
        "skip_if_in_workspace": bool(opts.get("skip_if_in_workspace", False)),
        "skip_if_in_campaign": bool(opts.get("skip_if_in_campaign", False)),
        "skip_if_in_list": bool(opts.get("skip_if_in_list", True)),
        "custom_variables": build_custom_variables(row, labels, fm),
    }
    for f in OPTIONAL_ID_FIELDS:                 # only sent when actually configured
        v = str(opts.get(f) or "").strip()
        if v:
            payload[f] = v
    for f in OPTIONAL_FLAG_FIELDS:
        if f in opts:
            payload[f] = bool(opts[f])
    return payload


# The five lead labels from campaign-decision-agent/ARCHITECTURE §5.1. They ride to
# Instantly inside custom_variables, land in the lead's `payload`, and come back out
# through GET /api/v2/leads/list. Without them the decision agent has nothing to group
# by and cannot tell a working trigger from a working list.
LABEL_COLUMNS = ("trigger_family", "evidence_source", "evidence_strength",
                 "contact_source", "verify_status")

# ── dynamic labels ───────────────────────────────────────────────────
#
# V1 hard-coded the list above as a Python tuple, so adding a label meant editing code.
# Instantly does not require that: per the API docs `custom_variables` accepts ANY key,
# as long as the value is a string, number, boolean or null — no nested objects, no
# arrays. Adding a variable to one lead updates the campaign schema for the rest.
#
# A label spec is:
#   {"send_as": "trigger_family",       the variable name Instantly receives
#    "type": "column" | "fixed" | "derived",
#    "source": "trigger_family",        a column/engine field, or a list of candidates
#    "value": ...,                      for type "fixed"
#    "fallback": "V0_volume",           used when the source is empty
#    "omit_if_blank": false}            drop the key entirely instead of sending a blank
#
# ⚠️ Never send a blank label. The decision agent counts 'unlabelled' as a real group,
# but a blank disappears out of every GROUP BY without anyone noticing.

LABEL_TYPES = ("column", "fixed", "derived")
ALLOWED_LABEL_VALUES = (str, int, float, bool, type(None))

DEFAULT_LABELS: list[dict] = [
    {"send_as": "Address", "type": "column", "source": ["city", "City"], "fallback": ""},
    {"send_as": "trigger_family", "type": "column", "source": "trigger_family",
     "fallback": "V0_volume"},
    {"send_as": "evidence_source", "type": "column", "source": "evidence_source",
     "fallback": "unlabelled"},
    {"send_as": "evidence_strength", "type": "column", "source": "evidence_strength",
     "fallback": "unlabelled"},
    {"send_as": "contact_source", "type": "column", "source": "contact_source",
     "fallback": "unlabelled"},
    {"send_as": "verify_status", "type": "column", "source": "verify_status",
     "fallback": "unlabelled"},
    {"send_as": "seniority_tier", "type": "derived", "source": "seniority_tier",
     "fallback": "unknown"},
    {"send_as": "size_band", "type": "derived", "source": "size_band", "fallback": "unknown"},
    {"send_as": "lead_id", "type": "column", "source": ["lead_id", "row_key"],
     "omit_if_blank": True},
    {"send_as": "campaign", "type": "column", "source": "campaign", "omit_if_blank": True},
]


def _derive_seniority(row: dict, fm=None) -> str:
    raw = ""
    if fm is not None:
        raw = fm.get(row, "seniority_rank")
    raw = raw or row.get("seniority_label") or row.get("seniority_tier") or ""
    return seniority_tier(raw)


def _derive_size_band(row: dict, fm=None) -> str:
    raw = ""
    if fm is not None:
        raw = fm.get(row, "employees")
    raw = raw or row.get("Employees") or row.get("employees") or ""
    return size_band(raw)


DERIVED = {"seniority_tier": _derive_seniority, "size_band": _derive_size_band}


def _read_source(row: dict, source, fm=None) -> str:
    """A source may be one name or a list of candidates — first non-blank wins."""
    names = source if isinstance(source, (list, tuple)) else [source]
    for n in names:
        n = str(n or "").strip()
        if not n:
            continue
        if fm is not None:
            v = fm.resolve(row, n)
            if v:
                return v
        v = row.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


OMIT = object()      # "drop this key entirely", which is not the same as sending null


def resolve_label(row: dict, spec: dict, fm=None):
    """One label spec -> the value Instantly receives, or OMIT to drop the key."""
    kind = str(spec.get("type") or "column").strip().lower()
    if kind == "fixed":
        val = spec.get("value")
    elif kind == "derived":
        fn = DERIVED.get(str(spec.get("source") or "").strip())
        val = fn(row, fm) if fn else ""
    else:
        val = _read_source(row, spec.get("source") or spec.get("send_as"), fm)
    if isinstance(val, str):
        val = val.strip()
    if kind != "fixed" and (val is None or val == ""):
        if spec.get("omit_if_blank"):
            return OMIT
        val = spec.get("fallback", "")
    if not isinstance(val, ALLOWED_LABEL_VALUES):
        val = str(val)                     # a dict/list would be rejected by the API
    return val


def validate_label_specs(specs) -> list[str]:
    """Catch a bad label table at save time, not at push time."""
    issues: list[str] = []
    if specs is None:
        return issues
    if not isinstance(specs, list):
        return ["labels must be a list of label specs"]
    seen: set[str] = set()
    for i, spec in enumerate(specs):
        if not isinstance(spec, dict):
            issues.append(f"labels[{i}] must be an object")
            continue
        send_as = str(spec.get("send_as") or "").strip()
        kind = str(spec.get("type") or "column").strip().lower()
        if not send_as:
            issues.append(f"labels[{i}] needs 'send_as' — the variable name Instantly receives")
        elif send_as in seen:
            issues.append(f"labels[{i}] duplicate variable name '{send_as}'")
        else:
            seen.add(send_as)
        if kind not in LABEL_TYPES:
            issues.append(f"labels[{i}] unknown type '{kind}' (use {', '.join(LABEL_TYPES)})")
        if kind == "fixed":
            if not isinstance(spec.get("value"), ALLOWED_LABEL_VALUES):
                issues.append(f"labels[{i}] 'value' must be text, a number, true/false or null "
                              "— Instantly rejects objects and lists")
        elif kind == "derived":
            if str(spec.get("source") or "") not in DERIVED:
                issues.append(f"labels[{i}] unknown derived source "
                              f"'{spec.get('source')}' (available: {', '.join(sorted(DERIVED))})")
        elif not (spec.get("source") or send_as):
            issues.append(f"labels[{i}] needs a 'source' column")
        if not isinstance(spec.get("fallback", ""), ALLOWED_LABEL_VALUES):
            issues.append(f"labels[{i}] 'fallback' must be text, a number, true/false or null")
    return issues


def seniority_tier(label: str) -> str:
    """Coarse tier for the decision agent. Derived here, never stored as a sheet column,
    so the fact lives in exactly one place (`seniority_label`)."""
    l = str(label or "").strip().lower()
    if l in ("owner", "leadership"):
        return "owner"
    if l in ("partner", "specialist_partner", "statutory_director", "accountant_principal"):
        return "partner_director"
    if not l:
        return "unknown"
    return "other"


def size_band(employees) -> str:
    """Coarse firm-size band for the decision agent, derived from Employees.
    Bands are merged so every value clears the agent's 300-lead minimum."""
    nums = re.findall(r"\d+", str(employees or "").replace(",", ""))
    if not nums:
        return "unknown"
    n = max(int(x) for x in nums)
    return "micro_1_10" if n <= 10 else "small_11_plus"


def build_custom_variables(row: dict, specs=None, fm=None) -> dict:
    """The label table -> Instantly's `custom_variables`.

    `specs=None` uses DEFAULT_LABELS, which reproduces V7's payload exactly: Address,
    the five decision-agent labels, the two derived ones, and lead_id / campaign only
    when they are actually present."""
    out: dict = {}
    for spec in (DEFAULT_LABELS if specs is None else specs):
        if not isinstance(spec, dict):
            continue
        send_as = str(spec.get("send_as") or "").strip()
        if not send_as:
            continue
        val = resolve_label(row, spec, fm)
        if val is OMIT:
            continue
        out[send_as] = val
    return out


def _http_push(payload: dict, api_key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        INSTANTLY_URL, data=json.dumps(payload).encode(), method="POST",
        headers=net.headers({"Content-Type": "application/json",
                             "Authorization": "Bearer " + api_key}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body}
        return {"ok": 200 <= r.status < 300, "status_code": r.status, "response": data}


def _test_push(payload: dict, api_key: str, timeout: int = 30) -> dict:
    """No-spend stub: validates the payload shape without contacting Instantly."""
    if not payload.get("email"):
        return {"ok": False, "status_code": 0, "response": {"error": "no email"}}
    if not payload.get("campaign"):
        return {"ok": False, "status_code": 0, "response": {"error": "no campaign id"}}
    return {"ok": True, "status_code": 200,
            "response": {"id": "test-" + str(abs(hash(payload["email"])) % 10**8), "simulated": True}}


def push_lead(row: dict, campaign_id: str, api_key: str = "", *, test_mode: bool = False,
              transport=None, timeout: int = 30, tries: int = 3, retry_wait: float = 5.0,
              on_retry=None, labels=None, fm=None, options: dict | None = None) -> dict:
    """Add one verified lead to the Instantly campaign. Returns the outcome + the
    sheet status to write back on success."""
    payload = build_payload(row, campaign_id, labels=labels, fm=fm, options=options)
    if not payload["email"]:
        return {"ok": False, "skipped": True, "reason": "no verified email", "payload": payload}
    tr = transport or (_test_push if test_mode else _http_push)
    attempts = 1 if test_mode else max(1, int(tries or 1))
    try:
        res = retry_mod.call(tr, payload, api_key, timeout,
                             tries=attempts, wait=retry_wait, on_retry=on_retry)
    except Exception as e:  # noqa: BLE001 — a failed push must not kill the run
        return {"ok": False, "error": str(e), "payload": payload}
    out = {"ok": bool(res.get("ok")), "status_code": res.get("status_code"),
           "response": res.get("response"), "payload": payload}
    if out["ok"]:
        out["status"] = pushed_status(row.get("email_source") or row.get("Email Source") or "selected")
    return out
