#!/usr/bin/env bash
# Loopback-only sample-data preview on the small AWS host. No Docker or mail engine.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export ALLOW_HTTP=1 DEMO_MODE=1 PUBLIC_ORIGIN=http://127.0.0.1:8787
export BIND=127.0.0.1 PORT=8787
exec python3 app/server.py
