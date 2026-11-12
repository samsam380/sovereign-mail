#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
project_root=$PWD
backup_config=${BACKUP_ENV_FILE:-/etc/sovereign-mail-backup.env}
[[ -r "$backup_config" ]] || { echo "Missing $backup_config" >&2; exit 1; }
# This is a trusted root-owned local shell configuration file, never a downloaded input.
set -a
source "$backup_config"
set +a
: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD_FILE:?Set RESTIC_PASSWORD_FILE}"
command -v restic >/dev/null
command -v flock >/dev/null
exec 9>/var/lock/sovereign-mail-backup.lock
flock -n 9 || { echo 'A backup is already running.' >&2; exit 1; }
[[ -s state/etc/config.json ]] || { echo 'Refusing backup of an uninitialized installation.' >&2; exit 1; }
# Check credentials and repository availability BEFORE stopping the mail server.
# This intentionally fails instead of initializing or changing a repository.
restic snapshots --latest 1 >/dev/null
mapfile -t running_services < <(docker compose ps --services --status running)
[[ ${#running_services[@]} -gt 0 ]] || { echo 'No services are running; perform a manual cold backup instead.' >&2; exit 1; }
restart_services() {
  result=$?
  trap - EXIT
  if ! docker compose start "${running_services[@]}"; then
    echo 'URGENT: services did not restart after backup. Run docker compose start.' >&2
    exit 1
  fi
  exit "$result"
}
trap restart_services EXIT
# Cold backup: pause all writers; never copy a live RocksDB directory.
docker compose stop --timeout 90 "${running_services[@]}"
# No retention deletion is performed automatically. Keep the recovery password
# separately: the snapshot is deliberately useless without it.
restic backup --tag sovereign-mail "$project_root/state" "$project_root/app" \
  "$project_root/deploy" "$project_root/scripts" "$project_root/compose.yaml" "$project_root/compose.aws.yaml" "$project_root/compose.setup.yaml" "$project_root/compose.pilot.yaml" "$project_root/.env" \
  "$project_root/README.md" "$project_root/docs"
echo 'Encrypted backup completed. Restarting services.'
