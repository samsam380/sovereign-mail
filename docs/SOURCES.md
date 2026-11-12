# Upstream references

Review upstream release and migration notes when deploying.

- Stalwart Docker installation, current v1 image layout, bootstrap wizard and ports: https://stalw.art/docs/install/platform/docker/
- Stalwart setup wizard, initial storage and certificate decisions: https://stalw.art/docs/install/setup-wizard/
- Stalwart system requirements and resource-dependent limits: https://stalw.art/docs/install/requirements/
- Public URLs, private HTTP listeners and forwarding headers: https://stalw.art/docs/server/reverse-proxy/
- Environment variables: https://stalw.art/docs/configuration/environment-variables/
- HTTP settings and client IP handling: https://stalw.art/docs/http/settings/
- ACME challenge selection and reverse proxies: https://stalw.art/docs/server/tls/acme/challenges/
- ACME configuration: https://stalw.art/docs/server/tls/acme/configuration/
- Stalwart app passwords: https://stalw.art/docs/auth/authentication/app-password/
- Installation hardening and plaintext-listener exposure: https://stalw.art/docs/install/security/
- AWS Lightsail outbound port 25 and reverse DNS: https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-configuring-reverse-dns.html
- AWS Lightsail firewall behavior: https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html
- JMAP Core specification, RFC 8620: https://www.rfc-editor.org/rfc/rfc8620
- JMAP for Mail, RFC 8621: https://www.rfc-editor.org/rfc/rfc8621
- Restic repository initialization, SFTP and password-file configuration: https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- Restic recovery: https://restic.readthedocs.io/en/stable/050_restore.html
- Docker Engine official installation: https://docs.docker.com/engine/install/
- Caddy reverse proxy: https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

The 2 GB starting recommendation, one-account pilot, split mx/webmail hostnames, 1 GB pilot quota and phased roadmap are implementation judgments for this project, not upstream minimum requirements or claims of measured capacity.

- Stalwart Docker bind-mount UID and port-binding capability: https://stalw.art/docs/install/troubleshooting/
- Official container definition: https://github.com/stalwartlabs/stalwart/blob/main/Dockerfile

## HTTPS-only shared-host update

- Caddy ACME issuer options, including disabling HTTP-01: https://caddyserver.com/docs/caddyfile/directives/tls
- Caddy automatic redirect controls: https://caddyserver.com/docs/caddyfile/options
- Stalwart Cloudflare token permissions: https://stalw.art/docs/server/dns/provider-notes/
- AWS larger instance from snapshot: https://docs.aws.amazon.com/lightsail/latest/userguide/lightsail-how-to-create-instance-from-snapshot.html

## v0.2 branding and live preparation

The exact four-path icon was recovered from the user's existing Sovereign AI branding installer, not generated.

- Stalwart Cache API schema: https://stalw.art/docs/ref/object/cache/
- SystemSettings API schema: https://stalw.art/docs/ref/object/system-settings/
- RocksDB field limits: https://stalw.art/docs/ref/object/data-store/
- Docker Ubuntu installation: https://docs.docker.com/engine/install/ubuntu/
- Docker forwarding policy: https://docs.docker.com/engine/network/packet-filtering-firewalls/
