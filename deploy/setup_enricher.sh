#!/usr/bin/env bash
# Installs a standalone enricher worker on Server 2.
# It runs independently of ugc-bot, so bot restarts cannot kill it.
#
# Usage:  cd ~/robux-ugc-advanced && bash deploy/setup_enricher.sh

set -euo pipefail

REPO="/home/ubuntu/robux-ugc-advanced"
VENV_PY="/home/ubuntu/ugc_env/bin/python"
ENV_DIR="/etc/ugc-bot"
ENV_FILE="$ENV_DIR/pipeline.env"
SERVICE="/etc/systemd/system/ugc-enrich.service"

sudo mkdir -p "$ENV_DIR"

if [ -f "$ENV_FILE" ]; then
  echo "==> Using existing $ENV_FILE"
else
  echo "==> Extracting DATABASE_URL from ugc-bot.service"
  DB_URL="$(sudo systemctl show ugc-bot -p Environment --value \
    | python3 -c "
import sys, shlex
for item in shlex.split(sys.stdin.read()):
    if item.startswith('DATABASE_URL='):
        print(item.split('=', 1)[1])
        break
" || true)"

  # Fallback: read the running bot process's environment.
  if [ -z "${DB_URL:-}" ]; then
    PID="$(pgrep -f discord_ugc_bot.py | head -1 || true)"
    if [ -n "${PID:-}" ]; then
      echo "==> Falling back to /proc/$PID/environ"
      DB_URL="$(sudo tr '\0' '\n' < "/proc/$PID/environ" \
        | sed -n 's/^DATABASE_URL=//p' | head -1)"
      COOKIE="$(sudo tr '\0' '\n' < "/proc/$PID/environ" \
        | sed -n 's/^ROBLOSECURITY_COOKIE_1=//p' | head -1)"
    fi
  fi

  if [ -z "${DB_URL:-}" ]; then
    echo
    echo "ERROR: could not find DATABASE_URL automatically."
    echo
    echo "Create the env file manually, then re-run this script:"
    echo
    echo "  sudo tee $ENV_FILE >/dev/null <<'EOF'"
    echo "  DATABASE_URL=postgresql://ugc_user:UgcSuper2026!@10.0.0.171:5432/ugc_db"
    echo "  ROBLOSECURITY_COOKIE_1=<paste cookie here>"
    echo "  ENRICH_BATCH_SIZE=300"
    echo "  PYTHONUNBUFFERED=1"
    echo "  EOF"
    echo "  sudo chmod 600 $ENV_FILE"
    echo
    exit 1
  fi

  if [ -z "${COOKIE:-}" ]; then
    echo "==> Extracting ROBLOSECURITY_COOKIE_1 from the drop-in"
    COOKIE="$(sudo sed -n 's/.*ROBLOSECURITY_COOKIE_1=\(.*\)"/\1/p' \
      /etc/systemd/system/ugc-bot.service.d/roblox.conf 2>/dev/null | head -1 || true)"
  fi

  echo "==> Writing $ENV_FILE"
  {
    echo "DATABASE_URL=$DB_URL"
    if [ -n "${COOKIE:-}" ]; then
      echo "ROBLOSECURITY_COOKIE_1=$COOKIE"
    fi
    echo "ENRICH_BATCH_SIZE=300"
    echo "PYTHONUNBUFFERED=1"
  } | sudo tee "$ENV_FILE" >/dev/null
  sudo chmod 600 "$ENV_FILE"
fi

echo "==> Writing $SERVICE"
sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=UGC Enricher Worker (standalone)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$REPO
EnvironmentFile=$ENV_FILE
ExecStart=/bin/bash -c 'while true; do $VENV_PY -u enricher.py; sleep 60; done'
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ugc-enrich

echo
echo "==> Started. Watch progress with:"
echo "    journalctl -u ugc-enrich -f"
echo
echo "==> Check the backlog with:"
echo "    PGPASSWORD=... psql ... -c \"SELECT count(*) FROM items;\""
