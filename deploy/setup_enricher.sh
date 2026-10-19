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

echo "==> Extracting DATABASE_URL from ugc-bot.service"
DB_URL="$(sudo systemctl show ugc-bot -p Environment --value \
  | python3 -c "
import sys, shlex
for item in shlex.split(sys.stdin.read()):
    if item.startswith('DATABASE_URL='):
        print(item.split('=', 1)[1])
        break
")"

if [ -z "${DB_URL:-}" ]; then
  echo "ERROR: could not find DATABASE_URL in the bot service environment."
  echo "Run: sudo systemctl show ugc-bot -p Environment"
  exit 1
fi

echo "==> Extracting ROBLOSECURITY_COOKIE_1 from the drop-in"
COOKIE="$(sudo sed -n 's/.*ROBLOSECURITY_COOKIE_1=\(.*\)"/\1/p' \
  /etc/systemd/system/ugc-bot.service.d/roblox.conf 2>/dev/null | head -1 || true)"

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
