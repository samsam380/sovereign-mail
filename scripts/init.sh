#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
[[ $EUID == 0 ]] || { echo 'Run this setup script with sudo so persistent directories get the mail engine UID.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Install Docker Engine and the Docker Compose v2 plugin from docs.docker.com first.' >&2; exit 1; }
docker compose version >/dev/null
if [[ ! -f .env ]]; then
  install -m 600 .env.example .env
  echo 'Created .env. Set your domain, mail hostnames and ACME contact email, then run this command again.'
  exit 0
fi
if [[ $(sed -n 's/^ACME_EMAIL=//p' .env) == REPLACE_WITH_YOUR_EXISTING_EMAIL ]]; then
  echo 'Edit ACME_EMAIL in .env before proceeding.' >&2; exit 1
fi
# No image is downloaded or service modified until Compose validates.
docker compose config --quiet
ram_kib=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
if (( ram_kib < 1900000 )); then
  echo 'This host has less than 2 GB RAM. Use it only for a measured experiment; other services also need headroom.'
fi
install -d -m 700 state state/etc state/mail state/caddy state/caddy/data state/caddy/config
# Official Stalwart v1 images run as uid/gid 2000. Bind mounts retain host ownership.
# Change only the two mount roots; do not recursively rewrite an existing database.
chown 2000:2000 state/etc state/mail
chmod 600 .env
if [[ -f state/etc/config.json ]]; then
  echo 'Stalwart is already initialized. Use scripts/start.sh; no configuration was replaced.'
  exit 0
fi
docker compose -f compose.setup.yaml config --quiet
docker compose -f compose.setup.yaml up -d stalwart
cat <<'TXT'
Mail engine started in private bootstrap mode. Public webmail has not started.
From your computer, open an SSH tunnel:
  ssh -L 8080:127.0.0.1:8080 YOUR_SSH_USER@YOUR_SERVER_IP
Open http://127.0.0.1:8080/admin in your browser.
Read the temporary credentials PRIVATELY on the server with:
  docker compose -f compose.setup.yaml logs --tail=80 stalwart
Follow docs/DEPLOY.md for the wizard, DNS and certificate choices.
Do not paste credentials or logs into a public issue or conversation.
TXT
