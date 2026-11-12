#!/usr/bin/env bash
# After the wizard, tuning, DNS A records, firewall and TLS prerequisites.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo bash scripts/start-live.sh.' >&2; exit 1; }
[[ -s state/etc/config.json && -f state/pilot-tuned ]] || { echo 'Complete private wizard and tune-small-host.py first.' >&2; exit 1; }
[[ ${EXPERIMENTAL_LOW_MEMORY:-0} == 1 ]] || { echo 'For the requested small-host trial, set EXPERIMENTAL_LOW_MEMORY=1 explicitly.' >&2; exit 1; }
export COMPOSE_FILE=compose.pilot.yaml
# Persist the chosen layout for later ordinary docker compose operations and backups.
python3 - <<'PY'
from pathlib import Path
p=Path('.env');lines=p.read_text().splitlines()
lines=[x for x in lines if not x.startswith('COMPOSE_FILE=')]
lines.append('COMPOSE_FILE=compose.pilot.yaml');p.write_text('\n'.join(lines)+'\n');p.chmod(0o600)
PY
docker compose config --quiet
bash scripts/init-webmail-security.sh
# Load memory/proxy changes while engine ports are still loopback-only.
docker compose -f compose.setup.yaml restart stalwart
# Validate the actual Caddy binary/config before publishing the web listener.
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose up -d --build
cat <<'TXT'
Public pilot services started. This does not prove successful certificate issuance or delivery.
Check the configured webmail and Stalwart administration URLs.
Check: sudo docker compose ps
Check: sudo docker stats --no-stream
Keep current MX until TLS, authenticated sending and receiving, and open-relay checks pass.
The trial can still run out of memory; container limits do not add physical RAM.
TXT
