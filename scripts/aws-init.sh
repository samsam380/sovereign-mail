#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# An operator may explicitly opt into a measured experiment. This is a project
# guardrail, not an upstream minimum RAM claim; swap is not counted as RAM.
ram_kib=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if (( ram_kib < 1900000 )) && [[ ${EXPERIMENTAL_LOW_MEMORY:-0} != 1 ]]; then
  echo 'Full AWS setup paused: this project recommends >=2 GB physical RAM, with tuned mail caches.' >&2
  echo 'For the existing small host, use scripts/preview-server.sh (sample data, no real mail).' >&2
  exit 1
fi
export COMPOSE_FILE=compose.aws.yaml
exec bash scripts/init.sh
