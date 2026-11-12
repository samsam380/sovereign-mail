// Read-only demo preview server; never forwards credentials or real mail.
import http from 'node:http';
import {readFile} from 'node:fs/promises';
const arg=name=>{const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
const host=arg('--host')||'127.0.0.1',port=Number(arg('--port')||8787);
const files={'/':['index.html','text/html'],'/app.js':['app.js','text/javascript'],'/app.css':['app.css','text/css'],'/mark.svg':['mark.svg','image/svg+xml']};
http.createServer(async(req,res)=>{
  res.setHeader('Cache-Control','no-store');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'");
  const path=new URL(req.url,'http://localhost').pathname;
  if(req.method!=='GET'){res.writeHead(405);res.end();return;}
  if(path==='/api/config'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({demo:true,domain:'example.com'}));return;}
  if(path==='/offline-preview.html'){res.removeHeader('Content-Security-Policy');res.setHeader('Content-Type','text/html');res.end(await readFile(new URL('../Sovereign-Mail-Preview.html',import.meta.url)));return;}
  if(path==='/healthz'){res.end('ok');return;}
  const file=files[path];if(!file){res.writeHead(404);res.end();return;}
  try{const content=await readFile(new URL('../app/static/'+file[0],import.meta.url));res.setHeader('Content-Type',file[1]);res.end(content);}catch{res.writeHead(500);res.end();}
}).listen(port,host,()=>console.log(`Read-only Sovereign Mail preview on http://${host}:${port}`));
