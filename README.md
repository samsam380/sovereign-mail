# Sovereign Mail

Sovereign Mail is a self-hosted email stack with a browser client for Stalwart. Stalwart handles SMTP, IMAP and JMAP, and Caddy provides HTTPS for the webmail and administration sites.

- Inbox, Sent, Drafts, Archive, Spam, Trash, search and unread filters.
- Plain-text compose, reply, forward, manual draft saving and attachments.
- Light, Dark and Teal themes with responsive layouts.
- Optional webmail two-factor authentication using a QR code or manual setup key, with one-use recovery codes.
- Docker Compose deployment and encrypted restic backups over SSH/SFTP.

## Try the preview

Run `npm run dev` with Node.js 20 or later and open `http://127.0.0.1:8787`. The preview uses fictional mail and stores changes only for that page session. Open `Sovereign-Mail-Preview.html` for the standalone offline preview. Rebuild it after frontend changes with `python3 scripts/build-preview.py`.

## Deploy

1. Install Docker Engine and the Compose v2 plugin on a Linux server.
2. Run `sudo ./scripts/init.sh` to create `.env`. Set your domain, webmail and MX hostnames, and ACME contact email.
3. Run `sudo ./scripts/init.sh` again and complete the Stalwart wizard through an SSH tunnel.
4. Configure DNS and TLS using [the deployment guide](docs/DEPLOY.md), then run `sudo ./scripts/start.sh`.
5. Create a regular Stalwart mailbox and a dedicated app password. Sign in to webmail and enroll an authenticator in **Settings → Two-factor authentication**.
6. Complete the [acceptance checks](docs/ACCEPTANCE.md) before switching MX records and test the [backup and restore procedure](docs/BACKUPS.md).

The deployment guide describes the HTTPS-only Compose layout for servers with an existing service on port 80. The default layout uses ports 80 and 443. The private setup profile binds administration to loopback on port 8080. Use the same Compose project and state directory throughout setup.

## Test

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r app/requirements.txt PyYAML
npm test
```

For the optional DOM integration test, install `jsdom@26.1.0` with `npm install --no-save --package-lock=false jsdom@26.1.0` and run `node --test tests/mfa-ui.test.cjs` with the virtual environment active. The tests use a local JMAP fixture. Check Docker startup, certificates and real SMTP delivery on your deployment.

## Mail and account security

The gateway uses HttpOnly session cookies, CSRF checks and a limited set of JMAP methods. Remote images are blocked, and attachments are downloaded as files. Webmail authenticator enrollment and recovery are described in [the 2FA guide](docs/2FA.md). Stalwart client protocols and its administrator login have their own authentication settings.

Keep your `.env`, `state/`, SSH keys, mailbox app passwords and backup credentials outside Git. The state directory includes mail, Stalwart settings, TLS keys and authenticator state. Protect and restore those files together through encrypted backups.

Upstream [documentation references](docs/SOURCES.md) cover the mail engine, reverse proxy and restic.
