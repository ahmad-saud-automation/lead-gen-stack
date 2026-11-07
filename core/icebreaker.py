"""
icebreaker.py — a faithful port of V7's "Prepare OpenAI Prompt" builder.

The icebreaker is built DETERMINISTICALLY in code (V7 uses this text verbatim; its
OpenAI call only echoes it back). Three modes:
  * offer     (default, no audit data)  — O1a/O1b/O2a/O2b/O3, evenly rotated
  * delivered (has an SEO-audit finding) — D1/D2, jargon translated to plain English
  * clean     (site scored well)         — CLEAN

Every line of copy lives in DEFAULT_TEMPLATES and can be overridden at runtime
(the app's Icebreaker tab saves edits to config), so wording changes never need a
code edit. Placeholders: {company} · {plain} (the translated audit finding) ·
{score_clause} (the "it scores N out of 100" aside).

Pure + deterministic — no network.
"""
from __future__ import annotations

import re

# ── the editable copy ────────────────────────────────────────────────
DEFAULT_TEMPLATES = {
    "O1a": "know you guys are crushing it at {company}, so this is a bit out of the blue, but I'd happily run you a free audit of where you're losing local clients online.",
    "O1b": "know you guys are crushing it at {company}, figured I'd offer you a quick free check of how you show up on Google and ChatGPT.",
    "O2a": "are you the one who looks after new client enquiries at {company}? Love how clean and trustworthy the site feels, btw.",
    "O2b": "are you in charge of bringing in new clients at {company}? Love how established the firm comes across online, btw.",
    "O3": "I'll run a full SEO audit on your site and show you exactly which pages are losing you enquiries, completely free. Just reply and I'll have it in your inbox within 24 hours.",
    "D1": "love what you've built at {company}. Very no-BS, and I ended up doing a quick audit of your site. Noticed {plain}, which is probably sending a few local enquiries elsewhere.",
    "D2_speed": "you're losing a tremendous number of visitors in the first 60 seconds right now, not because your work is bad (it rocks), but because {plain}. Will you let me fix that?",
    "D2": "you're missing out on a tremendous number of enquiries right now, not because your firm isn't good (it rocks), but because {plain}. Will you let me fix that?",
    "CLEAN": "{company} has a genuinely quick, well-built site{score_clause}, which is rare for an accountancy firm. Happy to run you a free check on how you're showing up for local searches and on tools like ChatGPT.",
}
OFFER_STYLES = ["O1a", "O1b", "O2a", "O2b", "O3"]
PLACEHOLDERS = {"company", "plain", "score_clause"}

# audit-jargon -> plain English (the bool marks a speed/experience issue -> D2_speed)
_MAP = [
    (re.compile(r"noindex|blocked|stop search engines|not indexed", re.I), "your homepage is hidden from Google entirely", False),
    (re.compile(r"layout shift|\bcls\b|elements move|move as the page", re.I), "things jump around while your page loads", True),
    (re.compile(r"slow|load|loading|loads|speed|render-?blocking|takes ~|takes about|seconds on mobile", re.I), "your site takes too long to load on phones", True),
    (re.compile(r"not mobile-?friendly|viewport", re.I), "your site doesn't display properly on phones", True),
    (re.compile(r"\btitle\b", re.I), "Google isn't clear about what you do, so you're ranking lower", False),
    (re.compile(r"\bh1\b|h1 heading|no h1", re.I), "your homepage doesn't tell Google clearly what you do", False),
    (re.compile(r"meta description", re.I), "your Google listing has nothing to make people click it", False),
    (re.compile(r"sitemap", re.I), "some of your pages aren't getting picked up by Google", False),
    (re.compile(r"structured data|schema", re.I), "you're missing the extra info that makes your Google listing stand out", False),
    (re.compile(r"open graph|social preview", re.I), "your links look plain and bare when people share them", False),
    (re.compile(r"canonical", re.I), "Google may be seeing duplicate versions of your pages", False),
    (re.compile(r"alt text", re.I), "a few small gaps are weakening your search visibility", False),
    (re.compile(r"click here|vague link|link text", re.I), "Google is getting weak signals about what your pages cover", False),
]


def _translate(text: str):
    lines = [s.strip() for s in str(text).split("\n") if s.strip()] or [str(text)]
    for line in lines:
        for rx, plain, speed in _MAP:
            if rx.search(line):
                return plain, speed
    return "a few small things are limiting how well you show up on Google", False


def _hash(key: str) -> int:
    h = 0
    for ch in str(key):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def _render(template: str, **vals) -> str:
    """Fill placeholders without exploding on a stray brace in user-edited copy."""
    out = str(template or "")
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return re.sub(r"\s+", " ", out).strip()


def validate_templates(templates: dict) -> list[str]:
    """Problems to show the user before they save edited copy."""
    problems = []
    for key in DEFAULT_TEMPLATES:
        text = str((templates or {}).get(key, "")).strip()
        if not text:
            problems.append(f"{key}: empty")
            continue
        for ph in re.findall(r"\{(\w+)\}", text):
            if ph not in PLACEHOLDERS:
                problems.append(f"{key}: unknown placeholder {{{ph}}}")
        if key in ("D1", "D2", "D2_speed") and "{plain}" not in text:
            problems.append(f"{key}: should include {{plain}} (the audit finding)")
    return problems


def build(firm: dict, email: str = "", templates: dict | None = None) -> dict:
    t = {**DEFAULT_TEMPLATES, **(templates or {})}
    company = firm.get("lead_company") or firm.get("Company Name") or "your firm"
    email = email or firm.get("found_email") or firm.get("final_email") or ""
    audit_mode = str(firm.get("audit_mode", "offer")).lower().strip()
    audit_finding = firm.get("audit_opener_data") or firm.get("audit_opener") or ""
    audit_score = firm.get("audit_perf_score") or ""
    h = _hash(email or company or "")

    if audit_mode == "delivered" and audit_finding:
        plain, speed = _translate(audit_finding)
        style = "D1" if h % 2 == 0 else ("D2_speed" if speed else "D2")
        text = _render(t[style], company=company, plain=plain)
        style = "D1" if style == "D1" else "D2"
    elif audit_mode == "clean":
        style = "CLEAN"
        clause = f" (it scores {audit_score} out of 100 on Google's mobile test)" if audit_score else ""
        text = _render(t["CLEAN"], company=company, score_clause=clause)
    else:
        style = OFFER_STYLES[h % len(OFFER_STYLES)]
        text = _render(t[style], company=company)

    return {"text": text, "style": style}
