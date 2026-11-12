"""Persistent webmail TOTP credentials. No mailbox passwords are stored here."""
import argparse
import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import time
import urllib.parse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PERIOD = 30
FAIL_LIMIT = 5
LOCK_SECONDS = 300


class InvalidCode(Exception):
    pass


class Locked(Exception):
    pass


def totp(secret, step, digits=6):
    """RFC 4226 dynamic truncation / RFC 6238 SHA-1 (Google Authenticator)."""
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return str(number % (10 ** digits)).zfill(digits)


def matching_step(secret, code, now=None, last=-1):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        return None
    current = int((time.time() if now is None else now) // PERIOD)
    matches = [step for step in (current - 1, current, current + 1)
               if step > last and step >= 0 and hmac.compare_digest(totp(secret, step), code)]
    return max(matches) if matches else None


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def provisioning_uri(secret, email):
    issuer = 'Sovereign Mail'
    return 'otpauth://totp/' + urllib.parse.quote(issuer + ':' + email, safe='') + '?' + urllib.parse.urlencode({
        'secret': secret, 'issuer': issuer, 'algorithm': 'SHA1', 'digits': 6, 'period': PERIOD,
    })


def qr_svg(secret, email):
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(provisioning_uri(secret, email), image_factory=qrcode.image.svg.SvgPathImage,
                        border=4, box_size=8)
    output = io.BytesIO()
    image.save(output)
    return output.getvalue()


class Store:
    def __init__(self, directory, initialize=False):
        self.directory = Path(directory)
        key_path = self.directory / 'master.key'
        self.database = self.directory / 'security.sqlite3'
        if initialize:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Never silently replace either half of an existing security store.
            if key_path.exists() != self.database.exists():
                raise RuntimeError('Incomplete security store. Restore its database and master.key together.')
            if not key_path.exists():
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    output.write(secrets.token_bytes(32))
                    output.flush()
                    os.fsync(output.fileno())
                fd = os.open(self.database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
        if not key_path.is_file() or not self.database.is_file():
            raise RuntimeError('Security store missing. Run the webmail 2FA installer; restore existing state if lost.')
        if key_path.is_symlink() or self.database.is_symlink():
            raise RuntimeError('Security-store files must not be symbolic links.')
        self.key = key_path.read_bytes()
        if len(self.key) != 32:
            raise RuntimeError('Invalid security-store key.')
        self.cipher = AESGCM(self.key)
        with self.connection() as db:
            if initialize:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS accounts (
                        principal TEXT PRIMARY KEY, email TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                        secret BLOB, last_step INTEGER NOT NULL DEFAULT -1, version INTEGER NOT NULL DEFAULT 0,
                        failures INTEGER NOT NULL DEFAULT 0, window_start INTEGER NOT NULL DEFAULT 0,
                        locked_until INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE IF NOT EXISTS recovery (
                        principal TEXT NOT NULL, digest TEXT NOT NULL,
                        PRIMARY KEY (principal, digest));
                ''')
                db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)',
                           ('key_id', hashlib.sha256(self.key).hexdigest()))
            key_id = db.execute('SELECT value FROM metadata WHERE name=?', ('key_id',)).fetchone()
            if not key_id or not hmac.compare_digest(key_id[0], hashlib.sha256(self.key).hexdigest()):
                raise RuntimeError('Security database and encryption key do not match.')

    @contextlib.contextmanager
    def connection(self, write=False):
        # mode=rw prevents a missing database becoming a fresh, unprotected store.
        db = sqlite3.connect(self.database.resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self, principal):
        with self.connection() as db:
            row = db.execute('SELECT * FROM accounts WHERE principal=?', (principal,)).fetchone()
            count = db.execute('SELECT COUNT(*) FROM recovery WHERE principal=?', (principal,)).fetchone()[0]
        return {'enabled': bool(row and row['enabled']), 'version': row['version'] if row else 0,
                'recoveryCodesRemaining': count}

    def assert_unlocked(self, principal, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as db:
            row = db.execute('SELECT locked_until FROM accounts WHERE principal=?', (principal,)).fetchone()
        if row and row[0] > now:
            raise Locked()

    def _encrypt(self, principal, secret):
        nonce = secrets.token_bytes(12)
        return nonce + self.cipher.encrypt(nonce, secret.encode(), principal.encode())

    def _decrypt(self, principal, value):
        return self.cipher.decrypt(value[:12], value[12:], principal.encode()).decode()

    def _digest(self, principal, code):
        normalized = code.replace('-', '').replace(' ', '').upper()
        return hmac.new(self.key, (principal + ':recovery:' + normalized).encode(), hashlib.sha256).hexdigest()

    def _recovery(self, db, principal):
        codes = ['-'.join([value[i:i + 8] for i in range(0, 32, 8)])
                 for value in [secrets.token_hex(16).upper() for _ in range(10)]]
        db.execute('DELETE FROM recovery WHERE principal=?', (principal,))
        db.executemany('INSERT INTO recovery VALUES (?,?)', [(principal, self._digest(principal, c)) for c in codes])
        return codes

    def enroll(self, principal, email, secret, code, now=None):
        step = matching_step(secret, code, now)
        if step is None:
            raise InvalidCode()
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM accounts WHERE principal=?', (principal,)).fetchone()
            if row and row['enabled']:
                raise InvalidCode()
            version = (row['version'] if row else 0) + 1
            db.execute('''INSERT INTO accounts (principal,email,enabled,secret,last_step,version)
                          VALUES (?,?,1,?,?,?) ON CONFLICT(principal) DO UPDATE SET
                          email=excluded.email,enabled=1,secret=excluded.secret,last_step=excluded.last_step,
                          version=excluded.version,failures=0,window_start=0,locked_until=0''',
                       (principal, email, self._encrypt(principal, secret), step, version))
            codes = self._recovery(db, principal)
        return codes

    def verify(self, principal, code, version=None, action=None, now=None):
        now = int(time.time() if now is None else now)
        valid = False
        result = None
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM accounts WHERE principal=?', (principal,)).fetchone()
            if not row or not row['enabled'] or (version is not None and row['version'] != version):
                raise InvalidCode()
            if row['locked_until'] > now:
                raise Locked()
            if isinstance(code, str) and len(code) <= 80:
                step = matching_step(self._decrypt(principal, row['secret']), code, now, row['last_step'])
                if step is not None:
                    db.execute('UPDATE accounts SET last_step=? WHERE principal=?', (step, principal))
                    valid = True
                elif re.fullmatch(r'[A-Fa-f0-9 -]{32,80}', code):
                    deleted = db.execute('DELETE FROM recovery WHERE principal=? AND digest=?',
                                         (principal, self._digest(principal, code)))
                    valid = deleted.rowcount == 1
            if valid:
                db.execute('UPDATE accounts SET failures=0,window_start=0,locked_until=0 WHERE principal=?', (principal,))
                if action == 'disable':
                    db.execute('UPDATE accounts SET enabled=0,secret=NULL,last_step=-1,version=version+1 WHERE principal=?', (principal,))
                    db.execute('DELETE FROM recovery WHERE principal=?', (principal,))
                elif action == 'regenerate':
                    result = self._recovery(db, principal)
                    db.execute('UPDATE accounts SET version=version+1 WHERE principal=?', (principal,))
            else:
                failures = (row['failures'] if now - row['window_start'] < LOCK_SECONDS else 0) + 1
                window = row['window_start'] if now - row['window_start'] < LOCK_SECONDS else now
                db.execute('UPDATE accounts SET failures=?,window_start=?,locked_until=? WHERE principal=?',
                           (failures, window, now + LOCK_SECONDS if failures >= FAIL_LIMIT else 0, principal))
        # Invalid attempts must commit their counter before the error is raised.
        if not valid:
            raise InvalidCode()
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--init', metavar='DIRECTORY', required=True)
    args = parser.parse_args()
    Store(args.init, initialize=True)
    print('Webmail security store initialized and verified.')
