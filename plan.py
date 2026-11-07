"""
plan.py — "what would each campaign do?", for free.

Reads your sheet, applies each campaign's rules, and prints how many rows every lane
would take. It makes NO finder call, NO verification and NO push, so it costs nothing
and can be run as often as you like. Run it before every real run.

    python plan.py                            the configured Google Sheet
    python plan.py --csv leads.csv            a local CSV, as the first campaign's tab
    python plan.py --csv leads.csv --tab Practices
    python plan.py --all                      include disabled campaigns too
    python plan.py --json                     machine-readable output

Exit code is 1 when something would stop a real run (a broken field map, a campaign with
no Instantly id), so a scheduled task can refuse to run on a bad config.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import campaigns as campaigns_mod       # noqa: E402
from core import ledger as ledger_mod             # noqa: E402
from core import runner as runner_mod             # noqa: E402
from core import sheets as sheets_mod             # noqa: E402

CONFIG_DIR = ROOT / "config"
DATA = ROOT / "data"


def load_engine_config() -> dict:
    """Same merge order the app uses: shipped defaults, then your saved settings."""
    cfg: dict = {}
    for p in (ROOT / "config.json", DATA / "config.json"):
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")) or {})
        except (OSError, ValueError):
            pass
    return cfg


def read_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [{(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))]


def read_tab(cfg: dict, tab: str) -> list[dict]:
    """One tab out of the configured sheet.

    A service account can address a tab by name. The no-credentials CSV export can only
    reach the single tab the URL's gid points at, so it is used as a fallback and says so."""
    parsed = sheets_mod.parse_sheet_url(cfg.get("sheet_url", ""))
    if not parsed["doc_id"]:
        raise ValueError("No sheet_url in config — set it in Settings, or use --csv")
    sa = str(cfg.get("sheet_service_account_file") or "").strip()
    if sa:
        return sheets_mod.SheetsClient(sa).read(parsed["doc_id"], tab)
    print(f"  ! no service account set — reading the URL's own tab, not '{tab}'")
    return sheets_mod.read_via_csv_export(parsed["doc_id"], parsed["gid"])


def build(cfg: dict, rows_by_tab: dict, *, enabled_only: bool = True) -> dict:
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    camps = loaded["campaigns"]
    if enabled_only:
        camps = [c for c in camps if c.enabled]

    issues = campaigns_mod.validate(loaded["campaigns"])
    fieldmaps, map_reports = {}, {}
    for tab, rows in rows_by_tab.items():
        heads = runner_mod.headers_of(rows)
        lane = next((c for c in camps if c.tab == tab), None)
        fm = runner_mod.fieldmap_for(lane, loaded["fieldmaps"], heads) if lane else None
        if fm is None:
            continue
        fieldmaps[tab] = fm
        map_reports[tab] = runner_mod.check_fieldmap(fm, heads)

    led = ledger_mod.Ledger(DATA / "ledger.db") if cfg.get("use_ledger", True) else None
    report = campaigns_mod.plan(rows_by_tab, camps, fieldmaps, ledger=led,
                                globals_cfg=loaded["globals"],
                                mv_rate_usd=float(cfg.get("mv_per_verification_usd", 0) or 0))
    report["config_issues"] = issues
    report["fieldmaps"] = map_reports
    report["campaigns_total"] = len(loaded["campaigns"])
    report["campaigns_enabled"] = len([c for c in loaded["campaigns"] if c.enabled])
    return report


def render(rep: dict) -> int:
    bad = 0
    print(f"\nCampaigns: {rep['campaigns_enabled']} enabled of {rep['campaigns_total']}")

    for tab, m in (rep.get("fieldmaps") or {}).items():
        state = "OK" if m["ok"] else "PROBLEM"
        print(f"\nField map | tab '{tab}' | {state}")
        for b in m["blocking"]:
            bad = 1
            print(f"  X {b}")
        if m["missing_recommended"]:
            print(f"  ! not mapped (that capability is off): {', '.join(m['missing_recommended'])}")

    if rep.get("config_issues"):
        print("\nConfig problems")
        for i in rep["config_issues"]:
            print(f"  X [{i['campaign']}] {i['issue']}")

    rows = rep.get("campaigns") or []
    if not rows:
        print("\nNo enabled campaign matched a tab that was read.")
        return 1

    print(f"\n{'campaign':<20} {'tab':<12} {'matched':>8} {'ledger':>7} {'free':>7} "
          f"{'take':>6} {'est $':>7}")
    print("-" * 72)
    for r in rows:
        print(f"{r['campaign']:<20} {r['tab']:<12} {r['matched']:>8} "
              f"{r['blocked_by_ledger']:>7} {r['available']:>7} {r['take_this_run']:>6} "
              f"{r['estimated_spend_usd']:>7.2f}")
    print("-" * 72)
    print(f"{'TOTAL':<20} {'':<12} {'':>8} {'':>7} {'':>7} {rep['total_take']:>6}")

    for r in rows:
        for w in r.get("warnings") or []:
            mark = "X" if "will be refused" in w else "!"
            if mark == "X":
                bad = 1
            print(f"  {mark} [{r['campaign']}] {w}")
    for w in rep.get("warnings") or []:
        print(f"  ! {w}")

    g = rep.get("globals") or {}
    print(f"\nGlobal caps: {g.get('daily_push_cap')} pushes/day, "
          f"${g.get('daily_spend_cap_usd')}/day")
    print("Nothing was spent. This was a preview.\n")
    return bad


def main(argv: list[str]) -> int:
    args = list(argv)
    as_json = "--json" in args
    enabled_only = "--all" not in args
    csv_path = tab = ""
    for flag, target in (("--csv", "csv"), ("--tab", "tab")):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                if target == "csv":
                    csv_path = args[i + 1]
                else:
                    tab = args[i + 1]

    cfg = load_engine_config()
    loaded = runner_mod.load_config_dir(CONFIG_DIR)
    lanes = [c for c in loaded["campaigns"] if c.enabled or not enabled_only]

    rows_by_tab: dict[str, list[dict]] = {}
    if csv_path:
        p = Path(csv_path)
        if not p.exists():
            print(f"No such file: {p}")
            return 1
        rows_by_tab[tab or (lanes[0].tab if lanes else "Practices")] = read_csv(p)
    else:
        for t in sorted({c.tab for c in lanes if c.tab}):
            try:
                rows_by_tab[t] = read_tab(cfg, t)
                print(f"read tab '{t}': {len(rows_by_tab[t])} rows")
            except Exception as e:                          # noqa: BLE001
                print(f"could not read tab '{t}': {e}")
        if not rows_by_tab:
            print("Nothing to read. Enable a campaign, or pass --csv.")
            return 1

    rep = build(cfg, rows_by_tab, enabled_only=enabled_only)
    if as_json:
        print(json.dumps(rep, indent=2, default=str))
        return 0
    return render(rep)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
