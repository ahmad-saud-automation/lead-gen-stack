# Putting the app on a server

Written 2026-10-04. The server is not chosen yet, so this covers both. **Linux is the
recommended choice**: it costs less, and nothing in the app needs Windows. The only
Windows-only feature is the "From Windows" schedule trigger, and on a server the app's own
clock replaces it.

## What changes on a server

| On your PC | On a server |
|---|---|
| No password (optional) | **Login required.** `LEADGEN_REQUIRE_LOGIN=1` closes every page until a password is set |
| `http://127.0.0.1:3200` | `https://your-domain` through Caddy. Only the screens (3200) are exposed; the engine (8771) stays on 127.0.0.1 |
| `start-app.bat` | `start-app.sh`, run by systemd so it restarts after a crash or reboot |
| Schedules: app or Windows | Schedules: **app**. The engine checks every 30 s while it runs, which on a server is always |

## Linux server (Ubuntu 22.04/24.04 — any small VPS, 1 GB RAM is enough)

```bash
# 1. tools
sudo apt update && sudo apt install -y python3 python3-venv git curl
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
sudo apt install -y caddy            # see caddyserver.com/docs/install if apt has no caddy

# 2. the app, as its own user
sudo useradd -m -s /bin/bash leadgen
sudo mkdir -p /opt/leadgen && sudo chown leadgen /opt/leadgen
sudo -u leadgen git clone <your private repo URL> /opt/leadgen

# 3. secrets — copied by hand, NEVER committed (see below)

# 4. first start + password
cd /opt/leadgen
sudo -u leadgen ./start-app.sh        # installs, builds, starts; stop it with Ctrl+C once it says ready
sudo -u leadgen .venv/bin/python set_password.py

# 5. run it for good
sudo cp deploy/leadgen.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now leadgen

# 6. HTTPS: point a DNS A record (e.g. leads.yourdomain.com) at the server first, then
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain name in it
sudo systemctl reload caddy
```

Open the domain: it asks for the password, then shows the Dashboard.

## Windows server

1. Install Python 3.11+, Node.js 22 and Git; clone the repo.
2. Copy the secrets (below).
3. Set a system environment variable `LEADGEN_REQUIRE_LOGIN=1`, then run
   `python set_password.py` in the app folder.
4. Start with `start-app.bat`. To start it at boot, add a Task Scheduler task "At startup"
   that runs `start-app.bat`.
5. Put HTTPS in front of port 3200 (Caddy for Windows uses the same `deploy/Caddyfile`), and
   set `LEADGEN_SECURE_COOKIE=1` once it is served over HTTPS.

Here both schedule triggers work. Note that a "From Windows" lane runs in a separate
process, so it does not see a run of the same lane started at the same moment in the app.
Pick one trigger per lane, which the app already enforces.

## Secrets — copy by hand, never commit

These are gitignored, so a clone does not have them:

| File | What | On the server |
|---|---|---|
| `data/config.json` | API keys, sheet URL, settings | Copy it, then fix `sheet_service_account_file` to the server's path |
| Google service-account JSON | Sheet access (now `C:\ClaudeDeps\northwind-google-service-account.json`) | Put it outside the app folder, e.g. `/home/leadgen/secrets/`, `chmod 600` |
| `config/campaigns.json` | The lanes | Tracked in git; check it is current before you clone |
| `data/ledger.db` | Which leads are already handled | **Copy it.** Without it the server would work on leads your PC has already done |

Copy over SSH, e.g. `scp data/config.json data/ledger.db leadgen@server:/opt/leadgen/data/`.

## Checks after the first start

- `curl -s http://127.0.0.1:8771/api/auth/status`, run on the server, says `"required": true`
- Opening the domain in a private window lands on the sign-in page
- Plan preview reads the sheet, which proves the service account and the URL
- One **test-mode** run, before any live run

## Not done yet (on purpose)

- **No Docker image.** `start-app.sh` + systemd is simpler to run and to fix. Ask if you want one.
- **One user only.** One password; anyone who has it has full access.
- **Backups of `data/`** (the ledger above all) are not automated on the server yet.
- The Linux script was written on Windows and has **not been run on Linux yet**. Expect the first
  start to need a small fix.
