"""
answer_template.py — Claude Code answers the Cold email request queue (2026-11-06).

A pipeline campaign's "Request a template" does not call a paid AI service: the request
waits in the queue. Claude Code reads it, writes the draft, and hands it back here. The app
then scores it against the copy rules; at 90 or more (and with auto-approve on) it goes live
by itself, otherwise it waits on the Cold email page for a person.

  python answer_template.py campaign:pipeline-showcase                   list waiting requests
  python answer_template.py campaign:pipeline-showcase 3 draft.json      answer request 3

draft.json = {"subject": "...", "body": "..."}  (variables: {{first_name}} {{company}} {{ice_breaker}})
Works on the same database as the running app (data/stack.db): no restart needed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LEADGEN_NO_SCHEDULER", "1")
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))
import server as S  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    source = argv[0]
    p = S._stack_parts(source)
    if len(argv) == 1:
        waiting = [r for r in S._stack_store().requests(p["store_source"]) if r.get("state") == "queued"]
        print(f"{p['name']}: {len(waiting)} request(s) waiting")
        for r in waiting:
            print(f"  #{r['id']}  {r.get('kind', '')}: {r.get('instructions', '')}")
        return 0
    draft = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    r = S.stack_email_answer(source, int(argv[1]), str(draft.get("subject") or ""), str(draft.get("body") or ""))
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
