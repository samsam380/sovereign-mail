# Deploy Sovereign Mail on your own server

The examples use `example.com`. Substitute your domain and the server’s public address.

## 1. Check the host and existing services


Check your hosting provider’s outbound TCP 25 policy. Set PTR/reverse DNS for the static public IP to your MX hostname. The forward A record must resolve back to that same IP. If the provider restricts direct delivery, you can test the interface and local mail, or configure an approved SMTP smart host in Stalwart. A relay means some outbound mail passes through that provider. No relay account is bundled.

Check for existing listeners before starting:

```bash
sudo ss -ltnp
free -h
df -h
```

If another application owns 25, 465, 993, 80, 443 or loopback 8080, stop and integrate with the existing proxy instead of killing its process. The supplied stack assumes these ports are available.

Run the read-only helper after extracting the project:

```bash
python3 scripts/preflight.py --host YOUR_MX_HOST --web YOUR_WEBMAIL_HOST --expected-ip YOUR_STATIC_PUBLIC_IPV4
```

Allow inbound TCP 25, 465, 993, 80 and 443 in the provider firewall and the host’s network controls. Keep SSH restricted appropriately for your administration path. Do not open 8080 or the gateway's 8787 publicly. Docker-published ports can bypass UFW's usual input rules; use the provider firewall and review Docker's firewall integration. Native mail clients use SMTP 465 with implicit TLS and IMAP 993; 587 is not published in this package. Do not configure them to connect unencrypted on 25.

Recommended initial host: 2 GB RAM or more, one mailbox and a 1 GB mailbox quota. A swap file may reduce abrupt OOM failures but does not replace RAM. Current Stalwart cache limits depend on available host resources; use its sizing guide and observe actual usage. Do not apply unverified arbitrary memory limits to a database and assume it is safe.

## 2. Prepare DNS without switching current mail

In the authoritative DNS provider, create these records, using the real static public IPv4 address. If using Cloudflare, these are **DNS only**, not orange-cloud proxied.

| Name | Type | Value |
|---|---|---|
| `mail.example.com` | A | static public IPv4 |
| `mx.example.com` | A | static public IPv4 |
| `autoconfig.example.com` | CNAME | `mx.example.com` |
| `autodiscover.example.com` | CNAME | `mx.example.com` |
| `mta-sts.example.com` | CNAME | `mx.example.com` |
| `ua-auto-config.example.com` | CNAME | `mx.example.com` |

Only publish AAAA if IPv6 is actually configured and tested for the same ports and forward/reverse DNS. Remove stale AAAA records for these new hosts if they point elsewhere. Check any existing CAA policy permits Let's Encrypt before requesting certificates.

If the domain already receives email elsewhere, retain its current MX until acceptance checks pass. Test receiving at the new server directly with a controlled SMTP client first. Automatic DNS management can publish authentication and policy records: review the provider zone before enabling it, especially existing SPF, DKIM, DMARC, MTA-STS and other mail-service records. Never replace them blindly.

## 3. Install the project and start private setup

Install Docker Engine and Compose v2 using the official Linux instructions for your distribution. Do not pipe an unreviewed installation script into root. Extract this package into `/opt/sovereign-mail`, preserving the scripts' executable permissions.

```bash
cd /opt/sovereign-mail
sudo ./scripts/init.sh
sudoedit .env
sudo ./scripts/init.sh
```

The first invocation creates `.env` and exits. Set `MAIL_DOMAIN`, `WEB_HOST` and `MX_HOST` for your domain. Set `ACME_EMAIL` to an existing, reachable external mailbox. The setup script gives its two persistent bind-mount directories to the official Stalwart image's UID/GID 2000; the database is not recursively rewritten. The second invocation starts **only** Stalwart. It does not start the public reverse proxy.

On your computer, open an SSH tunnel with your server’s username and address.

```bash
ssh -L 8080:127.0.0.1:8080 YOUR_SSH_USER@YOUR_SERVER_PUBLIC_IP
```

Open `http://127.0.0.1:8080/admin`. Read the one-time bootstrap password privately on the server:

```bash
sudo docker compose -f compose.setup.yaml logs --tail=80 stalwart
```

The temporary username is `admin`. Do not send the password, wizard credentials, generated keys or logs to anyone. The wizard generates a different persistent administrator account at the end; save it in your password manager before leaving the last screen.

## 4. Wizard choices and certificates

Use:

| Wizard field | Initial value |
|---|---|
| Server hostname | `mx.example.com` |
| Default email domain | `example.com` |
| Data store | RocksDB, `/var/lib/stalwart/` |
| Account directory | Internal |
| Logging | Console |
| DKIM signing keys | Enabled |

For certificates choose one of these routes:

**Route A — a supported DNS provider, preferred.** Enable automatic certificates and choose your supported DNS provider in the wizard. Stalwart uses DNS-01 for its SMTP/IMAP certificate. Give it credentials scoped to the needed zone rather than your DNS account's master credential. Review which DNS records it will publish. The DNS credentials live inside the mail engine's persisted data and backups. Caddy separately obtains web certificates through its own ACME client.

**Route B — manual DNS management.** Uncheck automatic TLS certificates in the wizard to avoid a failing initial TLS-ALPN order behind Caddy. Finish setup; Caddy can still secure the administration website. After starting the public stack in the next step, sign into `https://mx.example.com/admin`, create or configure a Let's Encrypt ACME provider using **HTTP-01**, and assign that provider to the domain's automatic certificate management. The supplied Caddy HTTP routes forward `/.well-known/acme-challenge/*` to Stalwart's port 8080. Follow upstream ACME settings for the current UI field names. Do not enable SMTP/IMAP client use until Stalwart has obtained the public certificate and you have verified it.

Do **not** select TLS-ALPN-01 with this architecture: Caddy occupies public port 443. A Caddy certificate for the website does not automatically give Stalwart a valid SMTP/IMAP certificate. Route A avoids the need to copy certificates or run a certificate-sync script.

The default Stalwart HTTP listener on 8080 must remain enabled because the gateway and Caddy reach it privately. It stays loopback-only on the host. The container's HTTPS listener on 443 is not published; the public mail-protocol ports are directly mapped to their matching Stalwart listeners.

## 5. Start webmail and finish engine configuration

After the wizard has written `state/etc/config.json`:

```bash
sudo ./scripts/start.sh
sudo docker compose ps
```

This restarts Stalwart out of bootstrap mode and builds/starts the gateway and Caddy. Public bootstrap mode must never be exposed: if entering recovery mode later, stop Caddy first and use the SSH tunnel.

Open `https://mx.example.com/admin` and sign in using the persistent administrator account saved from the wizard. `STALWART_PUBLIC_URL=https://mx.example.com` is already set in Compose so its OAuth and discovery URLs match the proxy.

Under HTTP settings, set `Http.clientIpSource` to `xForwardedFor`, `forwardedHops` to `1`, then reload settings. Both Caddy's direct engine route and the webmail gateway send one authoritative client address. Keep all HTTP listeners private; when trusting these headers, an exposed HTTP listener would allow forged IPs. Test two distinct client IPs and verify the address attributed by Stalwart before relying on auto-ban. Do not enable a PROXY-protocol requirement on these HTTP listeners: this package uses HTTP forwarding headers, not a TCP PROXY header.

Resolve Route B's certificate configuration now if chosen. Check authentication and policy settings, the built-in spam filter, password requirements, request/message limits, outbound rate limits and account quotas in Stalwart. This package relies on the engine for these services and does not assert that every default fits your deployment.

Create an ordinary user with address `demo@example.com`; assign a 1 GB quota for the pilot. Add aliases such as `postmaster@example.com`, `abuse@example.com` and `dmarc@example.com` to a monitored account. Create a mailbox app password for Sovereign Mail. Enable Stalwart two-factor authentication for the administrative account and your daily account. Enroll the webmail authenticator separately using [the 2FA guide](2FA.md). Do not give your daily mailbox administrator permissions.

Confirm Inbox, Drafts, Sent, Archive, Junk and Trash mailboxes have their corresponding standard roles. If a role is missing, create it using the engine or a capable mail client. The webmail deliberately does not invent server folder IDs.

Sign in at `https://mail.example.com` using your full email address and the mailbox app password.

## 6. Email DNS and controlled cutover

Use the **actual** DKIM selector and public key generated by Stalwart. Never use a sample key. Inspect the domain's generated zone file and adapt it to any existing services.

A new, direct-delivery-only domain would typically have:

| Record | Example intent |
|---|---|
| `example.com MX 10 mx.example.com.` | Switch here only after acceptance |
| `example.com TXT "v=spf1 mx -all"` | Authorizes the domain's MX hosts only; extend if other legitimate senders exist |
| `<actual-selector>._domainkey.example.com TXT ...` | Actual Stalwart-generated DKIM public key |
| `_dmarc.example.com TXT "v=DMARC1; p=none; rua=mailto:dmarc@example.com"` | Monitor alignment first, with a working reports mailbox |
| IP provider's PTR | Static public IP → `mx.example.com` |

There must be only one SPF record for the domain. If current MX still points elsewhere, `v=spf1 mx -all` alone will not authorize this new test server. During staged tests, merge the new IP into the existing SPF policy (e.g. an appropriate `ip4:` mechanism) or use a separate test subdomain. Relay use needs the relay's own documented SPF/DKIM alignment requirements.

Move DMARC to quarantine/reject only after every legitimate sender passes alignment. Do not announce an MTA-STS `enforce` policy until its HTTPS policy endpoint, valid certificates, actual MX names and inbound TLS all work. The engine can manage these policies, but they are not arbitrary static records to paste without verification.

Complete all of [ACCEPTANCE.md](ACCEPTANCE.md), including authenticated send/receive, open-relay refusal and SPF/DKIM/DMARC headers. Then switch MX deliberately. Keep the previous mail service reachable during DNS propagation, if one exists.

## 7. Reboots and updates

Compose services use `restart: unless-stopped`. Enable the Docker service at boot according to your distribution. A service explicitly stopped by an administrator remains stopped until started.

Record working image identities:

```bash
sudo docker image inspect stalwartlabs/stalwart:v1 --format '{{json .RepoDigests}}'
sudo docker image inspect caddy:2-alpine --format '{{json .RepoDigests}}'
```

After acceptance, replace the image values in `.env` with the actual returned digest references. Never paste placeholder digests. For an upgrade, first create and test a backup, read upstream migration notes, select the new image digest, then recreate the changed service. Retain the matching prior binary and its backup for rollback; an old image against an upgraded database is not a safe rollback plan.

## HTTPS-only layout

If port 80 already serves another application, select `COMPOSE_FILE=compose.aws.yaml` in `.env`. Caddy binds port 443 and uses TLS-ALPN-01 for web certificates. Configure Stalwart with a supported DNS-01 provider for its mail certificates. Open your webmail URL with `https://`. Keep the same project and state directory throughout setup.

The optional low-memory pilot uses `compose.setup.yaml` for private setup, `scripts/configure-live.sh` for engine tuning, and `scripts/start-live.sh` for startup. Validate resource use before relying on that profile.
