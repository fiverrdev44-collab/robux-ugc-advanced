#!/usr/bin/env bash
# Runs a pipeline script on Server 2 with the Oracle pipeline environment.
# Called by GitHub Actions over SSH.
#
# Usage:
#   bash deploy/run_on_oracle.sh scanner.py
#   bash deploy/run_on_oracle.sh enricher.py REFRESH_MODE=true
#   bash deploy/run_on_oracle.sh backfill_dates.py BATCH_SIZE=3000

set -euo pipefail

cd /home/ubuntu/robux-ugc-advanced

# Always run the latest code.
git fetch origin
git reset --hard origin/main

ENV_FILE="/etc/ugc-bot/pipeline.env"
VENV_PY="/home/ubuntu/ugc_env/bin/python"

"$VENV_PY" - "$@" <<'PY'
import os
import subprocess
import sys

env = dict(os.environ)

env_file = "/etc/ugc-bot/pipeline.env"
try:
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
except FileNotFoundError:
    pass

cmd = []
for arg in sys.argv[1:]:
    # KEY=VALUE overrides (but not file names like scanner.py)
    if "=" in arg and not arg.endswith(".py"):
        k, v = arg.split("=", 1)
        env[k] = v
    else:
        cmd.append(arg)

if not cmd:
    raise SystemExit("No script specified")

subprocess.run(
    ["/home/ubuntu/ugc_env/bin/python", "-u"] + cmd,
    env=env,
    check=True,
)
PY
