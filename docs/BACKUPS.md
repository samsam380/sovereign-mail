# Encrypted mail backups

Restic encrypts data before sending it through SFTP. Select your active Compose layout in the service environment before enabling the backup timer.

## Destination and SSH

On the backup server, choose a dedicated unprivileged account, e.g. `mailbackup`, and a private repository directory such as `/srv/backups/sovereign-mail`. Give only that account access. The directory must be reachable from the mail server over an authenticated SSH path.


Create a dedicated backup SSH key on the primary server, install its **public** key for the backup account, and verify the backup server’s SSH host key against a trusted console/known fingerprint. Populate the backup operator's `known_hosts`. Test noninteractive SSH/SFTP. Do not disable host-key checking or use your general administrator key for this job. Restrict the backup account to its intended data path; a properly configured SFTP-only account can be used by restic.

## Initialize once

Install restic on the primary server from the official package source. Copy the provided configuration example:

```bash
sudo install -m 600 deploy/backup.env.example /etc/sovereign-mail-backup.env
sudoedit /etc/sovereign-mail-backup.env
```

Set the actual reachable destination in `RESTIC_REPOSITORY`. Create a long random repository password in `/etc/sovereign-mail-restic-password` (mode 600, root-owned), and keep a separate recovery copy offline or in your password manager. Do not print it in shell history, commit it or store its only copy on the mail server. Losing it makes the encrypted backup unrecoverable.

Initialize the repository deliberately, once, after checking that the configured path is the intended new destination:

```bash
sudo bash -c 'set -a; source /etc/sovereign-mail-backup.env; set +a; restic init'
```

The backup script never initializes repositories automatically.

## First backup and restore drill

```bash
cd /opt/sovereign-mail
sudo ./scripts/backup.sh
sudo bash -c 'set -a; source /etc/sovereign-mail-backup.env; set +a; restic snapshots'
sudo bash -c 'set -a; source /etc/sovereign-mail-backup.env; set +a; restic check'
```

This is a **cold backup**: the script checks repository access, locks out concurrent jobs, remembers the running Compose services, stops them gracefully, backs up the persisted data and configuration, then restarts those services even if restic reports an error. It refuses an uninitialized installation. Never copy a live RocksDB directory with plain rsync.

All services are paused for the duration of the backup. That may be seconds for a small mailbox but much longer for the initial backup or a slow link. Outbound sending and webmail are unavailable during this time; other properly behaving MTAs will usually queue inbound mail and retry. There is no guarantee every sender will retry. Sessions disappear when the gateway restarts, so sign in again afterward. If you need uninterrupted availability, replace this cold backup with an engine-supported export/snapshot approach and test its consistency before relying on it.

The service allows up to two hours. A killed job normally triggers cleanup; a host crash or uncatchable termination can still interrupt restart. Monitor the timer, last successful snapshot time and actual services; do not assume scheduling proves success. Docker's restart policy helps after a host reboot but is not a backup monitor.

Restore a specific snapshot into a **new empty directory**, not over the running server:

```bash
sudo ./scripts/restore.sh SNAPSHOT_ID /srv/mail-recovery-test
```

Restic preserves the original absolute path below the target. A project stored at `/opt/sovereign-mail` will usually appear at `/srv/mail-recovery-test/opt/sovereign-mail/`. Inspect the restored tree and file ownership.

Validate the recovered system on a separate isolated machine/network with temporary local-only port mappings and a different Compose project name. Use the exact image digests recorded for that snapshot. Do not publish it as a second sender or point public MX at it during the drill. Disable its outbound delivery while testing so restored queue entries cannot resend old messages. Verify a known message, attachment hash, mailbox identities, signing keys, certificate configuration and settings. Do not delete the current installation until a recovery plan has actually passed.

Backups include `state/` (engine configuration/database, messages and Caddy state), app/source deployment configuration and documentation. They may therefore include DNS API credentials, TLS private keys and mail. They exclude the restic repository password file and operator's SSH keys, which live outside the project. Keep recovery access and those keys separately. Restic snapshots preserve file owner/permission metadata; restoration needs an appropriate privileged operator.

## Nightly scheduling

Only after a successful backup and restore drill:

```bash
sudo install -m 644 deploy/sovereign-mail-backup.service /etc/systemd/system/
sudo install -m 644 deploy/sovereign-mail-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sovereign-mail-backup.timer
sudo systemctl list-timers sovereign-mail-backup.timer
```

The timer runs around **03:30 UTC**, with up to ten minutes of random delay. It uses `/opt/sovereign-mail`. Change the unit if installed elsewhere.

Inspect actual results:

```bash
sudo systemctl status sovereign-mail-backup.service
sudo journalctl -u sovereign-mail-backup.service --since yesterday
```

The scripts deliberately do not delete snapshots. Review storage use and decide retention after recovery testing. A possible policy is 7 daily, 4 weekly and 12 monthly snapshots, but run restic `forget --dry-run` and inspect the proposed deletions before applying any retention/pruning command. Retention is not automatically configured.

A credential that can write an ordinary restic repository can usually delete its data too. This is not an immutable or ransomware-proof backup. For stronger protection, make an independent offline copy or configure a separately administered append-only backup service and test its recovery model.
