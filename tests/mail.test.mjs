import test from 'node:test';
import assert from 'node:assert/strict';
import {recipients,makeEmail,submissionPayload,Live} from '../app/static/app.js';
const form=()=>({to:'you@example.com',cc:'',bcc:'secret@example.com',subject:'hello',body:'Plain text',attachments:[],identity:'i'});
test('recipient parsing rejects header injection and ambiguous display names',()=>{
 assert.deepEqual(recipients(' a@example.com, b@example.com '),[{email:'a@example.com'},{email:'b@example.com'}]);
 for(const value of ['a@example.com\r\nBcc: evil@example.com','Person <a@example.com>','no-at-sign'])assert.throws(()=>recipients(value));
});
test('draft uses authenticated identity and preserves bcc and blob references',()=>{
 const f=form();f.attachments=[{blobId:'blob',name:'file.txt',type:'text/plain'}];
 const mail=makeEmail(f,{email:'demo@example.com',name:'Demo User'},'drafts-id');
 assert.equal(mail.from[0].email,'demo@example.com');assert.equal(mail.bcc[0].email,'secret@example.com');
 assert.equal(mail.bodyValues.body.value,'Plain text');assert.equal(mail.attachments[0].blobId,'blob');
 assert.equal(mail.keywords.$draft,true);assert.deepEqual(mail.mailboxIds,{'drafts-id':true});
});
test('submission retains a sent copy and removes draft status only on success',()=>{
 const p=submissionPayload('a','identity','email','sent');
 assert.deepEqual(p.create.send,{identityId:'identity',emailId:'email'});
 assert.deepEqual(p.onSuccessUpdateEmail['#send'].mailboxIds,{sent:true});
 assert.equal(p.onSuccessUpdateEmail['#send']['keywords/$draft'],null);
 assert.throws(()=>submissionPayload('a','i','e',null));
});
function fakeLive(){const c=new Live({email:'demo@example.com',jmap:{primaryAccounts:{'urn:ietf:params:jmap:mail':'a'}}});c.identities=[{id:'i',email:'demo@example.com'}];c.boxes=[{role:'drafts',id:'drafts'},{role:'sent',id:'sent'}];return c;}
test('failed submission preserves a persisted draft',async()=>{
 const c=fakeLive();c.call=async name=>name==='Email/set'?{value:{created:{draft:{id:'saved'}}}}:{value:{notCreated:{send:{type:'forbidden'}}},all:[]};
 const f=form();await assert.rejects(()=>c.send(f),/forbidden/);assert.equal(f.draftId,'saved');
});
test('uncertain submission is flagged and never retried automatically',async()=>{
 const c=fakeLive();let submissions=0;c.call=async name=>{if(name==='Email/set')return {value:{created:{draft:{id:'saved'}}}};submissions++;throw Error('connection lost');};
 const f=form();await assert.rejects(()=>c.send(f),e=>e.uncertain===true);assert.equal(submissions,1);assert.equal(f.draftId,'saved');
});
test('filing failure after successful submission reports warning instead of inviting resend',async()=>{
 const c=fakeLive();c.call=async name=>name==='Email/set'?{value:{created:{draft:{id:'saved'}}}}:{value:{created:{send:{id:'submission'}}},all:[['Email/set',{notUpdated:{saved:{type:'forbidden'}}},'1']]};
 const result=await c.send(form());assert.match(result.warning,/Do not resend/);
});

test('legacy dark preference migrates to the existing Teal palette',async()=>{
 const {resolveTheme}=await import('../app/static/app.js');
 assert.equal(resolveTheme(null,'dark'),'teal');assert.equal(resolveTheme(null,'light'),'light');
});
test('all three explicit theme choices persist independently',async()=>{
 const {resolveTheme}=await import('../app/static/app.js');
 for(const choice of ['light','dark','teal'])assert.equal(resolveTheme(choice,'dark'),choice);
 assert.equal(resolveTheme('invalid',null),'light');
});
