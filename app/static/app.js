const CORE='urn:ietf:params:jmap:core', MAIL='urn:ietf:params:jmap:mail', SUB='urn:ietf:params:jmap:submission';
const $ = id => document.getElementById(id);
const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roles = [['inbox','Inbox','inbox'],['starred','Starred','star'],['sent','Sent','send'],['drafts','Drafts','file'],['archive','Archive','archive'],['junk','Spam','shield'],['trash','Trash','trash']];
const paths = {inbox:'M3 4h18v16H3z M3 13h5l2 3h4l2-3h5',star:'m12 3 2.8 5.6 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.5l6.2-.9Z',send:'m3 3 18 9-18 9 4-9-4-9Z M7 12h14',file:'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6',envelope:'M3 5h18v14H3z M3 5l9 7 9-7',archive:'M3 4h18v5H3z M5 9v12h14V9 M9 13h6',shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M12 8v5 M12 16v1',trash:'M4 6h16 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7'};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.file}" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
export function recipients(value){
  if(!value.trim())return [];
  return value.split(',').map(x=>{const email=x.trim();if(!/^[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+$/.test(email))throw Error('Use comma-separated email addresses, without display names.');return {email};});
}
export function makeEmail(form, identity, draftId){
  if(!draftId)throw Error('Create a mailbox with the Drafts role in Stalwart first.');
  return {mailboxIds:{[draftId]:true},keywords:{'$draft':true,'$seen':true},from:[{email:identity.email,name:identity.name||''}],
    to:recipients(form.to),cc:recipients(form.cc),bcc:recipients(form.bcc),subject:form.subject,
    textBody:[{partId:'body',type:'text/plain'}],bodyValues:{body:{value:form.body}},
    ...(form.attachments.length?{attachments:form.attachments.map(a=>({blobId:a.blobId,type:a.type||'application/octet-stream',name:a.name,disposition:'attachment'}))}:{})};
}
export function submissionPayload(accountId, identityId, emailId, sentId){
  if(!sentId)throw Error('Create a mailbox with the Sent role in Stalwart first.');
  return {accountId,create:{send:{identityId,emailId}},onSuccessUpdateEmail:{'#send':{mailboxIds:{[sentId]:true},'keywords/$draft':null,'keywords/$seen':true}}};
}
async function http(path, options={}){
  const response=await fetch(path,{credentials:'same-origin',...options});
  let data;try{data=await response.json();}catch{throw Error('The server returned an unreadable response.');}
  if(!response.ok){const error=Error(data.error||'The request failed.');error.status=response.status;throw error;}return data;
}
export class Live {
  constructor(session){this.session=session;this.email=session.email;this.account=session.jmap.primaryAccounts[MAIL];this.boxes=[];this.identities=[];}
  async call(name,args,capability=MAIL){
    const value=await http('/api/jmap',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.session.csrf},body:JSON.stringify({using:[...new Set([CORE,MAIL,capability])],methodCalls:[[name,{accountId:this.account,...args},'0']]})});
    const result=value.methodResponses?.find(x=>x[2]==='0');if(!result)throw Error('No response from the mail engine.');
    if(result[0]==='error')throw Error(result[1].description||result[1].type||'Mail request rejected.');
    return {value:result[1],all:value.methodResponses};
  }
  async init(){this.boxes=(await this.call('Mailbox/get',{})).value.list;this.identities=(await this.call('Identity/get',{},SUB)).value.list;}
  box(role){return this.boxes.find(x=>x.role===role);}
  async list(role,text,unread,position){
    const filter={};if(role==='starred')filter.hasKeyword='$flagged';else{if(!this.box(role))throw Error('This folder is missing. Create its mailbox role in Stalwart.');filter.inMailbox=this.box(role).id;}
    if(text)filter.text=text;if(unread)filter.notKeyword='$seen';
    const query=(await this.call('Email/query',{filter,sort:[{property:'receivedAt',isAscending:false}],position,limit:50,calculateTotal:true})).value;
    const emails=query.ids.length?(await this.call('Email/get',{ids:query.ids,properties:['id','from','to','subject','preview','receivedAt','keywords','hasAttachment','mailboxIds']})).value.list:[];
    const order=new Map(query.ids.map((id,i)=>[id,i]));emails.sort((a,b)=>order.get(a.id)-order.get(b.id));
    return {emails,total:query.total??query.ids.length,hasMore:query.total===undefined?query.ids.length===50:position+query.ids.length<query.total};
  }
  async get(id){const result=(await this.call('Email/get',{ids:[id],properties:['id','from','to','cc','bcc','subject','receivedAt','keywords','mailboxIds','textBody','htmlBody','bodyValues','attachments'],fetchAllBodyValues:true,maxBodyValueBytes:1000000})).value;if(!result.list?.length)throw Error('This message no longer exists.');return result.list[0];}
  async patch(id,patch){const v=(await this.call('Email/set',{update:{[id]:patch}})).value;if(v.notUpdated?.[id])throw Error(v.notUpdated[id].description||v.notUpdated[id].type);}
  async move(email,role){const target=this.box(role);if(!target)throw Error('The destination folder is missing.');await this.patch(email.id,{mailboxIds:{[target.id]:true}});}
  async remove(id){const v=(await this.call('Email/set',{destroy:[id]})).value;if(v.notDestroyed?.[id])throw Error(v.notDestroyed[id].description||v.notDestroyed[id].type);}
  async save(form){const identity=this.identities.find(x=>x.id===form.identity);if(!identity)throw Error('No sending identity is configured.');const v=(await this.call('Email/set',{create:{draft:makeEmail(form,identity,this.box('drafts')?.id)}})).value;if(!v.created?.draft)throw Error(v.notCreated?.draft?.description||v.notCreated?.draft?.type||'Could not save draft.');const id=v.created.draft.id;let warning='';if(form.draftId){try{await this.remove(form.draftId);}catch{warning='A previous draft copy could not be removed.';}}return {id,warning};}
  async send(form){
    // Persist before submitting. An ambiguous transport failure must NEVER auto-resubmit.
    const saved=await this.save(form);form.draftId=saved.id;
    let result;
    try{result=await this.call('EmailSubmission/set',submissionPayload(this.account,form.identity,saved.id,this.box('sent')?.id),SUB);}
    catch(error){error.uncertain=true;throw error;}
    const v=result.value;if(!v.created?.send)throw Error(v.notCreated?.send?.description||v.notCreated?.send?.type||'Submission was rejected. The draft has been kept.');
    const filing=result.all.find(x=>x[0]==='Email/set');
    return {warning:filing?.[1]?.notUpdated?.[saved.id]?'Queued for delivery, but filing into Sent failed. Do not resend.':saved.warning};
  }
  async upload(file){if(file.size>10*1024*1024)throw Error('Each attachment must be 10 MiB or smaller.');const blob=await http('/api/upload?account='+encodeURIComponent(this.account),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':this.session.csrf},body:file});return {...blob,name:file.name,type:file.type||'application/octet-stream'};}
  async download(file){const q=new URLSearchParams({account:this.account,blob:file.blobId,name:file.name||'attachment'});const response=await fetch('/api/download?'+q,{credentials:'same-origin'});if(!response.ok)throw Error('Could not download this attachment.');return response.blob();}
  async refresh(){this.boxes=(await this.call('Mailbox/get',{})).value.list;}
  async logout(){await http('/api/logout',{method:'POST',headers:{'X-CSRF-Token':this.session.csrf}});}
}
class Demo {
  constructor(){this.email='demo@example.com';this.account='preview';this.identities=[{id:'demo',email:this.email,name:'Demo User'}];this.boxes=roles.filter(x=>x[0]!=='starred').map(([role,name])=>({id:role,role,name,unreadEmails:0}));const now=Date.now();
    const entries=[
      ['Sovereign Mail','hello@sovereign.example','Welcome to a more sovereign inbox.','Hello,\n\nWelcome to Sovereign Mail. A familiar place for your conversations, built to live on your own server.\n\nYour address is yours. Your inbox has a home you control.\n\nStart small: one mailbox, a few messages, and a reliable backup. Then make it your own.\n\nA few things to try in this preview:\n\n• Write a message and save a draft\n• Star a conversation you want to come back to\n• Move a message to Archive\n• Choose Light, Dark, or Teal in the theme menu\n\nThese are sample messages. No mail will be sent from this preview.\n\nHere’s to a little more independence.\nThe Sovereign Mail team',false,false],
      ['Maya · Studio','maya@studio.example','A few ideas for the next chapter','Hello,\n\nI’ve put together a few layout ideas for the next chapter. The simpler typography gives the writing room to breathe.\n\nLet me know what you think when you have a quiet moment.\n\nMaya',false,true],
      ['The Reading Room','notes@reading.example','This week: time, energy, and good questions','Hello,\n\nOur reading note this week explores the relationship between energy and the things we choose to preserve.\n\nOne question to carry with you: what would you build if you expected it to last a hundred years?\n\nEnjoy the read,\nThe Reading Room',false,false],
      ['Alex','alex@friend.example','Coffee when you’re back?','Hello,\n\nHope the journey home was a good one. Let’s find time for coffee next week. I’d love to hear what you’re building.\n\nAlex',true,false],
      ['Workshop Journal','journal@workshop.example','Small projects, steady progress','A note from the workshop:\n\nBig projects are a collection of small, finished steps. Today’s step counts.\n\nSee you next week.',true,true],
      ['Nadia','nadia@friend.example','A playlist for the long way home','Hello,\n\nHere’s the playlist we were talking about. Some old favorites and a few new discoveries.\n\nSafe travels,\nNadia',true,false]
    ];this.messages=entries.map((e,i)=>({id:'sample-'+i,from:[{name:e[0],email:e[1]}],to:[{email:this.email}],cc:[],bcc:[],subject:e[2],preview:e[3].replace(/\n/g,' ').slice(0,140),receivedAt:new Date(now-i*3700000).toISOString(),keywords:{...(e[4]?{'$seen':true}:{}),...(e[5]?{'$flagged':true}:{})},mailboxIds:{inbox:true},textBody:[{partId:'body'}],htmlBody:[],bodyValues:{body:{value:e[3]}},attachments:[],hasAttachment:false}));this.messages.push({...structuredClone(this.messages[4]),id:'archived',subject:'A note worth keeping',mailboxIds:{archive:true}});this.refresh();}
  async init(){} box(role){return this.boxes.find(b=>b.role===role);}async refresh(){for(const b of this.boxes)b.unreadEmails=this.messages.filter(m=>m.mailboxIds[b.id]&&!m.keywords.$seen).length;}
  async list(role,text,unread,position){const all=this.messages.filter(m=>(role==='starred'?m.keywords.$flagged:m.mailboxIds[role])&&(!unread||!m.keywords.$seen)&&(!text||[m.subject,m.preview,...m.from.map(x=>x.name+' '+x.email)].join(' ').toLowerCase().includes(text.toLowerCase()))).sort((a,b)=>b.receivedAt.localeCompare(a.receivedAt));return {emails:structuredClone(all.slice(position,position+50)),total:all.length,hasMore:position+50<all.length};}
  async get(id){return structuredClone(this.messages.find(m=>m.id===id));}
  async patch(id,patch){const m=this.messages.find(m=>m.id===id);for(const [k,v] of Object.entries(patch)){if(k.startsWith('keywords/')){const key=k.slice(9);if(v===null)delete m.keywords[key];else m.keywords[key]=v;}else m[k]=v;}await this.refresh();}
  async move(email,role){await this.patch(email.id,{mailboxIds:{[role]:true}});}async remove(id){this.messages=this.messages.filter(m=>m.id!==id);}
  async save(form){const id='draft-'+Date.now();this.messages.push({...makeEmail(form,this.identities[0],'drafts'),id,receivedAt:new Date().toISOString(),preview:form.body.slice(0,140),hasAttachment:!!form.attachments.length});if(form.draftId)await this.remove(form.draftId);return {id};}
  async send(){throw Error('Sending is disabled in this preview. Save a draft to try the composer.');}
  async upload(){throw Error('Connect a real mailbox to upload attachments.');}async logout(){}async download(){throw Error('No downloadable files in this preview.');}
}
let client,config,folder='inbox',unread=false,query='',position=0,emails=[],selected=null,sequence=0,readerSequence=0,toastTimer,refreshTimer,draftId=null,uploads=[],dirty=false,busy=false,uploading=false,uncertain=false,hydrating=false;
function toast(text){$('toast').textContent=text;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),7000);}
function fail(error){toast(error.message||String(error));if(error.status===401)showLogin();}
function action(fn){return async(...args)=>{try{await fn(...args);}catch(error){fail(error);}};}
function nameOf(email){return email?.from?.[0]?.name||email?.from?.[0]?.email||'Unknown sender';}
function initials(name){return name.split(/[^\p{L}\p{N}]+/u).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase();}
function formatDate(value){const d=new Date(value);if(Number.isNaN(d.valueOf()))return '';return d.toLocaleDateString(undefined,{month:'short',day:'numeric'});}
function textOf(email){const parts=email.textBody?.length?email.textBody:email.htmlBody||[];return parts.map(p=>{const raw=email.bodyValues?.[p.partId]?.value||'';if(email.textBody?.length)return raw;const t=document.createElement('template');t.innerHTML=raw;t.content.querySelectorAll('script,style,noscript').forEach(x=>x.remove());t.content.querySelectorAll('p,div,br,li,tr,h1,h2,h3').forEach(x=>x.prepend(document.createTextNode('\n')));return t.content.textContent||'';}).join('\n');}
function renderFolders(){
  $('folders').innerHTML=roles.map(([role,name,ico],i)=>`${i===5?'<div class="nav-divider"></div>':''}<button class="nav-item ${folder===role?'active':''}" data-folder="${role}" ${folder===role?'aria-current="page"':''}>${icon(ico)}<span>${name}</span>${client.box(role)?.unreadEmails?`<span class="count">${client.box(role).unreadEmails}</span>`:''}</button>`).join('');
  document.querySelectorAll('[data-folder]').forEach(b=>b.onclick=action(async()=>{folder=b.dataset.folder;position=0;query='';$('search').value='';selected=null;$('sidebar').classList.remove('open');await load();}));
}
function renderList(total,hasMore){
  $('resultCount').textContent=total+' total';$('folderCount').textContent=client.box(folder)?.unreadEmails||'';
  $('messageList').innerHTML=emails.length?emails.map(m=>`<div class="message-row ${!m.keywords.$seen?'unread':''} ${selected?.id===m.id?'selected':''}" data-id="${esc(m.id)}" role="button" tabindex="0" aria-label="${esc(nameOf(m)+': '+(m.subject||'No subject'))}">${!m.keywords.$seen?'<span class="unread-dot"></span>':''}<div class="row-meta"><span class="row-avatar">${esc(initials(nameOf(m)))}</span><span class="row-sender">${esc(nameOf(m))}</span><span class="row-time">${esc(formatDate(m.receivedAt))}</span></div><h3 class="row-subject">${esc(m.subject||'(No subject)')}</h3><div class="row-preview">${m.hasAttachment?'<span class="row-paperclip">⌁</span>':''}${esc(m.preview)}</div><button class="row-star ${m.keywords.$flagged?'flagged':''}" aria-label="${m.keywords.$flagged?'Unstar':'Star'} message" data-star="${esc(m.id)}">${m.keywords.$flagged?'★':'☆'}</button></div>`).join(''):'<div class="empty-reader"><div class="empty-mark">✓</div><h2>Room to breathe.</h2><p>No messages match this view.</p></div>';
  document.querySelectorAll('.message-row').forEach(row=>{row.onclick=action(()=>openMessage(row.dataset.id));row.onkeydown=e=>{if(e.target!==row)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();action(()=>openMessage(row.dataset.id))();}};});
  document.querySelectorAll('[data-star]').forEach(b=>b.onclick=action(async e=>{e.stopPropagation();const m=emails.find(x=>x.id===b.dataset.star);await client.patch(m.id,{'keywords/$flagged':m.keywords.$flagged?null:true});if(selected?.id===m.id)selected=await client.get(m.id);await load(false);}));
  $('pageInfo').textContent=total?`${position+1}–${position+emails.length}`:'0';$('prevPage').disabled=position===0;$('nextPage').disabled=!hasMore;
}
async function load(reset=true){
  const ticket=++sequence;$('syncLabel').textContent='Updating…';$('folderTitle').firstChild.textContent=(roles.find(x=>x[0]===folder)?.[1]||folder)+' ';$('folderSubtitle').textContent=query?`Results for “${query}”`:'A little space to stay connected.';renderFolders();
  if(reset){++readerSequence;selected=null;document.querySelector('.workspace').classList.remove('reading');emptyReader();}
  try{const result=await client.list(folder,query,unread,position);if(ticket!==sequence)return;emails=result.emails;renderList(result.total,result.hasMore);$('syncLabel').textContent=config.demo?'Preview · sample data':'Updated '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}
  catch(error){$('syncLabel').textContent='Update failed';throw error;}
}
function emptyReader(){$('reader').innerHTML='<div class="empty-reader"><div class="empty-mark">✉</div><h2>A quieter kind of inbox.</h2><p>Choose a conversation to read.</p></div>';}
async function openMessage(id){
  const ticket=++readerSequence;const email=await client.get(id);if(ticket!==readerSequence)return;
  if(!email)throw Error('This message no longer exists.');selected=email;
  if(!email.keywords.$seen){await client.patch(id,{'keywords/$seen':true});email.keywords.$seen=true;const row=emails.find(x=>x.id===id);if(row)row.keywords.$seen=true;await client.refresh();renderFolders();$('folderCount').textContent=client.box(folder)?.unreadEmails||'';}
  if(ticket!==readerSequence)return;
  document.querySelectorAll('.message-row').forEach(row=>{row.classList.toggle('selected',row.dataset.id===id);if(row.dataset.id===id){row.classList.remove('unread');row.querySelector('.unread-dot')?.remove();}});
  document.querySelector('.workspace').classList.add('reading');renderReader(email);
}
function renderReader(email){
  const sender=email.from?.[0]||{};const body=textOf(email);const truncated=Object.values(email.bodyValues||{}).some(x=>x.isTruncated);
  $('reader').innerHTML=`<div class="reader-tools"><button class="icon-button back-list" id="backList" aria-label="Back to messages">←</button><button class="icon-button" id="archiveMail" title="Archive" aria-label="Archive message">${icon('archive')}</button><button class="icon-button" id="trashMail" title="${folder==='trash'?'Delete permanently':'Move to trash'}" aria-label="${folder==='trash'?'Delete permanently':'Move to trash'}">${icon('trash')}</button><span class="separator"></span><button class="icon-button" id="unreadMail" title="Mark unread" aria-label="Mark unread">${icon('envelope')}</button><button class="icon-button" id="spamMail" title="${folder==='junk'?'Move to inbox':'Move to spam'}" aria-label="${folder==='junk'?'Move to inbox':'Move to spam'}">${icon('shield')}</button><button class="icon-button last" id="readerStar" title="Toggle star" aria-label="Toggle star">${email.keywords.$flagged?'★':'☆'}</button></div><article class="message-content"><span class="message-label">${esc(roles.find(x=>x[0]===folder)?.[1]||'MAIL')}</span><h2>${esc(email.subject||'(No subject)')}</h2><div class="sender-line"><span class="avatar">${esc(initials(nameOf(email)))}</span><div class="sender-info"><b>${esc(sender.name||sender.email||'Unknown sender')}</b><small>${esc(sender.email||'')}<br>To: ${esc((email.to||[]).map(x=>x.email).join(', '))}${email.cc?.length?'<br>Cc: '+esc(email.cc.map(x=>x.email).join(', ')):''}</small></div><span class="sender-date">${esc(formatDate(email.receivedAt))}<br>${esc(new Date(email.receivedAt).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}))}</span></div><div id="emailBody" class="email-body"></div>${truncated?'<p class="message-note">Message text was truncated at 1 MB. Use an IMAP client to read the complete message.</p>':''}${!email.textBody?.length&&email.htmlBody?.length?'<p class="message-note">HTML converted to text. Remote content is blocked.</p>':''}<div class="attachment-list">${(email.attachments||[]).map((a,i)=>`<button class="file-chip" data-download="${i}">↓ ${esc(a.name||'Attachment')}<small>${a.size?(a.size/1024).toFixed(1)+' KB · ':''}Download file</small></button>`).join('')}</div><div class="reader-actions">${folder==='drafts'?'<button class="secondary" id="editDraft">Continue writing →</button>':'<button class="secondary" id="replyMail">↶ Reply</button><button class="secondary" id="forwardMail">Forward →</button>'}</div></article>`;
  $('emailBody').textContent=body||'(No readable text body)';
  $('backList').onclick=()=>document.querySelector('.workspace').classList.remove('reading');
  $('archiveMail').onclick=action(async()=>{await client.move(email,'archive');await refresh(true);toast('Moved to Archive.');});
  $('trashMail').onclick=action(async()=>{if(folder==='trash'){if(!confirm('Permanently delete this message? This cannot be undone.'))return;await client.remove(email.id);}else await client.move(email,'trash');await refresh(true);toast('Message removed.');});
  $('unreadMail').onclick=action(async()=>{await client.patch(email.id,{'keywords/$seen':null});await refresh(true);toast('Marked unread.');});
  $('spamMail').onclick=action(async()=>{await client.move(email,folder==='junk'?'inbox':'junk');await refresh(true);});
  $('readerStar').onclick=action(async()=>{await client.patch(email.id,{'keywords/$flagged':email.keywords.$flagged?null:true});selected=await client.get(email.id);renderReader(selected);await load(false);});
  $('replyMail')?.addEventListener('click',()=>compose({to:sender.email||'',subject:/^re:/i.test(email.subject)?email.subject:'Re: '+(email.subject||''),body:'\n\nOn '+formatDate(email.receivedAt)+', '+nameOf(email)+' wrote:\n'+body.split('\n').map(l=>'> '+l).join('\n')}));
  $('forwardMail')?.addEventListener('click',()=>compose({subject:'Fwd: '+(email.subject||''),body:'\n\n---------- Forwarded message ----------\nFrom: '+(sender.email||'')+'\nSubject: '+(email.subject||'')+'\n\n'+body}));
  $('editDraft')?.addEventListener('click',()=>compose({to:(email.to||[]).map(x=>x.email).join(', '),cc:(email.cc||[]).map(x=>x.email).join(', '),bcc:(email.bcc||[]).map(x=>x.email).join(', '),subject:email.subject||'',body,draftId:email.id,attachments:email.attachments||[]}));
  document.querySelectorAll('[data-download]').forEach(b=>b.onclick=action(async()=>{const file=email.attachments[Number(b.dataset.download)];const blob=await client.download(file);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=file.name||'attachment';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
}
async function refresh(reset=false){await client.refresh();await load(reset);}
function compose(data={}){hydrating=true;draftId=data.draftId||null;uploads=structuredClone(data.attachments||[]);dirty=false;uncertain=false;for(const key of ['to','cc','bcc','subject','body'])$(key).value=data[key]||'';$('composeTitle').textContent=draftId?'Continue your draft':'New message';$('composeError').textContent='';$('sendButton').disabled=false;$('fromIdentity').innerHTML=client.identities.map(i=>`<option value="${esc(i.id)}">${esc((i.name?i.name+' · ':'')+i.email)}</option>`).join('');renderUploads();$('composer').showModal();hydrating=false;setTimeout(()=>$(data.to?'body':'to').focus(),50);}
function formValue(){return {to:$('to').value,cc:$('cc').value,bcc:$('bcc').value,subject:$('subject').value,body:$('body').value,identity:$('fromIdentity').value,attachments:uploads,draftId};}
function renderUploads(){$('uploadList').innerHTML=uploads.map((a,i)=>`<button type="button" class="file-chip" data-remove="${i}">${esc(a.name)} ×</button>`).join('');document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{if(busy)return;uploads.splice(Number(b.dataset.remove),1);dirty=true;renderUploads();});}
function closeComposer(){if(busy||uploading)return;if(dirty&&!confirm('Close without saving these changes?'))return;$('composer').close();}
function setBusy(value){busy=value;for(const id of ['sendButton','saveDraft','to','cc','bcc','subject','body','attachment','fromIdentity','closeCompose'])$(id).disabled=value;}
function showLogin(){loginChallenge=null;$('loginForm').classList.remove('hidden');$('twoFactorForm').classList.add('hidden');$('loginCode').value='';$('codeError').textContent='';clearInterval(refreshTimer);$('composer').close();$('settings').close();$('shell').classList.add('hidden');$('login').classList.remove('hidden');client=null;selected=null;emails=[];$('messageList').replaceChildren();emptyReader();$('password').value='';}
async function enter(){await client.init();$('login').classList.add('hidden');$('shell').classList.remove('hidden');$('demoBanner').classList.toggle('hidden',!config.demo);$('modeLabel').textContent=config.demo?'PREVIEW WORKSPACE':'PERSONAL WORKSPACE';$('accountEmail').textContent=client.email;$('accountName').textContent=client.identities[0]?.name||client.email.split('@')[0];$('domainLabel').textContent=config.domain;$('settingsAddress').textContent=client.email;$('webmailHost').textContent=location.host;folder='inbox';query='';position=0;await load();if(config.demo&&emails.length)await openMessage(emails[0].id);clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden&&!$('composer').open)action(()=>refresh(false))();},60000);}
// v1 stored its teal palette as "dark". Preserve that preference while
// keeping the new neutral Dark palette independently selectable.
export function resolveTheme(current,legacy){
  if(['light','dark','teal'].includes(current))return current;
  return legacy==='dark'?'teal':'light';
}
function applyTheme(value,persist=true){
  const theme=resolveTheme(value,null);
  document.documentElement.dataset.theme=theme;
  document.documentElement.classList.remove('dark');
  $('themeSelect').value=theme;
  document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===theme)));
  if(persist){try{localStorage.setItem('sovereign-theme-v2',theme);}catch{}}
}
let loginChallenge=null, recoveryMode=false, securityAction='setup', securityBusy=false, recoveryCodes=[];
function challengeMode(recovery=false){
  recoveryMode=recovery;const input=$('loginCode');input.value='';input.maxLength=recovery?80:6;input.inputMode=recovery?'text':'numeric';input.pattern=recovery?'[A-Fa-f0-9 -]{32,80}':'[0-9]{6}';input.placeholder=recovery?'Recovery code':'000000';$('loginCodeLabel').firstChild.textContent=recovery?'Recovery code':'Authenticator code';$('toggleRecovery').textContent=recovery?'Use an authenticator code':'Use a recovery code';$('codeError').textContent='';input.focus();
}
function securityHeaders(){return {'Content-Type':'application/json','X-CSRF-Token':client.session.csrf};}
function securityRequest(path,body){return http(path,{method:'POST',headers:securityHeaders(),body:JSON.stringify(body)});}
function clearSecurity(){
  for(const id of ['securityPasswordForm','mfaEnrollment','recoveryCodesPanel'])$(id).classList.add('hidden');
  for(const id of ['securityPassword','securityCode','setupCode','manualKey'])$(id).value='';
  $('mfaQr').removeAttribute('src');$('recoveryCodes').replaceChildren();$('securityError').textContent='';recoveryCodes=[];
}
function setSecurityBusy(value){securityBusy=value;for(const id of ['mfaSetup','mfaRecovery','mfaDisable','securityContinue','mfaEnable','closeSettings'])$(id).disabled=value;}
async function loadSecurity(){
  if(config.demo){$('mfaBadge').textContent='Preview';$('mfaStatus').textContent='Sign in to your real mailbox to set up an authenticator.';$('mfaSetup').disabled=true;return;}
  const status=await http('/api/security');$('mfaBadge').textContent=status.enabled?'Enabled':'Not enabled';$('mfaBadge').classList.toggle('enabled',status.enabled);
  $('mfaStatus').textContent=status.enabled?`Your password and a second factor are required at sign-in. ${status.recoveryCodesRemaining} recovery codes remain.`:'Protect your mailbox with Google Authenticator or another time-based authenticator.';
  $('mfaSetup').classList.toggle('hidden',status.enabled);$('mfaRecovery').classList.toggle('hidden',!status.enabled);$('mfaDisable').classList.toggle('hidden',!status.enabled);
}
async function openSettings(){clearSecurity();$('settings').showModal();try{await loadSecurity();}catch(error){$('securityError').textContent=error.message;}}
function securityForm(action){
  clearSecurity();securityAction=action;$('securityPasswordForm').classList.remove('hidden');const needsCode=action!=='setup';$('securityCodeLabel').classList.toggle('hidden',!needsCode);$('securityCode').required=needsCode;
  $('securityActionTitle').textContent=action==='setup'?'Confirm your mailbox password':action==='disable'?'Turn off two-factor authentication':'Replace recovery codes';
  $('securityContinue').textContent=action==='setup'?'Continue to authenticator setup':action==='disable'?'Turn off 2FA':'Generate new codes';$('securityPassword').focus();
}
function updateSecuritySession(payload){client.session={email:payload.email,csrf:payload.csrf,jmap:payload.jmap};}
function showRecovery(codes){
  recoveryCodes=codes;$('recoveryCodes').replaceChildren(...codes.map(code=>{const li=document.createElement('li');li.textContent=code;return li;}));$('recoveryCodesPanel').classList.remove('hidden');
}

async function start(){
  let theme='light';
  try{theme=resolveTheme(localStorage.getItem('sovereign-theme-v2'),localStorage.getItem('sovereign-theme'));}catch{}
  applyTheme(theme,false);
  $('themeSelect').onchange=e=>applyTheme(e.target.value);
  document.querySelectorAll('[data-theme-choice]').forEach(b=>b.onclick=()=>applyTheme(b.dataset.themeChoice));
  $('loginForm').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;$('loginError').textContent='';try{const session=await http('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:$('email').value.trim(),password:$('password').value})});$('password').value='';if(session.requires2fa){loginChallenge=session;$('challengeEmail').textContent=session.email;$('loginForm').classList.add('hidden');$('twoFactorForm').classList.remove('hidden');challengeMode(false);}else{loginChallenge=null;client=new Live(session);await enter();}}catch(error){$('loginError').textContent=error.message;}finally{$('password').value='';button.disabled=false;}};
  $('twoFactorForm').onsubmit=async e=>{e.preventDefault();if(!loginChallenge)return;const button=e.submitter;button.disabled=true;$('codeError').textContent='';try{const session=await http('/api/login/2fa',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':loginChallenge.csrf},body:JSON.stringify({code:$('loginCode').value.trim()})});loginChallenge=null;$('loginCode').value='';client=new Live(session);await enter();}catch(error){$('codeError').textContent=error.message;}finally{button.disabled=false;$('loginCode').value='';}};
  $('toggleRecovery').onclick=()=>challengeMode(!recoveryMode);
  $('cancelChallenge').onclick=async()=>{if(loginChallenge){try{await http('/api/login/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':loginChallenge.csrf},body:'{}'});}catch{}}showLogin();};

  $('composeButton').onclick=()=>compose();$('closeCompose').onclick=closeComposer;$('composer').addEventListener('cancel',e=>{e.preventDefault();closeComposer();});
  $('composeForm').addEventListener('input',()=>{if(!hydrating)dirty=true;});
  $('attachment').onchange=async e=>{if(busy)return;uploading=true;setBusy(true);try{for(const file of [...e.target.files]){const result=await client.upload(file);uploads.push(result);dirty=true;renderUploads();}}catch(error){$('composeError').textContent=error.message;}finally{e.target.value='';uploading=false;setBusy(false);}};
  $('saveDraft').onclick=async()=>{if(busy||uploading)return;setBusy(true);try{const result=await client.save(formValue());draftId=result.id;dirty=false;toast(result.warning||'Draft saved to your mailbox.');await refresh(false);}catch(error){$('composeError').textContent=error.message;}finally{setBusy(false);}};
  $('composeForm').onsubmit=async e=>{e.preventDefault();if(busy||uploading||uncertain)return;const form=formValue();try{if(!recipients(form.to).length)throw Error('Add at least one recipient.');recipients(form.cc);recipients(form.bcc);if(!form.subject&&!confirm('Send without a subject?'))return;}catch(error){$('composeError').textContent=error.message;return;}setBusy(true);$('composeError').textContent='';let sent=false;try{const result=await client.send(form);dirty=false;sent=true;$('composer').close();toast(result.warning||'Message queued for delivery.');}catch(error){draftId=form.draftId;uncertain=!!error.uncertain;$('composeError').textContent=uncertain?'The submission outcome is uncertain. Check Sent and the server queue before sending again. '+error.message:error.message;}finally{setBusy(false);if(uncertain)$('sendButton').disabled=true;}if(sent)await action(()=>refresh(false))();};
  $('searchForm').onsubmit=action(async e=>{e.preventDefault();query=$('search').value.trim();position=0;await load();});
  $('search').addEventListener('input',()=>{if(!$('search').value&&query){query='';position=0;action(()=>load())();}});
  $('allFilter').onclick=action(async()=>{unread=false;position=0;$('allFilter').classList.add('active');$('unreadFilter').classList.remove('active');await load();});
  $('unreadFilter').onclick=action(async()=>{unread=true;position=0;$('unreadFilter').classList.add('active');$('allFilter').classList.remove('active');await load();});
  $('refreshButton').onclick=action(()=>refresh(true));$('prevPage').onclick=action(async()=>{position=Math.max(0,position-50);await load();});$('nextPage').onclick=action(async()=>{position+=50;await load();});
  $('menuButton').onclick=()=>$('sidebar').classList.toggle('open');
  $('settingsButton').onclick=$('accountButton').onclick=openSettings;
  $('closeSettings').onclick=()=>{if(!securityBusy)$('settings').close();};
  $('settings').addEventListener('cancel',e=>{if(securityBusy)e.preventDefault();});$('settings').addEventListener('close',clearSecurity);
  $('mfaSetup').onclick=()=>securityForm('setup');$('mfaRecovery').onclick=()=>securityForm('recovery');$('mfaDisable').onclick=()=>securityForm('disable');
  $('securityPasswordForm').onsubmit=async e=>{e.preventDefault();if(securityBusy)return;setSecurityBusy(true);$('securityError').textContent='';try{const result=await securityRequest('/api/security/'+(securityAction==='setup'?'setup':securityAction==='disable'?'disable':'recovery'),{password:$('securityPassword').value,code:$('securityCode').value.trim()});$('securityPasswordForm').classList.add('hidden');if(securityAction==='setup'){$('manualKey').value=result.secret;$('mfaQr').src='/api/security/qr';$('mfaEnrollment').classList.remove('hidden');$('setupCode').focus();}else{updateSecuritySession(result);await loadSecurity();if(securityAction==='recovery')showRecovery(result.recoveryCodes);else toast('Two-factor authentication turned off.');}}catch(error){$('securityError').textContent=error.message;}finally{$('securityPassword').value='';$('securityCode').value='';setSecurityBusy(false);}};
  $('mfaConfirmForm').onsubmit=async e=>{e.preventDefault();if(securityBusy)return;setSecurityBusy(true);$('securityError').textContent='';try{const result=await securityRequest('/api/security/enable',{code:$('setupCode').value});updateSecuritySession(result);$('mfaEnrollment').classList.add('hidden');$('manualKey').value='';$('mfaQr').removeAttribute('src');await loadSecurity();showRecovery(result.recoveryCodes);toast('Two-factor authentication enabled. Save your recovery codes.');}catch(error){$('securityError').textContent=error.message;}finally{$('setupCode').value='';setSecurityBusy(false);}};
  $('copyMfaKey').onclick=async()=>{try{await navigator.clipboard.writeText($('manualKey').value);toast('Setup key copied.');}catch{$('manualKey').select();toast('Select and copy the setup key.');}};
  $('savedRecovery').onclick=()=>{recoveryCodes=[];$('recoveryCodes').replaceChildren();$('recoveryCodesPanel').classList.add('hidden');};
  $('downloadRecovery').onclick=()=>{if(!recoveryCodes.length)return;const text='Sovereign Mail recovery codes\n'+client.email+'\n\nEach code works once. Store privately.\n\n'+recoveryCodes.join('\n')+'\n';const url=URL.createObjectURL(new Blob([text],{type:'text/plain'}));const a=document.createElement('a');a.href=url;a.download='Sovereign-Mail-recovery-codes.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  $('logoutButton').onclick=action(async()=>{if($('composer').open&&dirty&&!confirm('Sign out and discard unsaved changes?'))return;await client.logout();dirty=false;showLogin();if(config.demo){client=new Demo();await enter();toast('Preview reset.');}});
  document.addEventListener('keydown',e=>{if($('composer').open&&(e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('composeForm').requestSubmit();return;}if(e.ctrlKey||e.metaKey||e.altKey||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)||$('composer').open||$('settings').open||!client)return;if(e.key==='/'){e.preventDefault();$('search').focus();}if(e.key==='c'){e.preventDefault();compose();}});
  window.addEventListener('beforeunload',e=>{if(dirty&&$('composer').open){e.preventDefault();e.returnValue='';}});
  config=await http('/api/config');if(config.demo){client=new Demo();await enter();}else{try{const session=await http('/api/session');client=new Live(session);await enter();}catch(error){if(error.status!==401)toast(error.message);showLogin();}}
}
if(typeof document!=='undefined')start().catch(fail);
