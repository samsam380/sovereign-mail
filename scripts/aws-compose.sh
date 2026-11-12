#!/usr/bin/env bash
# Keep every AWS operation, including backups, on the same Compose configuration.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export COMPOSE_FILE=compose.aws.yaml
exec docker compose "$@"
