#!/usr/bin/env python3
"""Tune a configured Stalwart v1 instance via its private, loopback JMAP API.
Never reads credentials from arguments or environment and never follows redirects.
"""
import base64
import getpass
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import urllib.error
import urllib.request

MIB=1024**2
LOOKUPS=('accessTokens httpAuth accounts domains roles mailingLists dkimSignatures tenants '
         'domainNames emailAddresses domainNamesNegative emailAddressesNegative directoryRecipients '
         'dnsTxt dnsMx dnsIpv4 dnsIpv6 dnsPtr dnsTlsa dnsMtaSts spamLookup').split()

def plans(cache):
    required={'messages','messagesLarge','groupwareLarge','events','contacts','files','scheduling'}
    if not required <= cache.keys():raise ValueError('Unexpected Cache schema. No settings were changed.')
    values={k:256*1024 for k in LOOKUPS if k in cache}
    values.update(messages=8*MIB,messagesLarge=0,groupwareLarge=0,
                  events=256*1024,contacts=256*1024,files=256*1024,scheduling=256*1024)
    return [('Cache',values),('SystemSettings',{'maxConnections':16,'maxBufferedMemory':16*MIB}),
            ('Http',{'clientIpSource':'xForwardedFor','forwardedHops':1})]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('Unexpected redirect; credentials were not forwarded.')

class Client:
    def __init__(self,user,password):
        self.auth='Basic '+base64.b64encode((user+':'+password).encode()).decode()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def call(self,method,args):
        body=json.dumps({'using':['urn:ietf:params:jmap:core','urn:stalwart:jmap'],
                         'methodCalls':[[method,args,'0']]}).encode()
        req=urllib.request.Request('http://127.0.0.1:8080/jmap/',data=body,
             headers={'Authorization':self.auth,'Content-Type':'application/json'})
        with self.opener.open(req,timeout=30) as response:
            value=json.loads(response.read(2*MIB))
        answer=next((x for x in value.get('methodResponses',[]) if x[2]=='0'),None)
        if not answer:raise RuntimeError('No management response.')
        if answer[0]=='error':raise RuntimeError('Management method rejected: '+answer[1].get('type','unknown'))
        return answer[1]
    def get(self,kind):
        value=self.call('x:'+kind+'/get',{'ids':['singleton']})
        if len(value.get('list',[]))!=1:raise RuntimeError('Expected singleton '+kind)
        return value['list'][0]
    def update(self,kind,fields):
        value=self.call('x:'+kind+'/set',{'update':{'singleton':fields}})
        if 'singleton' not in value.get('updated',{}):
            raise RuntimeError('Update rejected for '+kind+': '+value.get('notUpdated',{}).get('singleton',{}).get('type','unknown'))


def write_config(path,values):
    info=path.stat()
    with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix='.config-',delete=False) as f:
        tmp=Path(f.name)
        json.dump(values,f);f.write('\n');f.flush();os.fsync(f.fileno())
    try:
        os.chmod(tmp,stat.S_IMODE(info.st_mode));os.chown(tmp,info.st_uid,info.st_gid)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def apply(client,root):
    config=root/'state/etc/config.json'
    data=json.loads(config.read_text())
    if data.get('@type')!='RocksDb':raise ValueError('This profile supports the pilot RocksDb store only.')
    plan=plans(client.get('Cache'))
    originals={}
    for kind,fields in plan:
        value=client.get(kind)
        if not fields.keys()<=value.keys():raise ValueError('Unexpected '+kind+' schema; no changes applied.')
        originals[kind]={k:value[k] for k in fields}
    backup=root/'state/tuning-backups'/str(time.time_ns())
    backup.mkdir(parents=True,mode=0o700)
    (backup/'config.json').write_bytes(config.read_bytes());os.chmod(backup/'config.json',0o600)
    (backup/'settings.json').write_text(json.dumps(originals,indent=2));os.chmod(backup/'settings.json',0o600)
    applied=[]
    try:
        for kind,fields in plan:
            client.update(kind,fields);applied.append(kind)
        data.update(cacheSize=8*MIB,bufferSize=8*MIB,poolWorkers=2)
        write_config(config,data)
    except Exception:
        for kind in reversed(applied):
            try:client.update(kind,originals[kind])
            except Exception:print('Rollback needs manual attention for '+kind+'; see the local tuning backup.')
        raise
    return backup

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run with sudo python3 scripts/tune-small-host.py.')
    root=Path(__file__).resolve().parents[1]
    print('Enter the FINAL administrator credentials from the completed wizard, privately.')
    user=input('Administrator email: ').strip()
    password=getpass.getpass('Administrator password or app password: ')
    if not user or ':' in user or not password:raise SystemExit('Credentials are required.')
    try:
        backup=apply(Client(user,password),root)
    except (OSError,ValueError,RuntimeError,urllib.error.URLError) as error:
        raise SystemExit('Tuning did not finish: '+str(error))
    finally:password=''
    (root/'state/pilot-tuned').write_text('Review memory and delivery before MX cutover.\n')
    print('Tuning saved. Restart the engine before public use. Local recovery copy:',backup)
