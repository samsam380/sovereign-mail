#!/usr/bin/env python3
"""Read-only checks; does not alter DNS, firewall, packages, or mail services."""
import argparse
import shutil
import socket
import subprocess
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--host',default='mx.example.com')
p.add_argument('--web',default='mail.example.com')
p.add_argument('--expected-ip',help='Static public IPv4 address')
a=p.parse_args()
for host in [a.host,a.web]:
    try:
        addresses=sorted({row[4][0] for row in socket.getaddrinfo(host,None)})
        print(f'{host}: {", ".join(addresses)}')
        if a.expected_ip and a.expected_ip not in addresses: print('  CHECK: expected static public IP was not returned.')
    except OSError: print(f'{host}: DNS lookup failed')
if a.expected_ip:
    try: print('PTR:',socket.gethostbyaddr(a.expected_ip)[0])
    except OSError: print('PTR: missing; ask the IP provider to set it to',a.host)
print('Docker:',shutil.which('docker') or 'not installed')
if Path('/proc/meminfo').exists():
    memory=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    print('Host RAM:',round(int(memory['MemTotal'].split()[0])/1024),'MiB; available:',round(int(memory['MemAvailable'].split()[0])/1024),'MiB')
if shutil.which('ss'):
    subprocess.run(['ss','-ltn'],check=False)
print('This does not prove inbound/outbound port 25, deliverability, certificate validity, or spam protection.')
print('See docs/ACCEPTANCE.md for network and message-level checks.')
