#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ram_kib=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if (( ram_kib < 1900000 )) && [[ ${EXPERIMENTAL_LOW_MEMORY:-0} != 1 ]]; then
  echo 'Full AWS startup paused: use >=2 GB RAM and tune caches, or run the sample preview.' >&2
  exit 1
fi
export COMPOSE_FILE=compose.aws.yaml
exec bash scripts/start.sh
