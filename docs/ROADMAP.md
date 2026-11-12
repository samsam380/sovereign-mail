# From personal mailbox to a mature mail service

## Phase 1: one dependable personal address

Deploy the included stack with one account. Complete DNS, certificate and open-relay checks. Test Gmail/Outlook round trips. Watch queues, spam placement, RAM, disk and certificate expiry. Perform a backup and restore drill. Keep important recovery and banking accounts on your proven address until this has a reliable operating history.

## Phase 2: a fuller daily client

Add OAuth authorization-code login with PKCE to avoid a gateway-held app password; keep mailbox/admin identities separate. Add automatic draft saving with concurrency protection, rich-text editing with a separately audited sanitization boundary, thread views, contacts, sender identities, managed aliases, labels/custom folders, push notifications and quota UI. Add protocol tests against pinned Stalwart images and browser automation to CI.

## Phase 3: operations worthy of a primary mailbox

Introduce monitoring with a separately hosted alert destination, certificate/backup/queue alerts, restoration exercises, resource sizing and update windows. Replace cold-backup downtime with supported consistent exports/snapshots as mail volume grows. Review inbound spam/phishing controls with real traffic. Add independent recovery credentials and offline backup copies.

## Phase 4: privacy and availability with a defined threat model

Decide whether protecting a stolen disk, an administrator, a compromised host, an email counterparty, or all of these is the goal. Host disk encryption, engine encryption-at-rest options, OpenPGP/S/MIME and client-side zero-access design protect against different threats. Do not market TLS as end-to-end encryption. Ordinary external SMTP recipients also need compatible encryption to receive genuinely end-to-end encrypted content.

For availability, design a supported shared-store Stalwart cluster or a deliberate recovery/failover procedure. Two unrelated active mail servers with copied folders are not a coherent cluster. A secondary MX can queue inbound mail when correctly operated, but does not replicate mailbox state and can create a spam-filtering bypass if configured carelessly.

## Scope of the ambition

A good personal Gmail alternative is realistic. Matching Gmail's global delivery reputation, search scale, abuse team, uptime, clients and integrations is a sustained product and operations effort. Matching Proton's privacy claims requires a defined cryptographic design, key recovery policy and independent security review. This release is a concrete base for the first phase.
