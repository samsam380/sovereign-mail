#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $# != 2 ]]; then echo 'Usage: restore.sh SNAPSHOT_ID /absolute/empty/recovery-directory' >&2; exit 1; fi
snapshot=$1
recovery_dir=$2
[[ "$recovery_dir" == /* && "$recovery_dir" != / ]] || { echo 'Choose an absolute, non-root recovery directory.' >&2; exit 1; }
[[ ! -L "$recovery_dir" ]] || { echo 'Recovery target must not be a symlink.' >&2; exit 1; }
if [[ -e "$recovery_dir" ]]; then
  [[ -d "$recovery_dir" ]] || { echo 'Target must be a directory.' >&2; exit 1; }
  [[ -z $(find "$recovery_dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Recovery target must be empty.' >&2; exit 1; }
else
  mkdir -m 700 -p "$recovery_dir"
fi
set -a
source "${BACKUP_ENV_FILE:-/etc/sovereign-mail-backup.env}"
set +a
restic restore "$snapshot" --target "$recovery_dir"
echo 'Restored into a separate directory; live data was not replaced.'
echo 'Follow docs/BACKUPS.md to validate the recovered installation in isolation.'
