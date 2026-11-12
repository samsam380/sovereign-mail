#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ -s state/etc/config.json ]] || { echo 'Complete private Stalwart setup first. See docs/DEPLOY.md.' >&2; exit 1; }
docker compose config --quiet
bash scripts/init-webmail-security.sh
# The wizard writes config but remains in bootstrap mode until restart.
docker compose restart stalwart
docker compose up -d --build
printf '%s\n' 'Services started. Use docs/ACCEPTANCE.md before switching your domain MX.'
