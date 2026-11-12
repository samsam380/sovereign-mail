import os
from pathlib import Path
import subprocess
import tempfile
import unittest
try:
    import yaml
except ImportError:
    yaml = None

ROOT=Path(__file__).parents[1]
class AwsLayoutTests(unittest.TestCase):
    @unittest.skipIf(yaml is None, "Optional PyYAML is required for Compose structure validation")
    def test_keeps_haproxy_port_80_and_private_setup(self):
        stack=yaml.safe_load((ROOT/'compose.aws.yaml').read_text())
        self.assertEqual(stack['services']['caddy']['ports'],['443:443'])
        self.assertIn('127.0.0.1:8080:8080',stack['services']['stalwart']['ports'])
        self.assertNotIn('ports',stack['services']['webmail'])
        caddy=(ROOT/'deploy/Caddyfile.https-only').read_text()
        self.assertIn('auto_https disable_redirects',caddy)
        self.assertIn('disable_http_challenge',caddy)
        self.assertNotIn('http://',caddy)
    def check_guard(self,name):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'awk';path.write_text('#!/bin/sh\nprintf "424000\\n"\n');path.chmod(0o700)
            docker=Path(tmp)/'docker';docker.write_text('#!/bin/sh\necho DOCKER_MUST_NOT_RUN\nexit 99\n');docker.chmod(0o700)
            env={**os.environ,'PATH':tmp+':'+os.environ['PATH']}
            env.pop('EXPERIMENTAL_LOW_MEMORY',None)
            result=subprocess.run(['bash',str(ROOT/'scripts'/name)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,1)
            self.assertIn('RAM',result.stderr)
            self.assertNotIn('DOCKER_MUST_NOT_RUN',result.stdout+result.stderr)
    def test_small_host_init_stops_before_docker(self):self.check_guard('aws-init.sh')
    def test_small_host_start_stops_before_docker(self):self.check_guard('aws-start.sh')
