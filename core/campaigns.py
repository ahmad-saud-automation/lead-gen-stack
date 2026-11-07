"""
campaigns.py — many campaigns off one sheet.

V1 had exactly one campaign: `instantly_campaign_id` in config.json. Running a second
list meant editing settings and re-running by hand. A Campaign record makes each lane a
row of configuration instead:

    which rows (rules) · what order (order) · how many (limits)
    · where they go (instantly) · what rides along (labels) · when (schedule)

THE ONE-FIRM-ONE-CAMPAIGN RULE is enforced here, not by hoping the rules do not overlap:
campaigns are evaluated in priority order and the FIRST one whose rules match claims the
row. A row can never be sent by two campaigns.

`plan()` is the safety feature. It answers "how many rows would each campaign take?"
by reading the sheet and applying the rules — no finder, no verifier, no push, no spend.
Run it before every real run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import rules as rules_mod

# a lane that has not been told otherwise
DEFAULTS = {
    "enabled": False,          # nothing runs until it is switched on deliberately
    "priority": 100,
    "auto_push": False,        # a push always needs a human until this is flipped
    "limits": {"per_run": 50, "per_day": 100, "max_spend_usd": 2.0},
}

# global ceilings, applied across every campaign in one day
GLOBAL_DEFAULTS = {"daily_push_cap": 300, "daily_spend_cap_usd": 5.0}


class Campaign:
    """One lane. Dict in, attributes out, no surprises."""

    def __init__(self, raw: dict):
        self.raw = dict(raw or {})
        self.id = str(self.raw.get("id") or "").strip()
        self.name = str(self.raw.get("name") or self.id).strip()
        self.enabled = bool(self.raw.get("enabled", DEFAULTS["enabled"]))
        self.priority = int(self.raw.get("priority", DEFAULTS["priority"]) or 0)
        # NOT stripped: a real tab can end in a space ("Construction " in the Northwind sheet), and
        # the trimmed name does not exist in the sheet
        self.tab = str(self.raw.get("tab") or "")
        # Which Google Sheet this lane's tab lives in. Blank = the one in Settings, which
        # is what every campaign built before 2026-10-13 uses and keeps using. Set it and
        # this lane reads and writes its OWN document instead: the Northwind "Organized" sheet
        # is a different file from the Practices sheet the other nine lanes read, and the
        # engine held exactly one sheet URL for all of them until now.
        self.sheet_url = str(self.raw.get("sheet_url") or "").strip()
        self.fieldmap = str(self.raw.get("fieldmap") or "").strip()
        self.rules = self.raw.get("rules") or {}
        self.order = self.raw.get("order") or []
        # which Finding Recipe finds the emails. Blank = the engine's own fixed order,
        # which is what every campaign built before recipes existed keeps doing.
        self.recipe = str(self.raw.get("recipe") or "").strip()
        self.limits = {**DEFAULTS["limits"], **(self.raw.get("limits") or {})}
        self.instantly = self.raw.get("instantly") or {}
        self.labels = self.raw.get("labels") or []
        self.writeback = self.raw.get("writeback") or {}
        self.schedule = self.raw.get("schedule") or {}
        self.auto_push = bool(self.raw.get("auto_push", DEFAULTS["auto_push"]))

    # ── the three numbers a run needs ────────────────────────────

    @property
    def per_run(self) -> int:
        return max(0, int(self.limits.get("per_run") or 0))

    @property
    def per_day(self) -> int:
        return max(0, int(self.limits.get("per_day") or 0))

    @property
    def max_spend_usd(self) -> float:
        return max(0.0, float(self.limits.get("max_spend_usd") or 0))

    @property
    def instantly_campaign_id(self) -> str:
        return str(self.instantly.get("campaign_id") or "").strip()

    def campaign_tag(self) -> str:
        """What gets written into the sheet's Campaign Type column, and stamped on labels."""
        return str(self.writeback.get("campaign_type") or self.id or "").strip()

    def to_dict(self) -> dict:
        return dict(self.raw)

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Campaign {self.id} enabled={self.enabled} priority={self.priority}>"


# ───────────────────────── loading + validation ─────────────────────────

def load(path) -> tuple[list[Campaign], dict]:
    """Read campaigns.json -> (campaigns, globals). Missing file = no campaigns."""
    p = Path(path)
    if not p.exists():
        return [], dict(GLOBAL_DEFAULTS)
    raw = json.loads(p.read_text(encoding="utf-8")) or {}
    camps = [Campaign(c) for c in (raw.get("campaigns") or [])]
    g = {**GLOBAL_DEFAULTS, **(raw.get("globals") or {})}
    return camps, g


def validate(campaigns: list[Campaign], *, require_push_target: bool = False,
             recipes: dict | None = None) -> list[dict]:
    """Every problem across every campaign, so they are all fixable in one pass.

    `require_push_target` is only true when checking a LIVE push: a campaign is allowed
    to exist without an Instantly id while it is still being planned.

    `recipes` is every saved recipe, keyed by id. Pass it and a campaign pointing at a
    recipe that is gone, or at one with a problem, is reported here rather than quietly
    falling back to the fixed order mid-run."""
    issues: list[dict] = []
    seen_ids: set[str] = set()
    seen_targets: dict[str, list[Campaign]] = {}

    for c in campaigns:
        def bad(msg):
            issues.append({"campaign": c.id or "(no id)", "issue": msg})

        if not c.id:
            bad("every campaign needs an 'id'")
        elif c.id in seen_ids:
            bad(f"duplicate campaign id '{c.id}'")
        else:
            seen_ids.add(c.id)

        if not c.tab.strip():
            bad("no 'tab' set — which sheet tab does this campaign read?")

        for why in rules_mod.validate_rules(c.rules):
            bad(f"rules: {why}")

        for i, spec in enumerate(c.order or []):
            if not isinstance(spec, dict) or not str(spec.get("field") or "").strip():
                bad(f"order[{i}] needs a 'field'")
            elif spec.get("order") is not None and not isinstance(spec.get("order"), list):
                bad(f"order[{i}] 'order' must be a list of values, best first")

        if c.recipe and recipes is not None:
            rec = recipes.get(c.recipe)
            if rec is None:
                bad(f"it uses the finding recipe '{c.recipe}', which no longer exists — "
                    "pick another one, or clear it to use the app's own order")
            else:
                from . import recipe as recipe_mod
                for why in recipe_mod.validate(rec):
                    bad(f"finding recipe '{c.recipe}': {why}")

        if c.per_run <= 0:
            bad("limits.per_run is 0 — this campaign can never take a row")
        if c.per_day and c.per_run > c.per_day:
            bad(f"limits.per_run ({c.per_run}) is larger than limits.per_day ({c.per_day})")

        target = c.instantly_campaign_id
        if target:
            seen_targets.setdefault(target, []).append(c)
        elif require_push_target and c.enabled:
            bad("no instantly.campaign_id — a live push needs one")

    # Several lanes may feed one Instantly campaign. They stay apart in the results only
    # because every lead carries its lane id in the `campaign` variable — the default label
    # table sends it, so only a hand-written table that leaves it out is a problem.
    for target, lanes in seen_targets.items():
        if len({c.id for c in lanes}) < 2:
            continue
        for c in lanes:
            if c.labels and not any(isinstance(s, dict) and str(s.get("send_as") or "").strip()
                                    == "campaign" for s in c.labels):
                others = ", ".join(sorted({o.id for o in lanes if o.id != c.id}))
                issues.append({"campaign": c.id or "(no id)", "issue":
                    f"Instantly campaign '{target}' is shared with {others}, but this lane's "
                    "labels do not send 'campaign' — add it, or its leads cannot be told "
                    "apart from the other lanes' in the results"})

    return issues


# ───────────────────────── adding + removing lanes ─────────────────────────

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def slug(text: str) -> str:
    """'Owners — London 2' -> 'owners-london-2'. The id is what the ledger, the runs and the
    sheet's Campaign Type column record, so it is plain and stable."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:63]


def new_campaign(existing: list[dict], *, name: str, tab: str = "", fieldmap: str = "",
                 cid: str = "", copy_from: dict | None = None) -> tuple[dict | None, list[str]]:
    """A new lane for campaigns.json -> (row, problems). Pure: the caller writes it.

    A new lane is ALWAYS created switched off and checked LAST (highest priority number), so
    adding one can never quietly take rows from a lane that is already running.

    `copy_from` duplicates a lane's rules, order, labels, limits, write-back and finding
    recipe (recipes are shared on purpose — one serves many lanes), but never:
      · its Instantly campaign — lanes may share one, but that is a choice to type in,
        never something a copy does by accident;
      · its enabled state or auto_push — a copy is a draft until someone turns it on.
    """
    name = str(name or "").strip()
    cid = str(cid or "").strip().lower() or slug(name)
    taken = {str(c.get("id") or "") for c in existing}
    problems = []
    if not name:
        problems.append("give the campaign a name")
    if not cid or not ID_RE.match(cid):
        problems.append("the id must be lower-case letters, numbers, '-' or '_' (e.g. owners-london)")
    elif cid in taken:
        problems.append(f"there is already a campaign with the id '{cid}'")
    if problems:
        return None, problems

    last = max((int(c.get("priority", DEFAULTS["priority"]) or 0) for c in existing), default=0)
    if copy_from:
        row = json.loads(json.dumps(copy_from))           # deep copy, JSON-shaped
        if isinstance(row.get("instantly"), dict):
            row["instantly"] = {k: v for k, v in row["instantly"].items() if k != "campaign_id"}
        row.pop("note", None)
    else:
        row = {"limits": dict(DEFAULTS["limits"]), "rules": {}, "order": [], "labels": []}

    row.update({"id": cid, "name": name, "enabled": False, "auto_push": False,
                "priority": last + 10})
    row["tab"] = str(tab or row.get("tab") or "")          # kept exact, see Campaign.tab
    row["fieldmap"] = str(fieldmap or row.get("fieldmap") or "").strip()
    # the sheet's Campaign Type column says which lane sent a row, so a copy gets its own
    row["writeback"] = {**(row.get("writeback") or {}), "campaign_type": cid}
    if not row["tab"].strip():
        return None, ["choose which sheet tab the campaign reads"]
    return row, []


def remove_campaign(existing: list[dict], cid: str) -> tuple[list[dict], str]:
    """campaigns.json's list without `cid` -> (rows, problem). The ledger and past runs keep
    the id they recorded; only the lane's configuration goes."""
    kept = [c for c in existing if str(c.get("id") or "") != cid]
    if len(kept) == len(existing):
        return existing, f"there is no campaign '{cid}'"
    return kept, ""


# ───────────────────────── selection ─────────────────────────

def _ordered(campaigns: list[Campaign]) -> list[Campaign]:
    """Priority first (low number = looked at first), then file order. Stable."""
    return [c for _i, c in sorted(enumerate(campaigns), key=lambda p: (p[1].priority, p[0]))]


def assign(rows: list[dict], campaigns: list[Campaign], fm,
           *, enabled_only: bool = True) -> dict:
    """Give every row to at most ONE campaign — the first, by priority, whose rules match.

    Returns {campaign_id: [rows]} plus the rows nobody wanted and why."""
    lanes = [c for c in _ordered(campaigns) if c.enabled or not enabled_only]
    claimed: dict[str, list[dict]] = {c.id: [] for c in lanes}
    unclaimed: list[dict] = []
    reasons: dict[str, int] = {}

    for row in rows:
        for c in lanes:
            ok, _why = rules_mod.match(row, c.rules, fm)
            if ok:
                claimed[c.id].append(row)
                break
        else:
            unclaimed.append(row)
            if lanes:
                _ok, why = rules_mod.match(row, lanes[0].rules, fm)
                key = why or "no campaign matched"
                reasons[key] = reasons.get(key, 0) + 1

    return {"claimed": claimed, "unclaimed": unclaimed, "reasons": reasons,
            "lanes": [c.id for c in lanes]}


def select(rows: list[dict], campaign: Campaign, fm, *, take: int | None = None) -> list[dict]:
    """Rows this campaign wants, best first, capped. Pure — spends nothing."""
    kept = [r for r in rows if rules_mod.match(r, campaign.rules, fm)[0]]
    kept = rules_mod.sort_rows(kept, campaign.order, fm)
    cap = campaign.per_run if take is None else take
    return kept[:cap] if cap else kept


# ───────────────────────── the free plan preview ─────────────────────────

def plan(rows_by_tab: dict, campaigns: list[Campaign], fieldmaps: dict,
         *, ledger=None, globals_cfg: dict | None = None,
         mv_rate_usd: float = 0.0) -> dict:
    """What WOULD each campaign do, without spending anything.

    rows_by_tab : {"Practices": [raw rows], ...}
    fieldmaps   : {"Practices": FieldMap, ...} — falls back to a blank map (alias mode)

    The estimate assumes ~2 verifications per lead, which is what a lean pattern cascade
    costs when the first guess misses. It is a ceiling for budgeting, not a promise.
    """
    g = {**GLOBAL_DEFAULTS, **(globals_cfg or {})}
    blank = None
    out: list[dict] = []
    total_take = 0

    for tab, tab_rows in rows_by_tab.items():
        fm = fieldmaps.get(tab)
        if fm is None:
            from . import fieldmap as fieldmap_mod
            blank = blank or fieldmap_mod.FieldMap({})
            fm = blank
        # the CALLER decides which campaigns to include (enabled only, or all) — this
        # must not filter again or `--all` silently previews nothing
        lanes = [c for c in _ordered(campaigns) if c.tab == tab]
        if not lanes:
            continue
        # `lanes` is already the caller's chosen set — assign must not filter it again
        a = assign(tab_rows, lanes, fm, enabled_only=False)
        for c in lanes:
            matched = a["claimed"].get(c.id, [])
            fresh, blocked = matched, 0
            if ledger is not None:
                fresh, blocked = ledger.filter_pending(matched, fm, stage="enrich")
            ordered = rules_mod.sort_rows(fresh, c.order, fm)
            take = ordered[: c.per_run] if c.per_run else ordered
            est = round(len(take) * 2 * float(mv_rate_usd or 0), 4)
            total_take += len(take)
            out.append({
                "campaign": c.id, "name": c.name, "tab": tab,
                "rows_in_tab": len(tab_rows),
                "matched": len(matched),
                "blocked_by_ledger": blocked,
                "available": len(fresh),
                "take_this_run": len(take),
                "per_run": c.per_run, "per_day": c.per_day,
                "instantly_campaign_id": c.instantly_campaign_id,
                "estimated_spend_usd": est,
                "warnings": _warn(c, len(fresh), len(take), est),
            })

    warnings = []
    if total_take > int(g.get("daily_push_cap") or 0) > 0:
        warnings.append(f"this plan takes {total_take} leads but the global daily cap is "
                        f"{g['daily_push_cap']} — later campaigns will be cut short")
    return {"campaigns": out, "total_take": total_take, "globals": g, "warnings": warnings}


def _warn(c: Campaign, available: int, take: int, est_usd: float) -> list[str]:
    w = []
    if available == 0:
        w.append("no rows match - check the rules and the field map before running")
    if not c.instantly_campaign_id:
        w.append("no Instantly campaign id - a live push will be refused")
    if c.max_spend_usd and est_usd > c.max_spend_usd:
        w.append(f"estimated ${est_usd:.2f} is over this campaign's ${c.max_spend_usd:.2f} cap")
    # the decision agent refuses to call a result on a group under 300 leads
    if 0 < available < 300:
        w.append(f"only {available} leads - under the 300 the decision agent needs to read a result")
    if take and take < c.per_run:
        w.append(f"only {take} available, below per_run {c.per_run}")
    return w
