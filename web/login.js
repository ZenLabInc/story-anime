'use strict';
const next=new URLSearchParams(location.search).get('next');
if(next&&/^\/app(?:\/|$)/.test(next)&&!next.includes('\\'))sessionStorage.setItem('yourstory-return',next);
const $=s=>document.querySelector(s);let challenge=null,busy=false;
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Story-Anime':'local'},body:JSON.stringify(body)}:{});const x=await r.json();if(!r.ok)throw Error(x.error||'通信に失敗しました。');return x;}
async function run(task){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);$('#status').textContent='処理中…';try{await task();}catch(e){$('#status').textContent=e.message;}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
$('#google').onclick=()=>run(async()=>{const x=await api('/api/auth/google',{});location.assign(x.url);});
$('#email-form').onsubmit=e=>{e.preventDefault();run(async()=>{const x=await api('/api/auth/email/start',{email:$('#email').value});challenge=x.challenge;$('#code-form').hidden=false;$('#status').textContent=x.message+(x.dev_code?' 開発用コード: '+x.dev_code:'');$('#code').focus();});};
$('#code-form').onsubmit=e=>{e.preventDefault();run(async()=>{await api('/api/auth/email/finish',{challenge,code:$('#code').value});location.assign('/app');});};
run(async()=>{const x=await api('/api/account');if(x.account){location.replace('/app');return;}$('#google').hidden=!x.auth.google;$('#email-form').hidden=!(x.auth.email||x.auth.dev);$('#status').textContent=x.auth.google||x.auth.email||x.auth.dev?'':'ログインの接続設定を準備しています。';});
