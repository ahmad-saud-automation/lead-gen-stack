"""
runner.py — turn "a campaign" into "the exact leads this run will work on".

This is the piece V1 had no room for. V1 read a whole tab, filtered on Status alone,
took the first `max_firms`, and pushed them all to one campaign id. A run here instead:

    read the tab (raw rows)
        -> complete + validate the field map against the sheet's REAL header
        -> keep the rows this campaign's rules want
        -> drop anything the ledger already handled
        -> sort best-first
        -> cap by per_run, and by what is left of per_day
        -> organize into firms, carrying the raw row for the label table

Everything up to `organize` is pure and free, which is what makes `plan()` possible:
the same code path, stopped one step early, spending nothing.
"""
from __future__ import annotations

from pathlib import Path

from . import campaigns as campaigns_mod
from . import fieldmap as fieldmap_mod
from . import organize as organize_mod
from . import rules as rules_mod


def headers_of(rows: list[dict]) -> list[str]:
    """The sheet's real header, taken from the rows themselves. Reads a few rows rather
    than only the first, because a CSV reader drops nothing but a sparse API read can."""
    seen: list[str] = []
    known: set[str] = set()
    for row in rows[:50]:
        for k in row:
            if k not in known:
                known.add(k)
                seen.append(k)
    return seen


def load_config_dir(config_dir) -> dict:
    """Read config/campaigns.json plus every field map it names."""
    d = Path(config_dir)
    camps, globals_cfg = campaigns_mod.load(d / "campaigns.json")
    maps: dict[str, fieldmap_mod.FieldMap] = {}
    for c in camps:
        fname = c.fieldmap or ""
        if fname and fname not in maps:
            maps[fname] = fieldmap_mod.load(d / fname)
    return {"campaigns": camps, "globals": globals_cfg, "fieldmaps": maps}


def fieldmap_for(campaign, maps: dict, headers=None) -> fieldmap_mod.FieldMap:
    """The campaign's map, completed against the sheet's real header so that every
    resolvable field is explicit and write-back never has to guess."""
    fm = maps.get(campaign.fieldmap or "") or fieldmap_mod.FieldMap({})
    return fm.completed(headers) if headers else fm


def check_fieldmap(fm, headers) -> dict:
    """Validate a map before a run spends anything. `blocking` is the reason to stop."""
    v = fm.validate(headers)
    blocking: list[str] = []
    for f in v["missing_required"]:
        blocking.append(f"required field '{f}' is not mapped and no matching column was found")
    for bad in v["bad_targets"]:
        blocking.append(f"'{bad['field']}' is mapped to '{bad['header']}', which is not a "
                        "column in this sheet - a write there is silently discarded")
    v["blocking"] = blocking
    v["ok"] = not blocking
    return v


def remaining_today(campaign, ledger) -> int:
    """How many more leads this campaign may take today. 0 per_day means no limit."""
    if not campaign.per_day or ledger is None:
        return campaign.per_day or 10 ** 9
    used = ledger.count_today("enrich", campaign=campaign.id)
    return max(0, campaign.per_day - used)


def prepare(campaign, raw_rows: list[dict], fm, *, ledger=None, cfg: dict | None = None,
            take: int | None = None) -> dict:
    """Everything this campaign would work on, and why the rest was left out."""
    cfg = cfg or {}
    matched = [r for r in raw_rows if rules_mod.match(r, campaign.rules, fm)[0]]

    fresh, blocked = matched, 0
    if ledger is not None:
        fresh, blocked = ledger.filter_pending(
            matched, fm, stage="enrich",
            retry_not_found=bool(cfg.get("retry_not_found", False)))

    ordered = rules_mod.sort_rows(fresh, campaign.order, fm)

    cap = campaign.per_run if take is None else take
    day_left = remaining_today(campaign, ledger)
    cap = min(cap or len(ordered), day_left) if day_left is not None else (cap or len(ordered))
    selected = ordered[:cap] if cap else []

    org = organize_mod.organize(
        selected, owned_companies=cfg.get("owned_companies"),
        owned_domains=cfg.get("owned_domains"),
        strict_status=bool(cfg.get("strict_status", True)),
        fm=fm, keep_raw=True)

    for firm in org["firms"]:
        firm["campaign"] = campaign.id
        firm["campaign_type"] = campaign.campaign_tag()
        firm["lead_id"] = firm.get("row_key") or firm.get("company_key") or ""

    return {
        "campaign": campaign.id,
        "rows_in_tab": len(raw_rows),
        "matched": len(matched),
        "blocked_by_ledger": blocked,
        "available": len(fresh),
        "day_remaining": day_left,
        "selected": len(selected),
        "firms": org["firms"],
        "skipped": org["skipped"],
    }


def label_source_row(firm: dict) -> dict:
    """The row the label table reads from: the raw sheet row underneath the firm, with
    the engine's own result fields layered on top. Without the raw row a campaign could
    only send labels the engine happens to have a name for."""
    raw = firm.get("_raw") or {}
    merged = dict(raw)
    for k, v in firm.items():
        if k != "_raw" and v not in (None, ""):
            merged[k] = v
    return merged


# ───────────────────── ice breakers: Icebreaker Studio's line only ─────────────────────
#
# Decided 2026-09-29: a campaign lane never writes an ice breaker. Icebreaker Studio writes
# one into the sheet's Ice Breaker column, and the lane sends exactly that. Before this the
# engine built its own template line, sent it instead, and write-back then overwrote
# Studio's line in the sheet. The V1 single-campaign flow (/legacy) is unchanged: its CSV
# uploads have no Studio column.

def sheet_icebreaker(row: dict, fm) -> str:
    """Icebreaker Studio's line for this lead, from the sheet row underneath it."""
    raw = row.get("_raw") or row
    col = (fm.header("icebreaker") if fm else "") or "Ice Breaker"
    return str(raw.get(col) or "").strip()


def refresh_icebreakers(rows: list[dict], sheet_rows: list[dict], fm) -> list[dict]:
    """Each result with the line the sheet holds NOW, matched on the row key.

    Studio may write a line after the enrichment run, so a push re-reads the sheet rather
    than trusting what the run saw. A lead the sheet no longer has keeps the run's line."""
    key_col = (fm.header("row_key") if fm else "") or "lead_id"
    now = {str(r.get(key_col) or "").strip(): r for r in sheet_rows if str(r.get(key_col) or "").strip()}
    out = []
    for r in rows:
        live = now.get(str(r.get("row_key") or r.get("lead_id") or "").strip())
        line = sheet_icebreaker(live, fm) if live is not None else str(r.get("icebreaker") or "").strip()
        out.append({**r, "icebreaker": line, "ice_style": "studio" if line else ""})
    return out


def split_by_icebreaker(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(has a Studio line, waiting for one)."""
    ready = [r for r in rows if str(r.get("icebreaker") or "").strip()]
    return ready, [r for r in rows if not str(r.get("icebreaker") or "").strip()]


def push_options(campaign) -> dict:
    """The Instantly API options this campaign wants — blocklist_id and the skip flags
    included, which V1 never sent."""
    inst = dict(campaign.instantly or {})
    inst.pop("campaign_id", None)
    return inst
