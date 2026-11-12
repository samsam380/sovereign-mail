import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from mfa import Store, InvalidCode, Locked, totp, matching_step


class MfaTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store=Store(self.directory.name,initialize=True)
        self.secret=base64.b32encode(b'12345678901234567890').decode().rstrip('=')
        self.now=1700000010
        self.step=self.now//30

    def enroll(self):
        return self.store.enroll('account-a','demo@example.com',self.secret,totp(self.secret,self.step),now=self.now)

    def test_rfc6238_vectors(self):
        for now,expected in [(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),(1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')]:
            self.assertEqual(totp(self.secret,now//30,digits=8),expected)

    def test_window_and_replay(self):
        codes=self.enroll()
        with self.assertRaises(InvalidCode):self.store.verify('account-a',totp(self.secret,self.step),now=self.now)
        self.store.verify('account-a',totp(self.secret,self.step+1),now=self.now)
        with self.assertRaises(InvalidCode):self.store.verify('account-a',totp(self.secret,self.step+1),now=self.now)
        self.assertIsNone(matching_step(self.secret,totp(self.secret,self.step+5),now=self.now))
        self.assertIsNone(matching_step(self.secret,'１２３４５６',now=self.now))

    def test_encrypted_seed_and_hashed_recovery_persist(self):
        codes=self.enroll()
        raw=self.store.database.read_bytes()
        self.assertNotIn(self.secret.encode(),raw)
        for code in codes:self.assertNotIn(code.encode(),raw)
        self.store=Store(self.directory.name)
        self.assertTrue(self.store.status('account-a')['enabled'])
        self.store.verify('account-a',codes[0].lower(),now=self.now)
        self.assertEqual(self.store.status('account-a')['recoveryCodesRemaining'],9)
        with self.assertRaises(InvalidCode):self.store.verify('account-a',codes[0],now=self.now)

    def test_atomic_totp_and_recovery_consumption(self):
        codes=self.enroll()
        def attempt(code):
            try:self.store.verify('account-a',code,now=self.now);return True
            except InvalidCode:return False
        for code in [totp(self.secret,self.step+1),codes[0]]:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,[code,code]))
            self.assertEqual(results.count(True),1)

    def test_lockout_is_persistent(self):
        codes=self.enroll()
        for _ in range(5):
            with self.assertRaises(InvalidCode):self.store.verify('account-a','bad',now=self.now)
        self.store=Store(self.directory.name)
        with self.assertRaises(Locked):self.store.verify('account-a',codes[0],now=self.now+1)
        self.store.verify('account-a',codes[0],now=self.now+301)

    def test_missing_or_mismatched_state_fails_closed(self):
        self.enroll()
        key=Path(self.directory.name)/'master.key'
        key.write_bytes(b'x'*32)
        with self.assertRaises(RuntimeError):Store(self.directory.name)
        key.unlink()
        with self.assertRaises(RuntimeError):Store(self.directory.name,initialize=True)

    def test_security_version_and_secret_binding(self):
        codes=self.enroll()
        version=self.store.status('account-a')['version']
        self.store.verify('account-a',codes[0],version=version,action='regenerate',now=self.now)
        with self.assertRaises(InvalidCode):self.store.verify('account-a',codes[1],version=version,now=self.now)
        with self.assertRaises(Exception):self.store._decrypt('other-account',self.store._encrypt('account-a',self.secret))


if __name__=='__main__':unittest.main()
