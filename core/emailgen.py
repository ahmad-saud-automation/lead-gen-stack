"""
emailgen.py — turn a director's name + company domain into RANKED candidate
emails to try, in the same order V7's "Prepare Email Candidate" node uses.

The pipeline generates candidates most-likely-first; the verify step (verify.py)
checks them in order and STOPS at the first one MillionVerifier accepts — so we
spend the fewest verifications.

Four modes (the first two a faithful copy of V7's PATTERN_LIBRARY):
  lean      → first · first.last · f.last        (fewest verifications, default)
  plus      → first · middle · first.last · f.last · firstlast · flast  (wider net)
  fullname  → first.last · firstlast · flast     (never a bare first@)
  firstfull → first · first.last · firstlast · flast   (MEASURED best value)

`fullname` is the set he asked for on the Northwind "Organized" tabs, on the reasoning that
`john@` on a 2-partner practice may be the other John. ⛔ **It was measured and it is a
bad trade.** 1,531 addresses that real firms already use, read out of his own sheet on
2026-10-13, break down as: `first@` **38.6%**, `first.last@` 10.9%, `flast@` 2.9%,
`firstlast@` 2.8%, `f.last@` 1.2%, and 40.7% in a shape no pattern can reach. So
`fullname` covers 16.7% of them and `firstfull` covers 55.3% — and because a run stops
at the first address that passes, leading with the 38.6% case makes `firstfull` slightly
CHEAPER per lead (~2.6 checks vs ~2.75) as well as 3.3x better. A live 25-row batch on
C1 Hiring with `fullname` spent 51 checks for 0 hits. `plus` reaches only 56.5%, for up
to 6 checks a contact, so it is the worst value of the four.

Deterministic and pure — no network.
"""
from __future__ import annotations

import re

PATTERN_LIBRARY = {
    "lean": ["first", "first.last", "f.last"],
    "plus": ["first", "middle", "first.last", "f.last", "firstlast", "flast"],
    "fullname": ["first.last", "firstlast", "flast"],
    "firstfull": ["first", "first.last", "firstlast", "flast"],
}

# title prefixes stripped from the front of a name before building patterns (v7)
_TITLE_PREFIXES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir"}
_SPECIAL_PREFIXES = {"md", "mst"}


def clean_name_part(v: str) -> str:
    return re.sub(r"[^a-z]", "", str(v or "").strip().lower())


def clean_local_part(v: str) -> str:
    """v7 cleanLocalPart: keep a-z0-9._-, collapse repeats, trim edges."""
    local = re.sub(r"[^a-z0-9._-]", "", str(v or "").strip().lower())
    local = re.sub(r"([._-])\1+", r"\1", local)     # collapse ".." / "--" etc.
    local = re.sub(r"^[._-]+|[._-]+$", "", local)   # trim leading/trailing . _ -
    return local


def _raw_words(full_name: str) -> list[str]:
    return [w for w in (clean_name_part(p) for p in re.sub(r"\s+", " ", str(full_name or "").strip()).split(" ")) if w]


def derive_name(full_name: str, fallback_first: str = "", fallback_last: str = "") -> dict:
    """v7 name extraction: strip title/special prefixes; first / middle / last."""
    words = _raw_words(full_name)
    while words and (words[0] in _TITLE_PREFIXES or words[0] in _SPECIAL_PREFIXES):
        words.pop(0)
    first = words[0] if words else clean_name_part(fallback_first)
    middle = words[1] if len(words) >= 3 else ""
    last = (words[-1] if len(words) > 1 else "") or clean_name_part(fallback_last)
    return {"first": first, "middle": middle, "last": last, "words": words}


def spoken_words(full_name: str) -> list[str]:
    """The name's words with any leading Mr / Mrs / Dr / MD stripped, SPELLING KEPT.

    `derive_name` lowercases and strips punctuation because it is building an address.
    A name written into the sheet, or greeted in an email, has to keep its capitals —
    the Organized tabs hold rows like "MR Sumit Agarwal", where the guessed address is
    right (sumit.agarwal@) but a naive first word gives "Hi MR,"."""
    words = [w for w in re.split(r"\s+", str(full_name or "").strip()) if w]
    while words and clean_name_part(words[0]) in (_TITLE_PREFIXES | _SPECIAL_PREFIXES):
        words.pop(0)
    return words


def _pattern_value(pattern: str, first: str, middle: str, last: str) -> str:
    fi, li = first[:1], last[:1]
    return {
        "first": first,
        "middle": middle,
        "first.last": f"{first}.{last}" if first and last else "",
        "f.last": f"{fi}.{last}" if fi and last else "",
        "firstlast": f"{first}{last}" if first and last else "",
        "flast": f"{fi}{last}" if fi and last else "",
        "firstl": f"{first}{li}" if first and li else "",
    }.get(pattern, "")


def generate(first: str, last: str, domain: str, *, mode: str = "lean", middle: str = "") -> list[dict]:
    """Ordered, de-duplicated candidate emails for one person on one domain."""
    first, last, middle = clean_name_part(first), clean_name_part(last), clean_name_part(middle)
    domain = str(domain or "").strip().lower()
    patterns = PATTERN_LIBRARY.get(mode, PATTERN_LIBRARY["lean"])
    out, seen = [], set()
    if not domain:
        return out
    for pat in patterns:
        local = clean_local_part(_pattern_value(pat, first, middle, last))
        if not local or len(local) < 2:          # v7 skips locals shorter than 2
            continue
        email = f"{local}@{domain}"
        if email in seen:
            continue
        seen.add(email)
        out.append({"email": email, "pattern": pat, "source": f"guess_{pat.replace('.', '_')}"})
    return out


def candidates_for_firm(firm: dict, mode: str = "lean") -> list[dict]:
    """Candidates for a firm row produced by organize.py (uses the primary/oldest director)."""
    name = derive_name(firm.get("lead_director") or firm.get("Oldest Director Name") or "",
                        fallback_first=firm.get("lead_firstname", ""),
                        fallback_last=firm.get("lead_lastname", ""))
    return generate(name["first"], name["last"], firm.get("lead_domain", ""),
                    mode=mode, middle=name["middle"])


def matches_generated_pattern(email: str, first: str, last: str, domain: str, *, mode: str = "plus") -> bool:
    """True if a supplied email exactly matches one of the generated person patterns
    on the same domain — v7's strict 'use the source email only if it looks like a
    real person address' rule."""
    e = str(email or "").strip().lower()
    if "@" not in e:
        return False
    return e in {c["email"] for c in generate(first, last, domain, mode=mode)}
