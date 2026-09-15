/* Real SSE transport; optimistic messages remain visible while the server works. */
async function submitChat(e){
 e.preventDefault();const text=$('#input').value.trim();if(!text||busy||!project)return;
 const workId=project.id,revision=project.revision,viewing=inspecting;
 const log=$('.conversation'),pending=document.createElement('div');pending.className='pending-turn';
 const user=document.createElement('div');user.className='message user';user.textContent=text;
 const answer=document.createElement('div');answer.className='message assistant streaming';answer.textContent='返答を考えています…';
 pending.append(user,answer);log.append(pending);$('#input').value='';chatDrafts.set(workId,'');$('#input').dispatchEvent(new Event('input',{bubbles:true}));
 window.scrollTo(0,document.documentElement.scrollHeight);
 busy=true;window.dispatchEvent(new Event('yourstory:busy'));
 let completed=false;
 try{
  const response=await fetch('/api/project/chat/stream',{method:'POST',headers:{'Content-Type':'application/json','X-Story-Anime':'local'},body:JSON.stringify({id:workId,revision,context:'studio',viewing,text})});
  if(!response.ok){const error=await response.json();throw Error(error.error||'送信できませんでした。');}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
   let boundary;
   while((boundary=buffer.indexOf('\n\n'))>=0){
    const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const event=frame.match(/^event: (.+)$/m)?.[1];const raw=frame.split('\n').filter(l=>l.startsWith('data: ')).map(l=>l.slice(6)).join('\n');if(!raw)continue;
    const data=JSON.parse(raw);
    if(event==='error')throw Error(data.error);
    if(event==='reply'&&data.text){const follow=innerHeight+scrollY>=document.documentElement.scrollHeight-160;answer.innerHTML='<div class="markdown">'+YourStoryMarkdown.render(data.text)+'</div>';if(follow)window.scrollTo(0,document.documentElement.scrollHeight);}
    if(event==='done'){project=data;completed=true;}
   }
   if(done)break;
  }
  if(!completed)throw Error('接続が途切れました。処理が保存されている可能性があります。再送する前に作品を開き直して確認してください。');
  render();try{await refresh();}catch{} // A saved turn must not become a failed turn due to an account refresh.
 }catch(error){
  answer.classList.remove('streaming');answer.textContent='返答を完了できませんでした。'+error.message;pending.classList.add('failed-turn');
  $('#error').textContent='自動再送はしていません。入力した文章はこの画面に残しています。';
 }finally{busy=false;window.dispatchEvent(new Event('yourstory:busy'));if(queuedNavigation){const next=queuedNavigation;queuedNavigation=null;navigate(next.url,next.replace);}}
}

// Keep Enter for newlines and IME confirmation; submit only explicit shortcuts.
document.addEventListener('keydown',e=>{
 if(e.target.id!=='input'||e.key!=='Enter'||!(e.metaKey||e.ctrlKey)||e.altKey||e.shiftKey||e.isComposing||e.keyCode===229||e.repeat)return;
 e.preventDefault();const button=document.querySelector('#send');if(!button.disabled)document.querySelector('#composer').requestSubmit(button);
});
