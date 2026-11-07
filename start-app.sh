#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Lead Gen Automation Engine — Linux / server start. The Windows twin is start-app.bat.
#
# Two processes:
#   - the engine (Python) on 127.0.0.1:8771 — never exposed, reached only through the screens
#   - the screens (Next.js) on 127.0.0.1:3200 — put HTTPS (Caddy or nginx) in front of THIS
#
#   ./start-app.sh            install what is missing, build once, start
#   ./start-app.sh rebuild    rebuild the screens first (after editing web/)
#
# A login is REQUIRED here (LEADGEN_REQUIRE_LOGIN=1): until `python set_password.py` has been
# run, every page asks for a password that does not exist yet, so a fresh server is never open.
# The engine's own clock runs the scheduled lanes, so keep exactly ONE engine process (no
# uvicorn --workers): two would fire every schedule twice.
# See docs/DEPLOY.md.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

export LEADGEN_REQUIRE_LOGIN="${LEADGEN_REQUIRE_LOGIN:-1}"
PY="${PYTHON:-python3}"

command -v node >/dev/null 2>&1 || { echo "Node.js 18+ is required: https://nodejs.org"; exit 1; }

# ---- the engine's packages, in a venv beside the app (.venv is gitignored)
if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  "$PY" -m venv .venv
fi
.venv/bin/python -c "import fastapi, uvicorn, multipart, googleapiclient" 2>/dev/null \
  || .venv/bin/pip install -q -r requirements.txt

if [ "$LEADGEN_REQUIRE_LOGIN" = "1" ] && [ ! -f data/auth.json ]; then
  echo
  echo "  No password is set yet, so the app will only show its sign-in page."
  echo "  Set one now in another terminal:  .venv/bin/python set_password.py"
  echo
fi

# ---- the screens
(
  cd web
  if ! node -e "require.resolve('next/package.json')" >/dev/null 2>&1; then
    echo "Installing the screen packages ..."
    npm ci --no-audit --no-fund
  fi
  if [ "${1:-}" = "rebuild" ]; then rm -f .next/BUILD_ID; fi
  if [ ! -f .next/BUILD_ID ]; then
    echo "Building the screens ..."
    npm run build
  fi
)

# ---- start both; stopping this script stops both
.venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8771 --log-level warning &
ENGINE=$!
trap 'kill "$ENGINE" 2>/dev/null || true' EXIT INT TERM

echo "Lead Gen Automation Engine — screens on http://127.0.0.1:3200 (engine pid $ENGINE)"
cd web
npm run start
