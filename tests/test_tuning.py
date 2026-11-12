import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('tuning',ROOT/'scripts/tune-small-host.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
class Fake:
    def __init__(self,fail=None):
        self.fail=fail;self.calls=[]
        self.values={'Cache':dict(messages=999999,messagesLarge=1000,groupwareLarge=1000,
                                 events=2000,contacts=2000,files=2000,scheduling=2000,httpAuth=5000),
                     'SystemSettings':dict(maxConnections=8192,maxBufferedMemory=None),
                     'Http':dict(clientIpSource='peer',forwardedHops=1)}
    def get(self,kind):return self.values[kind].copy()
    def update(self,kind,fields):
        self.calls.append((kind,fields.copy()))
        if kind==self.fail:raise RuntimeError('simulated rejected update')
        self.values[kind].update(fields)
class TuningTests(unittest.TestCase):
    def root(self,directory):
        p=Path(directory);(p/'state/etc').mkdir(parents=True)
        (p/'state/etc/config.json').write_text(json.dumps({'@type':'RocksDb','path':'/var/lib/stalwart/'}))
        return p
    def test_applies_bounded_settings_and_preserves_data_path_with_recovery_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);client=Fake();backup=t.apply(client,root)
            data=json.loads((root/'state/etc/config.json').read_text())
            self.assertEqual(data['path'],'/var/lib/stalwart/')
            self.assertEqual(data['cacheSize'],8*t.MIB)
            self.assertEqual(data['bufferSize'],8*t.MIB)
            self.assertEqual(client.values['Cache']['messagesLarge'],0)
            self.assertEqual(client.values['Http']['clientIpSource'],'xForwardedFor')
            self.assertEqual(json.loads((backup/'config.json').read_text()),{'@type':'RocksDb','path':'/var/lib/stalwart/'})
    def test_partial_failure_rolls_back_prior_api_updates_and_leaves_local_store_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);client=Fake(fail='SystemSettings');initial=client.values['Cache'].copy()
            with self.assertRaises(RuntimeError):t.apply(client,root)
            self.assertEqual(client.values['Cache'],initial)
            self.assertNotIn('cacheSize',json.loads((root/'state/etc/config.json').read_text()))
            self.assertEqual([kind for kind,_ in client.calls],['Cache','SystemSettings','Cache'])
    def test_incompatible_store_refused_before_any_api_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);p=root/'state/etc/config.json';p.write_text('{"@type":"Postgres"}');client=Fake()
            with self.assertRaises(ValueError):t.apply(client,root)
            self.assertEqual(client.calls,[])
    def test_unknown_cache_schema_refused(self):
        with self.assertRaises(ValueError):t.plans({'messages':1})
try:import yaml
except ImportError:yaml=None
@unittest.skipIf(yaml is None,'Optional PyYAML is required for deployment structure checks')
class SetupIsolationTests(unittest.TestCase):
    def test_private_setup_never_publishes_public_smtp_or_https(self):
        s=yaml.safe_load((ROOT/'compose.setup.yaml').read_text())
        self.assertEqual(set(s['services']),{'stalwart'})
        self.assertEqual(s['services']['stalwart']['ports'],['127.0.0.1:8080:8080'])
    def test_pilot_has_no_demo_mode_and_preserves_port_80(self):
        s=yaml.safe_load((ROOT/'compose.pilot.yaml').read_text())
        self.assertEqual(s['services']['caddy']['ports'],['443:443'])
        self.assertNotIn('DEMO_MODE',s['services']['webmail']['environment'])
        self.assertEqual(s['services']['stalwart']['mem_limit'],'256m')
        self.assertEqual(s['services']['stalwart']['memswap_limit'],'768m')
