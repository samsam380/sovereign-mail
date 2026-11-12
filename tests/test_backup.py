"""Exercise backup failure/restart paths without touching Docker or a repository."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).parents[1]
class BackupTests(unittest.TestCase):
    def exercise(self,fail_backup=False,fail_probe=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'scripts').mkdir();(root/'state/etc').mkdir(parents=True)
            (root/'state/etc/config.json').write_text('{}')
            shutil.copy(SOURCE/'scripts/backup.sh',root/'scripts/backup.sh')
            bin_dir=root/'bin';bin_dir.mkdir()
            for name,script in {
                'docker':'''#!/bin/bash
printf '%s\\n' "$*" >> "$EVENTS"
if [[ "$*" == "compose ps --services --status running" ]]; then printf 'stalwart\\nwebmail\\ncaddy\\n'; fi
''',
                'restic':'''#!/bin/bash
printf 'restic %s\\n' "$*" >> "$EVENTS"
if [[ "$1" == snapshots && "$FAIL_PROBE" == 1 ]]; then exit 3; fi
if [[ "$1" == backup && "$FAIL_BACKUP" == 1 ]]; then exit 3; fi
''',
                'flock':'''#!/bin/bash
exit 0
'''
            }.items():
                path=bin_dir/name;path.write_text(script);path.chmod(0o700)
            cfg=root/'backup.env';cfg.write_text('RESTIC_REPOSITORY=sftp:example:/backup\nRESTIC_PASSWORD_FILE=/unused\n')
            # Test uses a local lock path instead of the real system lock.
            script=root/'scripts/backup.sh'
            script.write_text(script.read_text().replace('/var/lock/sovereign-mail-backup.lock',str(root/'lock')))
            env={**os.environ,'PATH':str(bin_dir)+':'+os.environ['PATH'],'BACKUP_ENV_FILE':str(cfg),'EVENTS':str(root/'events'),'FAIL_BACKUP':str(int(fail_backup)),'FAIL_PROBE':str(int(fail_probe))}
            result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
            events=(root/'events').read_text()
            return result.returncode,events
    def test_success_restarts_original_services(self):
        code,events=self.exercise()
        self.assertEqual(code,0,events)
        self.assertIn('compose stop --timeout 90 stalwart webmail caddy',events)
        self.assertIn('compose start stalwart webmail caddy',events)
    def test_failed_backup_still_restarts_and_reports_failure(self):
        code,events=self.exercise(fail_backup=True)
        self.assertNotEqual(code,0)
        self.assertIn('compose start stalwart webmail caddy',events)
    def test_unreachable_repository_does_not_stop_services(self):
        code,events=self.exercise(fail_probe=True)
        self.assertNotEqual(code,0)
        self.assertNotIn('compose stop',events)
