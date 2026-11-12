/* DOM integration against the real gateway and a controlled JMAP fixture.
   npm install --prefix /tmp/sovereign-ui-test jsdom@26.1.0
   NODE_PATH=/tmp/sovereign-ui-test/node_modules node --test tests/mfa-ui.test.cjs
*/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {createHmac} = require('node:crypto');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
function otp(secret, step) {
  let bits='';
  for(const ch of secret) bits+='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(ch).toString(2).padStart(5,'0');
  const bytes=Buffer.from((bits.match(/.{8}/g)||[]).map(x=>parseInt(x,2)));
  const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(step));
  const hash=createHmac('sha1',bytes).update(counter).digest();const offset=hash[19]&15;
  return String((hash.readUInt32BE(offset)&0x7fffffff)%1000000).padStart(6,'0');
}
async function until(fn) {
  const deadline=Date.now()+5000;
  while(Date.now()<deadline){if(fn())return;await new Promise(r=>setTimeout(r,10));}
  assert.ok(fn(),'UI did not reach expected state');
}
test('enrollment, challenge, recovery and security actions use real gateway',async t=>{
  const fixture=spawn('python3',['-u','-c',`
import json,sys,tempfile,threading
sys.path.insert(0,'tests')
from test_gateway import g,Engine,ThreadingHTTPServer
with tempfile.TemporaryDirectory() as state:
    g.MFA=g.Store(state,initialize=True)
    engine=ThreadingHTTPServer(('127.0.0.1',0),Engine)
    g.UPSTREAM='http://127.0.0.1:'+str(engine.server_port)
    web=g.Server(('127.0.0.1',0),g.Handler)
    g.ORIGIN='http://127.0.0.1:'+str(web.server_port)
    g.SECURE=False;g.COOKIE='sovereign-dev'
    for server in (engine,web):threading.Thread(target=server.serve_forever,daemon=True).start()
    print(g.ORIGIN,flush=True)
    sys.stdin.read()
    for server in (web,engine):server.shutdown();server.server_close()
`],{cwd:root,env:process.env,stdio:['pipe','pipe','pipe']});
  t.after(()=>fixture.stdin.end());
  let output='',errors='';fixture.stderr.on('data',chunk=>errors+=chunk);
  const base=await new Promise((resolve,reject)=>{
    fixture.stdout.on('data',chunk=>{output+=chunk;if(output.includes('\n'))resolve(output.split('\n')[0]);});
    fixture.on('exit',code=>{if(code)reject(Error(errors));});
  });
  const dom=new JSDOM(fs.readFileSync(path.join(root,'app/static/index.html'),'utf8'),{url:base,runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window,$=id=>w.document.getElementById(id);
  const cookies=new Map();
  w.fetch=async (target,options={})=>{
    const response=await fetch(new URL(target,base),{...options,headers:{Origin:base,...options.headers,Cookie:[...cookies].map(([k,v])=>k+'='+v).join('; ')}});
    for(const value of response.headers.getSetCookie()) {const first=value.split(';')[0],i=first.indexOf('=');cookies.set(first.slice(0,i),first.slice(i+1));}
    return response;
  };
  w.structuredClone=structuredClone;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){if(this.open){this.open=false;this.dispatchEvent(new w.Event('close'));}};
  w.eval(fs.readFileSync(path.join(root,'app/static/app.js'),'utf8').replace(/\bexport /g,''));
  const submit=async id=>{
    const form=$(id),button=form.querySelector('button[type="submit"]');
    await form.onsubmit({preventDefault(){},submitter:button});
  };
  await until(()=>$('loginForm').onsubmit);
  await until(()=>$('login').classList.contains('hidden')===false);
  const login=async()=>{$('email').value='demo@example.com';$('password').value='app-secret';await submit('loginForm');};
  await login();assert.ok(!$('shell').classList.contains('hidden'),$('loginError').textContent);
  await $('settingsButton').onclick();assert.equal($('mfaBadge').textContent,'Not enabled');
  $('mfaSetup').click();$('securityPassword').value='app-secret';await submit('securityPasswordForm');
  assert.ok(!$('mfaEnrollment').classList.contains('hidden'),$('securityError').textContent);
  const secret=$('manualKey').value;assert.match(secret,/^[A-Z2-7]{32}$/);
  const qr=await w.fetch($('mfaQr').getAttribute('src'));assert.equal(qr.status,200);assert.match(await qr.text(),/<svg/);
  $('setupCode').value=otp(secret,Math.floor(Date.now()/30000));await submit('mfaConfirmForm');
  assert.equal($('mfaBadge').textContent,'Enabled',$('securityError').textContent);
  const codes=[...$('recoveryCodes').children].map(li=>li.textContent);assert.equal(codes.length,10);
  assert.equal($('manualKey').value,'');assert.equal($('mfaQr').hasAttribute('src'),false);
  assert.equal(w.localStorage.length,0,'authenticator data must stay out of localStorage');
  await $('logoutButton').onclick();await login();
  assert.ok(!$('twoFactorForm').classList.contains('hidden'));assert.ok($('shell').classList.contains('hidden'));
  $('loginCode').value='000000';await submit('twoFactorForm');
  assert.match($('codeError').textContent,/Invalid|already used/);assert.ok($('shell').classList.contains('hidden'));
  $('toggleRecovery').click();assert.equal($('loginCode').maxLength,80);
  $('loginCode').value=codes[0];await submit('twoFactorForm');assert.ok(!$('shell').classList.contains('hidden'),$('codeError').textContent);
  await $('settingsButton').onclick();assert.match($('mfaStatus').textContent,/9 recovery codes/);
  $('mfaRecovery').click();$('securityPassword').value='app-secret';$('securityCode').value=codes[1];await submit('securityPasswordForm');
  const replacement=[...$('recoveryCodes').children].map(li=>li.textContent);assert.equal(replacement.length,10);assert.notDeepEqual(replacement,codes);
  $('savedRecovery').click();assert.equal($('recoveryCodes').children.length,0);
  $('mfaDisable').click();$('securityPassword').value='app-secret';$('securityCode').value=replacement[0];await submit('securityPasswordForm');
  assert.equal($('mfaBadge').textContent,'Not enabled',$('securityError').textContent);
});
