import base64
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

spec=importlib.util.spec_from_file_location('gateway',Path(__file__).parents[1]/'app/server.py')
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

class Engine(BaseHTTPRequestHandler):
    requests=[]
    def log_message(self,*args): pass
    def do_GET(self): self.reply()
    def do_POST(self): self.reply()
    def reply(self):
        data=self.rfile.read(int(self.headers.get('Content-Length',0)))
        Engine.requests.append((self.command,self.path,data,self.headers.get('Authorization')))
        expected='Basic '+base64.b64encode(b'demo@example.com:app-secret').decode()
        accepted={'Basic '+base64.b64encode((email+':app-secret').encode()).decode() for email in ['demo@example.com','alias@example.com','bob@example.com']}
        if self.headers.get('Authorization') not in accepted:
            self.send_response(401);self.end_headers();return
        if self.path=='/jmap/session':
            account='b' if self.headers.get('Authorization')=='Basic '+base64.b64encode(b'bob@example.com:app-secret').decode() else 'a'
            response={'primaryAccounts':{'urn:ietf:params:jmap:mail':account},'accounts':{account:{}},'apiUrl':'https://mx.example.com/jmap/',
                      'uploadUrl':'https://mx.example.com/jmap/upload/{accountId}/',
                      'downloadUrl':'https://mx.example.com/jmap/download/{accountId}/{blobId}/{name}?type={type}'}
        elif self.path.startswith('/jmap/download/'):
            self.send_response(200);self.end_headers();self.wfile.write(b'<script>unsafe attachment</script>');return
        elif self.path.startswith('/jmap/upload/'):
            response={'blobId':'blob1','accountId':'a','size':len(data),'type':'application/octet-stream'}
        else:
            methods=[]
            for method,args,tag in json.loads(data or b'{}').get('methodCalls',[]):
                if method=='Mailbox/get': value={'list':[{'id':r,'role':r,'name':r.title(),'unreadEmails':0} for r in ['inbox','sent','drafts','archive','junk','trash']]}
                elif method=='Identity/get': value={'list':[{'id':'identity1','name':'','email':'demo@example.com'}]}
                elif method=='Email/query': value={'ids':[],'total':0}
                else: value={'list':[]}
                methods.append([method,value,tag])
            response={'methodResponses':methods}
        raw=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ThreadingHTTPServer(('127.0.0.1',0),Engine)
        g.UPSTREAM='http://127.0.0.1:'+str(cls.engine.server_port)
        cls.web=g.Server(('127.0.0.1',0),g.Handler)
        for s in [cls.engine,cls.web]: threading.Thread(target=s.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        for s in [cls.web,cls.engine]: s.shutdown();s.server_close()
    def setUp(self):
        self.security_dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.security_dir.cleanup)
        g.MFA=g.Store(self.security_dir.name,initialize=True)
        g.SESSIONS.clear();g.PENDING.clear();g.ATTEMPTS.clear();Engine.requests.clear()
    def request(self,method,path,body=None,headers=None):
        h={'Origin':g.ORIGIN,**(headers or {})}
        if isinstance(body,(dict,list)):
            body=json.dumps(body);h['Content-Type']='application/json'
        c=http.client.HTTPConnection('127.0.0.1',self.web.server_port,timeout=3)
        c.request(method,path,body,h);r=c.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;c.close()
        return status,headers,data
    def signin(self):
        status,headers,raw=self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})
        self.assertEqual(status,200,raw)
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertNotIn('app-secret',raw.decode());self.assertNotIn('app-secret',headers['Set-Cookie'])
        return {'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.loads(raw)['csrf']}
    def test_login_session_logout_revokes_cookie(self):
        h=self.signin();self.assertEqual(self.request('GET','/api/session',headers=h)[0],200)
        self.assertEqual(self.request('POST','/api/logout',headers=h)[0],200)
        self.assertEqual(self.request('GET','/api/session',headers=h)[0],401)
    def test_cross_origin_login_and_mutation_blocked(self):
        self.assertEqual(self.request('POST','/api/login',{}, {'Origin':'https://evil.example'})[0],403)
        h=self.signin();h['Origin']='https://evil.example'
        self.assertEqual(self.request('POST','/api/logout',headers=h)[0],403)
    def test_missing_csrf_rejected(self):
        h=self.signin();h.pop('X-CSRF-Token')
        self.assertEqual(self.request('POST','/api/logout',headers=h)[0],403)
    def test_mail_method_passes_but_admin_method_does_not(self):
        h=self.signin();payload={'using':['urn:ietf:params:jmap:mail'],'methodCalls':[['Mailbox/get',{'accountId':'a'},'0']]}
        self.assertEqual(self.request('POST','/api/jmap',payload,h)[0],200)
        payload['methodCalls'][0][0]='Account/set'
        self.assertEqual(self.request('POST','/api/jmap',payload,h)[0],400)
    def test_static_allowlist_and_security_headers(self):
        status,h,body=self.request('GET','/')
        self.assertEqual(status,200);self.assertIn(b'Sovereign Mail',body)
        self.assertIn("script-src 'self'",h['Content-Security-Policy']);self.assertEqual(h['X-Frame-Options'],'DENY')
        for target in ['/../server.py','/%2e%2e/server.py','/.env','/server.py']:
            self.assertEqual(self.request('GET',target)[0],404)
    def test_wrong_password_is_not_a_valid_session(self):
        self.assertEqual(self.request('POST','/api/login',{'email':'demo@example.com','password':'wrong'})[0],401)
        self.assertEqual(len(g.SESSIONS),0)
    def test_only_domain_mailbox_and_well_formed_json(self):
        for email in ['x@evil.example','example.com','sam:admin@example.com','@example.com']:
            self.assertEqual(self.request('POST','/api/login',{'email':email,'password':'x'})[0],400)
        self.assertEqual(self.request('POST','/api/login','{broken')[0],400)
    def test_upload_and_download_force_attachment(self):
        h=self.signin()
        status,_,body=self.request('POST','/api/upload?account=a',b'payload',h)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['size'],7)
        status,headers,body=self.request('GET','/api/download?account=a&blob=b&name=evil.html',headers=h)
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/octet-stream')
        self.assertTrue(headers['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(self.request('POST','/api/upload?account=another',b'x',h)[0],403)
    def test_session_expiry(self):
        h=self.signin()
        for value in g.SESSIONS.values(): value['expires']=time.monotonic()-1
        self.assertEqual(self.request('GET','/api/session',headers=h)[0],401)
    def test_rate_limit(self):
        for _ in range(8): self.request('POST','/api/login',{'email':'demo@example.com','password':'wrong'})
        self.assertEqual(self.request('POST','/api/login',{'email':'demo@example.com','password':'wrong'})[0],429)
    def test_oversize_rejected_without_allocating_body(self):
        self.assertEqual(self.request('POST','/api/login',headers={'Content-Length':str(g.MAX_BODY+1)})[0],413)
    def test_no_advertised_host_ssrf(self):
        self.assertEqual(g.endpoint('https://attacker.example/jmap/upload/{accountId}/',accountId='a/b'),'/jmap/upload/a%2Fb/')
        for target in ['http://evil.example/admin','//evil.example/secret','/jmap/{unsupported}']:
            with self.assertRaises(g.Fault):g.endpoint(target)
    def test_secure_cookie_when_https(self):
        old=(g.SECURE,g.COOKIE)
        try:
            g.SECURE=True;g.COOKIE='__Host-sovereign'
            status,h,_=self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})
            self.assertEqual(status,200);self.assertIn('; Secure',h['Set-Cookie']);self.assertIn('__Host-sovereign=',h['Set-Cookie'])
        finally:g.SECURE,g.COOKIE=old

    def enroll(self, headers=None):
        headers=headers or self.signin()
        other=self.signin()
        status,_,raw=self.request('POST','/api/security/setup',{'password':'app-secret'},headers)
        self.assertEqual(status,200,raw)
        setup=json.loads(raw)
        self.assertTrue(setup['uri'].startswith('otpauth://totp/'))
        self.assertEqual(self.request('GET','/api/security',headers=headers)[2],b'{"enabled": false, "recoveryCodesRemaining": 0}')
        status,qr_headers,qr=self.request('GET','/api/security/qr',headers=headers)
        self.assertEqual(status,200,qr)
        self.assertEqual(qr_headers['Content-Type'],'image/svg+xml')
        self.assertIn(b'<svg',qr)
        self.assertEqual(qr_headers['Cache-Control'],'no-store')
        code=g.totp(setup['secret'],int(time.time()//30)) if hasattr(g,'totp') else __import__('mfa').totp(setup['secret'],int(time.time()//30))
        status,h,raw=self.request('POST','/api/security/enable',{'code':code},headers)
        self.assertEqual(status,200,raw)
        data=json.loads(raw)
        new={'Cookie':h['Set-Cookie'].split(';')[0],'X-CSRF-Token':data['csrf']}
        self.assertEqual(self.request('GET','/api/session',headers=other)[0],401)
        self.assertEqual(self.request('GET','/api/session',headers=headers)[0],401)
        return new,setup['secret'],data['recoveryCodes']

    def challenge(self,email='demo@example.com'):
        status,h,raw=self.request('POST','/api/login',{'email':email,'password':'app-secret'})
        self.assertEqual(status,200,raw)
        data=json.loads(raw)
        self.assertTrue(data['requires2fa'])
        self.assertNotIn('jmap',data)
        self.assertNotIn('app-secret',raw.decode())
        return {'Cookie':h['Set-Cookie'].split(';')[0],'X-CSRF-Token':data['csrf']}

    def test_enrollment_requires_password_and_valid_code(self):
        h=self.signin()
        self.assertEqual(self.request('POST','/api/security/setup',{'password':'wrong'},h)[0],401)
        self.assertEqual(self.request('POST','/api/security/enable',{'code':'123456'},h)[0],410)
        status,_,raw=self.request('POST','/api/security/setup',{'password':'app-secret'},h)
        self.assertEqual(status,200,raw)
        self.assertEqual(self.request('POST','/api/security/enable',{'code':'invalid'},h)[0],401)
        self.assertFalse(json.loads(self.request('GET','/api/security',headers=h)[2])['enabled'])

    def test_password_only_and_pending_cookie_cannot_access_mail(self):
        _,_,codes=self.enroll()
        h=self.challenge()
        for path in ['/api/session','/api/security','/api/download?account=a&blob=x']:
            self.assertEqual(self.request('GET',path,headers=h)[0],401)
        self.assertEqual(self.request('POST','/api/jmap',{},h)[0],401)
        self.assertEqual(self.request('POST','/api/upload?account=a',b'x',h)[0],401)
        status,auth_headers,raw=self.request('POST','/api/login/2fa',{'code':codes[0]},h)
        self.assertEqual(status,200,raw)
        self.assertIn('jmap',json.loads(raw))
        full={'Cookie':auth_headers['Set-Cookie'].split(';')[0]}
        self.assertEqual(self.request('GET','/api/session',headers=full)[0],200)
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[1]},h)[0],401)

    def test_alias_login_cannot_bypass_second_factor(self):
        self.enroll()
        self.challenge('alias@example.com')
        status,_,raw=self.request('POST','/api/login',{'email':'bob@example.com','password':'app-secret'})
        self.assertEqual(status,200,raw)
        self.assertNotIn('requires2fa',json.loads(raw))

    def test_challenge_csrf_origin_expiry_and_cancellation(self):
        _,_,codes=self.enroll()
        h=self.challenge()
        missing={k:v for k,v in h.items() if k!='X-CSRF-Token'}
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[0]},missing)[0],403)
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[0]},{**h,'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/login/cancel',{},h)[0],200)
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[0]},h)[0],401)
        h=self.challenge()
        for p in g.PENDING.values():p['expires']=time.monotonic()-1
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[0]},h)[0],401)

    def test_code_lockout_survives_new_challenge(self):
        self.enroll()
        h=self.challenge()
        for _ in range(5):self.assertEqual(self.request('POST','/api/login/2fa',{'code':'invalid'},h)[0],401)
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':'invalid'},h)[0],429)
        self.assertEqual(self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})[0],429)

    def test_mfa_persists_after_process_memory_is_cleared(self):
        self.enroll()
        g.SESSIONS.clear();g.PENDING.clear()
        g.MFA=g.Store(self.security_dir.name)
        self.challenge()

    def test_settings_need_password_code_and_recovery_codes_work_once(self):
        h,_,codes=self.enroll()
        self.assertEqual(self.request('POST','/api/security/disable',{'password':'wrong','code':codes[0]},h)[0],401)
        self.assertEqual(self.request('POST','/api/security/disable',{'password':'app-secret','code':'invalid'},h)[0],401)
        status,new_headers,raw=self.request('POST','/api/security/recovery',{'password':'app-secret','code':codes[0]},h)
        self.assertEqual(status,200,raw)
        data=json.loads(raw)
        h={'Cookie':new_headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':data['csrf']}
        challenge=self.challenge()
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':codes[1]},challenge)[0],401)
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':data['recoveryCodes'][0]},challenge)[0],200)
        challenge=self.challenge()
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':data['recoveryCodes'][0]},challenge)[0],401)
        g.ATTEMPTS.clear()  # Separate settings checks from the independent login throttle test.
        status,_,raw=self.request('POST','/api/security/disable',{'password':'app-secret','code':data['recoveryCodes'][1]},h)
        self.assertEqual(status,200,raw)
        status,_,raw=self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})
        self.assertEqual(status,200,raw)
        self.assertIn('jmap',json.loads(raw))

    def test_authenticator_code_login_and_replay_rejection(self):
        _,secret,_=self.enroll()
        code=__import__('mfa').totp(secret,int(time.time()//30)+1)
        h=self.challenge()
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':code},h)[0],200)
        h=self.challenge()
        self.assertEqual(self.request('POST','/api/login/2fa',{'code':code},h)[0],401)

    def test_absent_security_storage_does_not_allow_password_login(self):
        from unittest.mock import patch
        g.MFA=None
        with tempfile.TemporaryDirectory() as empty, patch.dict('os.environ',{'MFA_STATE_DIR':empty}):
            self.assertEqual(self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})[0],503)
            self.assertFalse(g.SESSIONS)

    def test_security_change_during_login_cannot_issue_new_version_session(self):
        from unittest.mock import patch
        original = g.Handler.new_session
        def changed(handler, values, expected_version, invalidate=False):
            # Simulate another session enabling 2FA after the password-only check.
            secret = __import__('mfa').new_secret()
            code = __import__('mfa').totp(secret, int(time.time()//30))
            g.MFA.enroll(values['principal'], values['email'], secret, code)
            return original(handler, values, expected_version, invalidate)
        with patch.object(g.Handler, 'new_session', changed):
            status,_,_=self.request('POST','/api/login',{'email':'demo@example.com','password':'app-secret'})
        self.assertEqual(status,401)
        self.assertFalse(g.SESSIONS)

if __name__=='__main__':unittest.main()
