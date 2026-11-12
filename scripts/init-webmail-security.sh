#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo to prepare the private webmail security directory.' >&2; exit 1; }
install -d -m 700 -o 10001 -g 10001 state/webmail
docker compose config --quiet
docker compose build webmail
docker compose run --rm --no-deps --entrypoint python webmail \
  /app/mfa.py --init /var/lib/sovereign-mail
