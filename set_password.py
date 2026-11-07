"""
set_password.py - set (or change) the app's login password from the server's terminal.

    python set_password.py

Asks twice, without echoing. Use it on a fresh server: there, the app refuses every request
until a password exists (start-app.sh sets LEADGEN_REQUIRE_LOGIN=1). Setting it signs every
browser out. On your own PC you can do the same from Settings instead.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import auth as auth_mod  # noqa: E402

AUTH_FILE = ROOT / "data" / "auth.json"


def main() -> int:
    first = getpass.getpass("New password: ")
    why = auth_mod.check_strength(first)
    if why:
        print(f"Not saved: {why}.")
        return 1
    if getpass.getpass("Same again: ") != first:
        print("Not saved: the two did not match.")
        return 1
    auth_mod.save(AUTH_FILE, auth_mod.make(first))
    print(f"Saved to {AUTH_FILE}. Every browser has been signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
