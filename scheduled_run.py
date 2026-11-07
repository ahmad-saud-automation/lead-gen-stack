"""
scheduled_run.py - run the pipeline headlessly (for Windows Task Scheduler).

Reuses the exact same engine, config and data files as the web app, so a scheduled
run shows up in the app's History, Log and Results just like a manual one. The app
does NOT need to be running.

    python scheduled_run.py                 # run with saved settings (test mode off)
    python scheduled_run.py --test           # no-spend dry run
    python scheduled_run.py --from-sheet     # pull leads from the configured Sheet first
    python scheduled_run.py --push           # also push verified leads to Instantly
    python scheduled_run.py --campaign <id> [--test]
                                             # one campaign lane (V4): its next batch, then
                                             # the push only if the lane has auto_push on
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp import server as S  # noqa: E402


def run_campaign(cid: str, test_mode: bool) -> int:
    """What a lane's Windows task (LeadGen-<id>) runs. Same guards as the app's own clock."""
    camp = next((c for c in S.runner_mod.load_config_dir(S.CONFIG_DIR)["campaigns"] if c.id == cid), None)
    if camp is None:
        print(f"campaign {cid}: not in config/campaigns.json - remove its task")
        return 1
    snap = S.fire_lane(camp, test_mode=test_mode, wait=True, source="windows")
    if snap.get("error"):
        print(f"campaign {cid}: not started - {snap['error']}")
        S._sched_log(f"{cid}: windows task did not start a run — {snap['error']}")
        return 1
    done = S.get_run(snap["run_id"]) or {}
    c = done.get("counters", {})
    print(f"campaign {cid} run {snap['run_id']}: {done.get('processed')}/{done.get('total')} leads, "
          f"found={c.get('found')}")
    return 0


def main(argv: list[str]) -> int:
    test_mode = "--test" in argv
    if "--campaign" in argv:
        i = argv.index("--campaign")
        if i + 1 >= len(argv):
            print("--campaign needs a campaign id")
            return 2
        return run_campaign(argv[i + 1], test_mode)
    from_sheet = "--from-sheet" in argv
    do_push = "--push" in argv

    if from_sheet:
        try:
            info = S.load_leads_from_sheet()
            print(f"sheet: imported {info.get('count', 0)} firms from {info.get('files', ['sheet'])[0]}")
        except Exception as e:  # noqa: BLE001 - keep going with whatever leads are saved
            print(f"sheet import failed ({e}) - using the saved lead list")

    snap = S.start_run(test_mode)
    if snap.get("error"):
        print("run not started:", snap["error"])
        return 1
    run_id = snap["run_id"]
    S.wait_for_job(run_id)
    done = S.get_run(run_id) or {}
    c = done.get("counters", {})
    print(f"run {run_id}: {done.get('processed')}/{done.get('total')} leads · "
          f"found={c.get('found')} held={c.get('held')} not_found={c.get('not_found')} "
          f"credits={(done.get('credits') or {}).get('total_credits')}")

    if do_push:
        p = S.start_push(run_id, test_mode=test_mode, confirm=True)
        if p.get("error"):
            print("push not started:", p["error"])
            return 1
        S.wait_for_job(p["run_id"])
        pd = S.get_run(p["run_id"]) or {}
        print(f"push {p['run_id']}: pushed={pd.get('counters', {}).get('pushed')} "
              f"failed={pd.get('counters', {}).get('push_failed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
