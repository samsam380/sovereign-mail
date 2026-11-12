# Sovereign Mail authenticator setup

Deploy the webmail using [the deployment guide](DEPLOY.md). The startup script initializes the persistent authenticator store. Stalwart administrator authentication is configured in Stalwart.

## Activate your authenticator

1. Open your webmail URL and sign in with your mailbox app password.
2. Open the gear icon or your account button, then **Two-factor authentication**.
3. Choose **Set up authenticator** and confirm your mailbox password.
4. In Google Authenticator choose **+ → Scan a QR code**. Alternatively select
   **Enter a setup key**, paste the displayed manual key, and select **Time based**.
5. Enter a fresh six-digit code on Sovereign Mail, then select **Enable two-factor
   authentication**. Protection starts only after a valid confirmation.
6. Save the ten recovery codes privately. Each works once; they cannot be shown
   again. You can download them from the confirmation screen.
7. Sign out and back in. After the mailbox password, enter a fresh authenticator
   code. A code already used for enrollment or a login cannot be used again;
   wait for the next code when testing immediately after setup.

The server accepts the current 30-second TOTP interval and one adjacent interval
on either side for clock drift, with replay prevention. Five failed checks lock
code verification for five minutes across new login challenges. Ensure the server
and your phone use automatic time synchronization.

## Recovery and account changes

At the code screen, choose **Use a recovery code** if your authenticator is
unavailable. After logging in, regenerate recovery codes or turn off 2FA from
settings; both require your mailbox password and a fresh authenticator or unused
recovery code. Regenerating codes replaces the old set. Enabling, disabling, or
regenerating invalidates older webmail sessions. Account aliases share one MFA
configuration.

Keep the existing administrative/SSH recovery access. An operator with root access
can alter the service; this feature is not protection against a compromised server.
There is no email/SMS backdoor for resetting the authenticator.

## Persistent security data and backups

`state/webmail/security.sqlite3` contains encrypted TOTP seeds, one-use recovery-code
hashes, replay counters, and lockouts. `state/webmail/master.key` is the private
encryption key. Both live in the private directory owned by container UID 10001.
Restore the database and key together. The daemon refuses to create missing
production state silently; deleting state is not a recovery procedure.

The project's existing cold-backup script includes all of `state/`, so it also
captures this directory. Keep those backups encrypted. The encryption key lives
on the server beside the database; encryption protects an isolated database copy,
not an attacker who controls the host or obtains the complete backup and its key.

MFA protects browser access through this gateway. A stolen Stalwart app password
may still work in enabled IMAP/SMTP/JMAP clients; use dedicated, revocable app
passwords and keep the upstream JMAP listener private.

## Validation

The test suite covers TOTP vectors, persistent state, one-use codes, lockouts, alias handling, pre-authentication isolation, CSRF and session invalidation. The optional DOM test exercises setup, incorrect codes and recovery against a local mail-engine fixture.
