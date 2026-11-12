#!/usr/bin/env python3
"""Sovereign Mail: same-origin JMAP gateway with persistent authenticator 2FA."""
import base64
import collections
import hmac
import hashlib
import http.cookies
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import threading
import time
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).parent))
from mfa import Store, InvalidCode, Locked, new_secret, provisioning_uri, qr_svg, matching_step

ROOT = Path(__file__).parent / 'static'
ORIGIN = os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8787').rstrip('/')
UPSTREAM = os.getenv('JMAP_ORIGIN', 'http://stalwart:8080').rstrip('/')
DOMAIN = os.getenv('MAIL_DOMAIN', 'example.com')
SECURE = ORIGIN.startswith('https://')
COOKIE = '__Host-sovereign' if SECURE else 'sovereign-dev'
MAX_BODY = 12 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
SESSION_TTL = 8 * 3600
MAX_SESSIONS = 128
ALLOWED = {'Mailbox/get', 'Mailbox/query', 'Email/get', 'Email/query', 'Email/set',
           'Identity/get', 'EmailSubmission/set', 'EmailSubmission/get', 'Quota/get'}
SESSIONS = {}
PENDING = {}
MFA = None
CHALLENGE_TTL = 300
ENROLLMENT_TTL = 600
ATTEMPTS = collections.OrderedDict()
LOCK = threading.Lock()

class Fault(Exception):
    def __init__(self, status, message): self.status, self.message = status, message

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Fault(502, 'The mail engine returned a redirect; check JMAP listener configuration.')

# Never use environment HTTP proxies for mailbox passwords or private mail.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

def upstream(method, path, credential, body=None, content_type='application/json', ip=''):
    if not path.startswith('/') or path.startswith('//') or '\\' in path or '\r' in path or '\n' in path:
        raise Fault(502, 'Invalid mail engine endpoint.')
    headers = {'Authorization': 'Basic ' + credential, 'Content-Type': content_type,
               'Accept': 'application/json'}
    # Stalwart rejects loopback addresses claimed in forwarded headers.
    if ip and not ipaddress.ip_address(ip).is_loopback: headers['X-Forwarded-For'] = ip
    req = urllib.request.Request(UPSTREAM + path, data=body, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=30) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE: raise Fault(413, 'Mail engine response is too large.')
            return data
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403): raise Fault(401, 'Sign-in expired or mail access was denied. Use a mailbox app password.')
        if exc.code == 429: raise Fault(429, 'The mail engine is rate limiting requests. Try later.')
        raise Fault(502, 'The mail engine rejected the request. Check its private administrator log.')
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise Fault(503, 'The mail engine is unavailable or has not completed setup.')

def endpoint(template, **values):
    # Use only paths from the authenticated session. Advertised hosts never become destinations.
    if not isinstance(template, str): raise Fault(502, 'Mail engine endpoint is missing.')
    for key, value in values.items():
        template = template.replace('{' + key + '}', urllib.parse.quote(str(value), safe=''))
    parsed = urllib.parse.urlsplit(template)
    if parsed.fragment or '{' in template or '}' in template:
        raise Fault(502, 'Unsupported mail engine endpoint template.')
    path = parsed.path + ('?' + parsed.query if parsed.query else '')
    if path != '/jmap' and not path.startswith('/jmap/'):
        raise Fault(502, 'Mail engine endpoint must be under /jmap/.')
    return path

def login_limit(ip):
    now = time.monotonic()
    with LOCK:
        # Bounded memory, including when attackers rotate client addresses.
        stale = [k for k, v in ATTEMPTS.items() if not v or now - v[-1] > 300]
        for k in stale: ATTEMPTS.pop(k, None)
        values = ATTEMPTS.setdefault(ip, collections.deque())
        while values and now - values[0] > 300: values.popleft()
        if len(values) >= 8: raise Fault(429, 'Too many sign-in attempts. Wait five minutes.')
        values.append(now)
        ATTEMPTS.move_to_end(ip)
        while len(ATTEMPTS) > 4096: ATTEMPTS.popitem(last=False)

def validate_calls(data):
    if not isinstance(data, dict): raise Fault(400, 'Expected a JMAP object.')
    calls = data.get('methodCalls')
    if not isinstance(calls, list) or not 1 <= len(calls) <= 16:
        raise Fault(400, 'Supply between 1 and 16 mail methods.')
    for call in calls:
        if not isinstance(call, list) or len(call) != 3 or not isinstance(call[0], str) or call[0] not in ALLOWED:
            raise Fault(400, 'This gateway only allows supported mailbox methods.')
        if not isinstance(call[1], dict) or not isinstance(call[2], str):
            raise Fault(400, 'Invalid mail method arguments.')

def security_store():
    global MFA
    if MFA is None:
        try: MFA = Store(os.getenv('MFA_STATE_DIR', '/var/lib/sovereign-mail'))
        except Exception: raise Fault(503, 'Webmail security storage is unavailable. Contact the server administrator.')
    return MFA

def principal_for(data):
    account = data.get('primaryAccounts', {}).get('urn:ietf:params:jmap:mail')
    if not account: raise Fault(403, 'This account has no JMAP mailbox.')
    # All aliases of the same mailbox share MFA; an alternate address cannot bypass it.
    return hashlib.sha256((DOMAIN.lower() + '\0' + str(account)).encode()).hexdigest()

def mfa_error(error):
    if isinstance(error, Locked): return Fault(429, 'Too many incorrect codes. Wait five minutes and try again.')
    return Fault(401, 'Invalid or already used code. Use a fresh authenticator code or an unused recovery code.')

class Handler(BaseHTTPRequestHandler):
    server_version = 'SovereignMail'
    def setup(self):
        super().setup()
        self.connection.settimeout(35)
    def log_message(self, fmt, *args):
        # No query strings, message contents, usernames, passwords, or cookies in logs.
        print('%s %s' % (self.command, urllib.parse.urlsplit(self.path).path), flush=True)
    def respond(self, status, payload, kind='application/json', cookie=None, extra=None):
        if not isinstance(payload, bytes): payload = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if SECURE: self.send_header('Strict-Transport-Security', 'max-age=31536000')
        if cookie:
            for value in ([cookie] if isinstance(cookie, str) else cookie): self.send_header('Set-Cookie', value)
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)
    def ip(self):
        # Production binds to loopback or a private Docker network and ONLY Caddy reaches it.
        if os.getenv('TRUST_PROXY', '0') == '1':
            return self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[-1].strip()[:80]
        return self.client_address[0]
    def check_origin(self):
        if self.headers.get('Origin') != ORIGIN:
            raise Fault(403, 'Request origin does not match this installation.')
    def body(self, json_body=True):
        if self.headers.get('Transfer-Encoding'): raise Fault(400, 'Chunked uploads are not supported.')
        try: length = int(self.headers.get('Content-Length', '0'))
        except ValueError: raise Fault(400, 'Invalid request length.')
        limit = 1024 * 1024 if json_body else MAX_BODY
        if length < 0 or length > limit: raise Fault(413, 'Request exceeds the 1 MiB JSON / 12 MiB upload limit.')
        body = self.rfile.read(length)
        if len(body) != length: raise Fault(400, 'Incomplete request body.')
        if not json_body: return body
        try: return json.loads(body)
        except (ValueError, UnicodeError): raise Fault(400, 'Invalid JSON request.')
    def session(self, csrf=False):
        cookies = http.cookies.SimpleCookie()
        try: cookies.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: raise Fault(401, 'Please sign in.')
        token = cookies.get(COOKIE)
        sid = token.value if token else ''
        with LOCK:
            session = SESSIONS.get(sid)
            if not session or session['expires'] <= time.monotonic():
                SESSIONS.pop(sid, None)
                raise Fault(401, 'Please sign in.')
        status = security_store().status(session['principal'])
        if session['version'] != status['version']:
            with LOCK: SESSIONS.pop(sid, None)
            raise Fault(401, 'Security settings changed. Please sign in again.')
        if csrf:
            self.check_origin()
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session['csrf']):
                raise Fault(403, 'Invalid request token. Reload the page.')
        return sid, session
    def cookie(self, value, challenge=False, clear=False):
        name = COOKIE + '-challenge' if challenge else COOKIE
        ttl = 0 if clear else CHALLENGE_TTL if challenge else SESSION_TTL
        return f'{name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={ttl}' + ('; Secure' if SECURE else '')
    def authenticate_mailbox(self, email, password):
        if not isinstance(email, str) or not isinstance(password, str) or not password or len(password) > 1024 or len(email) > 254 or ':' in email or email.count('@') != 1 or not email.split('@')[0] or any(c.isspace() for c in email):
            raise Fault(400, 'Enter a valid email and mailbox password.')
        email = email.strip()
        if email.rsplit('@', 1)[-1].lower() != DOMAIN.lower(): raise Fault(400, 'Use an address on ' + DOMAIN + '.')
        credential = base64.b64encode((email + ':' + password).encode()).decode()
        raw = upstream('GET', '/jmap/session', credential, ip=self.ip())
        try: data = json.loads(raw)
        except ValueError: raise Fault(502, 'Mail engine returned an invalid session.')
        principal = principal_for(data)
        endpoint(data.get('apiUrl'))
        return {'credential': credential, 'jmap': data, 'email': email, 'principal': principal}
    def new_session(self, values, expected_version, invalidate=False):
        status = security_store().status(values['principal'])
        if status['version'] != expected_version:
            raise Fault(401, 'Security settings changed. Please sign in again.')
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session = {key: values[key] for key in ('credential', 'jmap', 'email', 'principal')}
        session.update(expires=time.monotonic() + SESSION_TTL, csrf=csrf, version=status['version'])
        with LOCK:
            for collection in (SESSIONS, PENDING):
                for key in [k for k, v in collection.items() if v['expires'] <= time.monotonic() or (invalidate and v['principal'] == values['principal'])]:
                    collection.pop(key, None)
            if len(SESSIONS) >= MAX_SESSIONS: raise Fault(503, 'Session capacity reached. Try later.')
            SESSIONS[sid] = session
        return session, self.cookie(sid)
    def public_session(self, session):
        return {key: session[key] for key in ('email', 'csrf', 'jmap')}
    def reauthenticate(self, session, value):
        login_limit(self.ip())
        verified = self.authenticate_mailbox(session['email'], value.get('password'))
        if verified['principal'] != session['principal']: raise Fault(403, 'Mailbox identity changed. Please sign in again.')
    def pending(self):
        self.check_origin()
        cookies = http.cookies.SimpleCookie()
        try: cookies.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: raise Fault(401, 'Sign in again to request a new code challenge.')
        token = cookies.get(COOKIE + '-challenge')
        sid = token.value if token else ''
        with LOCK:
            pending = PENDING.get(sid)
            if not pending or pending['expires'] <= time.monotonic():
                PENDING.pop(sid, None)
                raise Fault(401, 'Code challenge expired. Start sign-in again.')
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), pending['csrf']): raise Fault(403, 'Invalid request token.')
            if pending.get('busy'): raise Fault(429, 'A code check is already in progress.')
            pending['busy'] = True
        return sid, pending
    def do_GET(self): self.dispatch('GET')
    def do_POST(self): self.dispatch('POST')
    def dispatch(self, method):
        try: self.route(method)
        except Fault as exc:
            self.close_connection = True
            self.respond(exc.status, {'error': exc.message})
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception:
            self.close_connection = True
            self.respond(500, {'error': 'The request could not be completed.'})
    def route(self, method):
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        if method == 'GET' and path == '/healthz':
            return self.respond(200, {'status':'ok', 'service':'webmail', 'mailEngine':'not-probed'})
        if method == 'GET' and path == '/api/config':
            return self.respond(200, {'domain': DOMAIN, 'demo': os.getenv('DEMO_MODE') == '1'})
        if method == 'POST' and path == '/api/login':
            self.check_origin()
            login_limit(self.ip())
            value = self.body()
            if not isinstance(value, dict): raise Fault(400, 'Expected email and password.')
            values = self.authenticate_mailbox(value.get('email'), value.get('password'))
            status = security_store().status(values['principal'])
            if status['enabled']:
                try: security_store().assert_unlocked(values['principal'])
                except Locked as error: raise mfa_error(error)
                sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with LOCK:
                    for key in [k for k, v in PENDING.items() if v['expires'] <= time.monotonic()]: PENDING.pop(key, None)
                    if len(PENDING) >= MAX_SESSIONS: raise Fault(503, 'Sign-in capacity reached. Try later.')
                    PENDING[sid] = {**values, 'csrf': csrf, 'expires': time.monotonic() + CHALLENGE_TTL, 'version': status['version']}
                return self.respond(200, {'requires2fa': True, 'csrf': csrf, 'email': values['email']},
                                    cookie=self.cookie(sid, challenge=True))
            session, cookie = self.new_session(values, status['version'])
            return self.respond(200, self.public_session(session), cookie=cookie)
        if method == 'POST' and path == '/api/login/2fa':
            value = self.body()
            if not isinstance(value, dict): raise Fault(400, 'Enter an authenticator or recovery code.')
            sid, pending = self.pending()
            try:
                security_store().verify(pending['principal'], value.get('code'), version=pending['version'])
                with LOCK: PENDING.pop(sid, None)
                session, cookie = self.new_session(pending, pending['version'])
                return self.respond(200, self.public_session(session), cookie=[self.cookie('', challenge=True, clear=True), cookie])
            except (InvalidCode, Locked) as error: raise mfa_error(error)
            finally:
                with LOCK:
                    if sid in PENDING: PENDING[sid]['busy'] = False
        if method == 'POST' and path == '/api/login/cancel':
            sid, _ = self.pending()
            with LOCK: PENDING.pop(sid, None)
            return self.respond(200, {'ok': True}, cookie=self.cookie('', challenge=True, clear=True))
        if method == 'GET' and path == '/api/session':
            _, session = self.session()
            return self.respond(200, self.public_session(session))
        if method == 'GET' and path == '/api/security':
            _, session = self.session()
            status = security_store().status(session['principal'])
            return self.respond(200, {'enabled': status['enabled'], 'recoveryCodesRemaining': status['recoveryCodesRemaining']})
        if method == 'POST' and path == '/api/security/setup':
            _, session = self.session(csrf=True)
            value = self.body()
            if not isinstance(value, dict): raise Fault(400, 'Enter your mailbox password.')
            if security_store().status(session['principal'])['enabled']: raise Fault(409, 'Two-factor authentication is already enabled.')
            self.reauthenticate(session, value)
            secret = new_secret()
            with LOCK: session['enrollment'] = {'secret': secret, 'expires': time.monotonic() + ENROLLMENT_TTL, 'failures': 0}
            return self.respond(200, {'secret': secret, 'uri': provisioning_uri(secret, session['email']), 'expiresIn': ENROLLMENT_TTL})
        if method == 'GET' and path == '/api/security/qr':
            _, session = self.session()
            enrollment = session.get('enrollment')
            if not enrollment or enrollment['expires'] <= time.monotonic(): raise Fault(410, 'Setup expired. Start again.')
            return self.respond(200, qr_svg(enrollment['secret'], session['email']), 'image/svg+xml')
        if method == 'POST' and path == '/api/security/enable':
            _, session = self.session(csrf=True)
            value = self.body()
            if not isinstance(value, dict): raise Fault(400, 'Enter your six-digit authenticator code.')
            with LOCK:
                enrollment = session.get('enrollment')
                if not enrollment or enrollment['expires'] <= time.monotonic(): raise Fault(410, 'Setup expired. Start again.')
                enrollment['failures'] += 1
                if enrollment['failures'] > 5:
                    session.pop('enrollment', None)
                    raise Fault(429, 'Too many incorrect codes. Start setup again.')
            try: codes = security_store().enroll(session['principal'], session['email'], enrollment['secret'], value.get('code'))
            except InvalidCode as error: raise mfa_error(error)
            replacement, cookie = self.new_session(session, session['version'] + 1, invalidate=True)
            return self.respond(200, {**self.public_session(replacement), 'recoveryCodes': codes}, cookie=cookie)
        if method == 'POST' and path in ('/api/security/disable', '/api/security/recovery'):
            _, session = self.session(csrf=True)
            value = self.body()
            if not isinstance(value, dict): raise Fault(400, 'Enter your mailbox password and code.')
            self.reauthenticate(session, value)
            try:
                codes = security_store().verify(session['principal'], value.get('code'), version=session['version'],
                                                action='disable' if path.endswith('disable') else 'regenerate')
            except (InvalidCode, Locked) as error: raise mfa_error(error)
            replacement, cookie = self.new_session(session, session['version'] + 1, invalidate=True)
            return self.respond(200, {**self.public_session(replacement), 'recoveryCodes': codes or []}, cookie=cookie)
        if method == 'POST' and path == '/api/logout':
            sid, _ = self.session(csrf=True)
            with LOCK: SESSIONS.pop(sid, None)
            return self.respond(200, {'ok': True}, cookie=f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0' + ('; Secure' if SECURE else ''))
        if method == 'POST' and path == '/api/jmap':
            _, session = self.session(csrf=True)
            value = self.body()
            validate_calls(value)
            payload = upstream('POST', endpoint(session['jmap']['apiUrl']), session['credential'],
                               json.dumps(value).encode(), ip=self.ip())
            return self.respond(200, payload)
        if method == 'POST' and path == '/api/upload':
            _, session = self.session(csrf=True)
            query = urllib.parse.parse_qs(url.query)
            account = query.get('account', [''])[0]
            if account not in session['jmap'].get('accounts', {}): raise Fault(403, 'Unknown mail account.')
            upload_path = endpoint(session['jmap'].get('uploadUrl'), accountId=account)
            payload = upstream('POST', upload_path, session['credential'], self.body(False),
                               'application/octet-stream', ip=self.ip())
            return self.respond(200, payload)
        if method == 'GET' and path == '/api/download':
            _, session = self.session()
            query = urllib.parse.parse_qs(url.query)
            def arg(key): return query.get(key, [''])[0]
            if arg('account') not in session['jmap'].get('accounts', {}): raise Fault(403, 'Unknown mail account.')
            target = endpoint(session['jmap'].get('downloadUrl'), accountId=arg('account'),
                              blobId=arg('blob'), name=arg('name') or 'attachment', type='application/octet-stream')
            payload = upstream('GET', target, session['credential'], ip=self.ip())
            name = urllib.parse.quote(arg('name')[:200] or 'attachment', safe='')
            return self.respond(200, payload, 'application/octet-stream', extra={
                'Content-Disposition': "attachment; filename=attachment; filename*=UTF-8''" + name})
        if method == 'GET':
            # Exact static allowlist: no traversal, no source files, no secrets.
            allowed = {'/': 'index.html', '/index.html':'index.html', '/app.js':'app.js',
                       '/app.css':'app.css', '/mark.svg':'mark.svg'}
            if path in allowed:
                file = ROOT / allowed[path]
                return self.respond(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'text/plain')
        raise Fault(404, 'Not found.')

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    # Bound workers before starting threads, including slow client connections.
    workers = threading.BoundedSemaphore(max(1, min(4, int(os.getenv('MAX_WORKERS', '4')))))
    def process_request(self, request, address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, address)
        except Exception:
            self.workers.release()
            raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.workers.release()

if __name__ == '__main__':
    host = os.getenv('BIND', '127.0.0.1')
    port = int(os.getenv('PORT', '8787'))
    if not SECURE and os.getenv('ALLOW_HTTP', '0') != '1':
        raise SystemExit('Set HTTPS PUBLIC_ORIGIN for deployment, or ALLOW_HTTP=1 for a loopback-only local preview.')
    if not SECURE and host not in ('127.0.0.1', '::1'):
        raise SystemExit('Plain HTTP previews must bind to loopback.')
    if os.getenv('DEMO_MODE') != '1': security_store()
    print(f'Sovereign Mail listening on {host}:{port}', flush=True)
    Server((host, port), Handler).serve_forever()
