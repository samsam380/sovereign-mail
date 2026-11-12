#!/usr/bin/env bash
# Run after finishing the private setup wizard. No public ports are added here.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo bash scripts/configure-live.sh.' >&2; exit 1; }
[[ -s state/etc/config.json ]] || { echo 'Finish the private setup wizard first.' >&2; exit 1; }
python3 - <<'PY'
import importlib.util,json,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('tuning','scripts/tune-small-host.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=Path('state/etc/config.json');data=json.loads(p.read_text())
if data.get('@type')!='RocksDb':raise SystemExit('Unexpected data store; no configuration changed.')
backup=Path('state/tuning-backups');backup.mkdir(parents=True,exist_ok=True,mode=0o700)
f=backup/('initial-store-'+str(time.time_ns())+'.json');f.write_bytes(p.read_bytes());f.chmod(0o600)
data.update(cacheSize=8*1024**2,bufferSize=8*1024**2,poolWorkers=2)
m.write_config(p,data)
PY
docker compose -f compose.setup.yaml restart stalwart
python3 - <<'PY'
import time,urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
end=time.monotonic()+35
while time.monotonic()<end:
 try:
  with opener.open('http://127.0.0.1:8080/healthz/live',timeout=2) as r:
   if r.status==200:break
 except OSError:pass
 time.sleep(1)
else:raise SystemExit('The engine is not ready. Inspect its logs privately before proceeding.')
PY
exec python3 scripts/tune-small-host.py
