'use strict';
let catalog={projects:[],layouts:{}}, project=null, section='home', target=null, busy=false;
const expanded=new Set();
const expandedSceneLists=new Map();
let accountState=null, loginChallenge=null, inspecting=null, lastChatRender=null, projectMenu=null, helpOpen=true;
const visualState=c=>c.visual_state||(c.approved?'confirmed':'interview');
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const file=p=>'/file/'+p.split('/').map(encodeURIComponent).join('/');
const image=(p,alt,cls='')=>`<img class="${cls}" src="${file(p)}" alt="${esc(alt)}" loading="lazy">`;
const icon=name=>YOURSTORY_ICONS[name]||'';
const actionIcons={'delete-project':'trash-2','create':'sparkles','open':'book-open','character-new':'plus','character':'user-round','scene':'panels-top-left','scene-new':'plus','quote-character':'image','quote-scene':'image','generate':'sparkles','world-save':'check','approve-character':'check','scene-confirm':'check','summary-save':'save','scene-export':'download','scene-fork':'git-branch','context':'messages-square'};
const btn=(label,op,attrs='',cls='')=>`<button data-op="${op}" ${attrs} class="${cls}">${icon(actionIcons[op])}<span class="button-label">${label}</span></button>`;
document.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Story-Anime':'local'},body:JSON.stringify(body)}:{});const x=await r.json();if(!r.ok){if(r.status===403&&x.error?.includes('ログイン'))location.assign('/login?next='+encodeURIComponent(location.pathname));throw Error(x.error||'通信できませんでした。');}return x;}
async function refresh(){[catalog,accountState]=await Promise.all([api('/api/projects'),api('/api/account')]);$('#account-nav').title=accountState.local?'設定・トークン使用量':'アカウントとプラン';$('#account-label').textContent=accountState.local?'設定':accountState.account?accountState.membership.limits.label+' · '+(accountState.account.display_name||'ユーザー名を登録'):'ログイン・プラン';tree();}
async function run(fn){if(busy)return;busy=true;$('#error').textContent='';document.querySelectorAll('button:not(.shell-control)').forEach(x=>x.disabled=true);$('#send').innerHTML=icon('loader-circle');window.dispatchEvent(new Event('yourstory:busy'));try{await fn();await refresh();render();}catch(e){$('#error').textContent=e.message;if(e.message.includes('ログイン'))section='account';if(project){try{project=await api('/api/work/'+project.id);}catch{} }try{await refresh();}catch{}render();}finally{busy=false;document.querySelectorAll('button').forEach(x=>x.disabled=false);$('#send').innerHTML=icon('arrow-up');window.dispatchEvent(new Event('yourstory:busy'));if(queuedNavigation){const next=queuedNavigation;queuedNavigation=null;navigate(next.url,next.replace);}}}
function heading(k,title,desc=''){return `<p class="eyebrow">${k}</p><h1>${esc(title)}</h1>${desc?`<p class="lead">${esc(desc)}</p>`:''}`;}
function assistantMessage(text){return `<div class="message assistant"><div class="markdown">${YourStoryMarkdown.render(text)}</div></div>`;}
function views(asset){return `<div class="views">${[['front','正面'],['side','横面'],['back','背面']].map(([k,t])=>`<figure>${asset?.[k]?image(asset[k],t):`<div class="placeholder">${t}</div>`}<figcaption>${t}</figcaption></figure>`).join('')}</div>`;}

function tree(){let html='';for(const p of catalog.projects){const active=project?.id===p.id;html+=`<div class="project-row">${btn(icon(expanded.has(p.id)?'chevron-down':'chevron-right'),'expand',`data-id="${p.id}" aria-label="漫画の階層を開閉" aria-expanded="${expanded.has(p.id)}"`)}${btn(esc(p.title),'expand',`data-id="${p.id}" aria-expanded="${expanded.has(p.id)}"`)}${btn(icon('ellipsis'),'project-menu',`data-id="${p.id}" aria-label="${esc(p.title)}のメニュー" aria-haspopup="true" aria-controls="project-dialog"`,'project-more')}</div>`;
 if(!expanded.has(p.id))continue;
 html+=`<a href="${YourStoryRouter.path({page:'studio',project:p.id})}" class="child ${active&&section==='studio'&&!inspecting?'selected':''}">${icon('messages-square')}制作チャット</a>`;
 if(active){
 if(project.world.text)html+=`<a class="child" href="${routeURL('world')}">${icon('globe')}世界観</a>`;
 for(const c of project.characters){const v=c.versions.find(v=>v.id===c.approved);if(v)html+=`<a class="child" href="${routeURL(c.id)}">${icon('user-round')}${esc(v.name)}</a>`;}
 const scenes=project.scenes.filter(s=>s.confirmed);
 if(scenes.length){const isOpen=expandedSceneLists.get(p.id)??scenes.some(s=>s.id===inspecting);
 html+=`<button class="child scene-group-toggle shell-control" data-op="toggle-scenes" data-id="${p.id}" aria-expanded="${isOpen}" aria-controls="completed-scenes-${p.id}">${icon(isOpen?'chevron-down':'chevron-right')}<span>完成したコマ</span><small>${scenes.length}シーン</small></button><div id="completed-scenes-${p.id}" class="completed-scenes" ${isOpen?'':'hidden'}>${scenes.map(s=>`<a class="child ${inspecting===s.id?'selected':''}" href="${routeURL(s.id)}" ${inspecting===s.id?'aria-current="page"':''}>${icon('panels-top-left')}<span>${esc(s.title)}</span></a>`).join('')}</div>`;
 }
 }}if($('#tree').innerHTML!==html)$('#tree').innerHTML=html;}
const usageExamples=[
 ['動画をダウンロード','完成したシーンを順番に、YouTube Shorts用の無音MP4にしてダウンロードしたい。','1コマずつ切り替わる無音動画です。'],
 ['画像をダウンロード','完成した漫画をPNGでダウンロードしたい。','縦読み画像やZIPでの書き出しも頼めます。'],
 ['コマを修正','1コマ目だけ表情を笑顔にして。他のコマはそのまま残して。','変えたいコマと内容を伝えます。'],
 ['セリフを変更','2コマ目のセリフを「ここから始めよう」に変えて。絵はそのままで。','絵を作り直さず文字を変更できます。'],
 ['続きをつくる','このシーンでOK。続きの4コマを一緒に考えて。','確定した設定や人物を引き継ぎます。'],
 ['キャラ・世界観を追加','主人公のライバルを追加したい。見た目と性格から相談しよう。','画風や世界観の変更も、このチャットで。']
];
function usageGuide(){return `<section class="asset-reader usage-guide" aria-label="使い方と例文"><div class="row"><h2>できること</h2>${btn('閉じる','toggle-help')}</div><p class="muted">例文を選ぶと入力欄に入ります。自由に直して送ってください。</p>${usageExamples.map(([title,prompt,note],i)=>`<section class="usage-example"><h3>${esc(title)}</h3><button type="button" data-op="use-example" data-index="${i}" ${busy?'disabled':''}>${esc(prompt)}</button><p class="muted">${esc(note)}</p></section>`).join('')}</section>`;}

const sceneSlideIndex=new Map();
let followChatBottom=false;
function scrollChatBottom(){requestAnimationFrame(()=>{if(!followChatBottom)return;window.scrollTo(0,document.documentElement.scrollHeight);requestAnimationFrame(()=>{if(followChatBottom)window.scrollTo(0,document.documentElement.scrollHeight);});});}
function pinChatBottom(){followChatBottom=true;scrollChatBottom();}
new ResizeObserver(()=>{if(followChatBottom)scrollChatBottom();}).observe(document.querySelector('#content'));
window.addEventListener('wheel',()=>{followChatBottom=false;},{passive:true});
window.addEventListener('touchstart',()=>{followChatBottom=false;},{passive:true});
document.addEventListener('keydown',e=>{if(['PageUp','Home','ArrowUp'].includes(e.key))followChatBottom=false;});
document.addEventListener('load',e=>{if(followChatBottom&&e.target.matches?.('.conversation img'))scrollChatBottom();},true);
function sceneSlideshow(scene){
 const panels=scene.panels.map((p,i)=>({path:p.asset?.file,label:`${i+1}コマ目`})).filter(p=>p.path);
 if(!panels.length)return scene.output?image(scene.output,scene.title,'page'):'';
 const index=Math.min(sceneSlideIndex.get(scene.id)||0,panels.length-1),slide=panels[index];
 return `<div class="scene-slideshow" aria-label="完成したコマのスライド"><div class="slide-image">${image(slide.path,slide.label,'page')}</div><div class="slide-controls">${panels.length>1?`<button type="button" class="shell-control" data-op="scene-slide" data-step="-1" aria-label="前のコマ">←</button>`:''}<span aria-live="polite">${slide.label} · ${index+1} / ${panels.length}</span>${panels.length>1?`<button type="button" class="shell-control" data-op="scene-slide" data-step="1" aria-label="次のコマ">→</button>`:''}</div><a href="${file(slide.path)}" download="panel-${index+1}.png">${icon('download')}このコマを保存</a></div>`;
}

function renderConfirmation(message){const c=message.confirmation;if(!c)return '';if(c.status==='accepted')return '<p class="muted">確定済み</p>';if(c.status!=='pending')return '';return `<div class="confirmation-actions">${btn(c.label,'confirm-proposal',`data-message="${esc(message.id)}"`,'primary')}</div>`;}

function assetReader(){if(!inspecting)return '';let title,html;
 if(inspecting==='world'){title='世界観';html=`<p class="text-block">${esc(project.world.text)}</p><small>確定版 v${project.world.revision}</small>`;}
 else {const c=project.characters.find(c=>c.id===inspecting), scene=project.scenes.find(s=>s.id===inspecting);
 if(c){const v=c.versions.find(v=>v.id===c.approved);if(!v)return '';title=v.name;html=views(v.asset)+`<p class="text-block">${esc(v.description)}</p>`;}
 else if(scene?.confirmed){title=scene.title;html=sceneSlideshow(scene)+renderDownloads((project.exports||[]).filter(e=>e.scenes.includes(scene.id)).flatMap(e=>e.files))+`<p class="text-block">${esc(scene.summary)}</p>`;}
 else return '';}
 return `<section class="asset-reader" aria-label="確定した設定と素材"><div class="row"><h2>${esc(title)}</h2>${btn('閉じる','close-reader')}</div>${html}<p class="muted">修正や追加は、制作チャットで話しかけてください。確定するまで元の設定は残ります。</p></section>`;}
function draftCard(context){if(project.chat_engine==='tools-v1')return '';if(context==='world')return project.world_draft&&project.world_draft!==project.world.text&&!project.chats.some(x=>(x.artifacts||[]).some(a=>a.kind==='world'&&a.text===project.world_draft))&&!project.chats.some(x=>x.proposal?.kind==='world'&&x.proposal.text===project.world_draft)?`<div class="card"><h3>${project.world_ready?'世界観の案':'世界観の下書き'}</h3><p>${esc(project.world_draft)}</p><p class="muted">これまで話した内容です。追加・変更したいことも、このチャットで教えてください。</p></div>`:'';
 const c=project.characters.find(c=>c.id===context);
 if(c){const stage=visualState(c);let html='';
 if(c.asset&&stage!=='confirmed')html+=`<div class="card"><h3>${esc(c.name)}の三面図</h3>${views(c.asset)}<p>見た目や名前について、OKか変更したい点を教えてください。</p></div>`;
 else if(!c.asset&&stage==='ready')html+=`<div class="card"><h3>見た目の案</h3><p>${esc(c.appearance||c.description)}</p>${c.view_assets&&Object.keys(c.view_assets).length?views(Object.fromEntries(Object.entries(c.view_assets).map(([k,v])=>[k,v.file])))+'<p>生成済みの向きは保存しました。残りの向きだけ生成できます。</p>':''}</div>`;
 if(stage==='confirmed'&&c.persona_state==='ready')html+=`<div class="card"><h3>${esc(c.name)}の性格・話し方の案</h3><p>${esc(c.personality)}</p><p>${esc(c.speech)}</p><p class="muted">この案でOKか、変えたい点を教えてください。</p></div>`;
 return html;}
 const s=project.scenes.find(s=>s.id===context);if(!s||s.confirmed)return '';
 return `<div class="card"><h3>${esc(s.title)} · ${esc(catalog.layouts[s.layout])}</h3><p>${s.characters.map(c=>esc(c.name)).join(' / ')}</p><div class="grid">${s.panels.map((p,i)=>`<div class="panel"><h3>${i+1}コマ目</h3>${p.asset?image(p.asset.file,`${i+1}コマ目`):''}<p>${esc(p.direction)}</p>${(p.bubbles||[p]).map(b=>`<p>${esc(s.characters[b.speaker].name)}「${esc(b.text)}」</p>`).join('')}${p.held?'<p>保持中</p>':''}</div>`).join('')}</div><p>${esc(s.summary)}</p>${s.output?image(s.output,s.title,'page')+'<p>このページでOKか、変えたい点を教えてください。</p>':''}</div>`;
}
function render(){document.body.classList.remove('character-screen');document.body.classList.toggle('inspect-open',(!!inspecting||helpOpen)&&!!project&&section!=='account');tree();$('#composer').hidden=true;$('#help-toggle').hidden=!project||section==='account';$('#help-toggle').setAttribute('aria-expanded',String(helpOpen&&!inspecting));
 if(!accountState?.local&&accountState?.account&&accountState.account.consent_required&&section!=='account'){renderConsentSetup();return;}
 if(!accountState?.local&&accountState?.account&&!accountState.account.display_name){renderProfileSetup();return;}
 if(routeError){$('#breadcrumb').textContent='YourStory';$('#content').innerHTML=heading('YOUR STORY',routeError)+'<a href="/app">アトリエへ戻る</a>';return;}
 if(section==='account'){renderAccount();return;}
 if(!project){$('#breadcrumb').textContent='YourStory / アトリエ';$('#content').innerHTML=heading('YOUR STORY STARTS HERE','どんな漫画をつくりましょう？','世界観も、登場人物も、物語も。一つのチャットから。')+`<label>漫画のタイトル<input id="new-title" class="field" maxlength="80" placeholder="仮のタイトルでも大丈夫"></label>${btn('漫画をはじめる','create','','primary')}`;return;}
 section='studio';const context=project.active_context||project.chats.at(-1)?.context||'world';target=context;
 $('#breadcrumb').textContent=project.title+' / 制作チャット';
 const entries=project.chats.map(x=>`<div class="message user">${esc(x.text)}</div>${assistantMessage(x.reply)}${renderConfirmation(x)}${(x.artifacts||[]).map(a=>renderArtifact(a,x.narrative)).join('')}${x.proposal?.kind==='world'?assistantMessage(x.proposal.text):''}${(x.images||[]).map(p=>image(p,'生成した画像','chat-image')).join('')}`).join('');
 $('#content').innerHTML=(inspecting?assetReader():helpOpen?usageGuide():'')+`<div class="conversation" role="log" aria-label="漫画の制作チャット">${assistantMessage('どんな世界で、どんな物語を描きたいですか？思いつくところから話してください。決まった設定や画像は保存していきます。')}${entries}</div>`+draftCard(context);
 $('#composer').hidden=false;$('#composer').dataset.context='studio';
 if(accountState?.membership.plan==='free'&&!accountState.gemini_key?.configured){$('#composer').hidden=true;$('#content').insertAdjacentHTML('beforeend','<div class="card"><p>制作するには、ご自身のGemini APIキーを登録してください。</p><a href="/app/account">アカウント設定でキーを登録</a></div>');}
 const stamp=project.id+':'+(project.chats.at(-1)?.id||'')+':'+(inspecting||'')+':'+helpOpen;if(lastChatRender!==stamp){lastChatRender=stamp;pinChatBottom();}
 if(project.error)$('#error').textContent=project.error;
}
async function edit(op,extra={}){project=await api('/api/project/edit',{id:project.id,revision:project.revision,op,...extra});}
async function open(id,sec='studio'){project=await api('/api/work/'+id);expanded.add(id);section=sec;target=null;inspecting=null;}
document.addEventListener('click',e=>{const b=e.target.closest('[data-op]');if(!b)return;const op=b.dataset.op;
 if(op==='scene-slide'){const scene=project?.scenes.find(s=>s.id===inspecting);if(!scene)return;const count=scene.panels.filter(p=>p.asset).length;if(count<2)return;sceneSlideIndex.set(scene.id,((sceneSlideIndex.get(scene.id)||0)+Number(b.dataset.step)+count)%count);document.querySelector('.asset-reader').outerHTML=assetReader();document.querySelector(`[data-op="scene-slide"][data-step="${b.dataset.step}"]`)?.focus({preventScroll:true});return;}
 if(op==='toggle-help'){helpOpen=!helpOpen;if(inspecting){helpOpen=true;navigate(routeURL(null));}else render();return;}
 if(op==='use-example'){if(busy)return;const example=usageExamples[Number(b.dataset.index)];if(!example)return;const input=$('#input');input.value=(input.value.trim()?input.value.trim()+'\n':'')+example[1];input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();return;}
 if(op==='toggle-scenes'){expandedSceneLists.set(b.dataset.id,b.getAttribute('aria-expanded')!=='true');tree();document.querySelector('[data-op="toggle-scenes"][data-id="'+b.dataset.id+'"]')?.focus();return;}
 if(op==='choose-format'){if(busy)return;const f=(catalog.publication_formats||[]).find(x=>x.id===b.dataset.id);if(!f)return;const input=$('#input');input.value=(input.value.trim()?input.value.trim()+'\n':'')+'掲載形式は「'+f.label+'」を希望します。';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();return;}
 if(op==='choose-style'){if(busy)return;const style=(catalog.styles||[]).find(s=>s.id===b.dataset.id);if(!style)return;const input=$('#input');input.value=(input.value.trim()?input.value.trim()+'\n':'')+'絵のテイストは「'+style.label+'」を選びます。';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();return;}
 if(op==='project-menu'){if(busy)return;const menu=$('#project-dialog');if(menu.matches(':popover-open')){const same=projectMenu===b.dataset.id;menu.hidePopover();if(same)return;}projectMenu=b.dataset.id;$('#project-dialog-actions').innerHTML=btn('削除','delete-project',`data-id="${projectMenu}"`,'danger');menu.showPopover();const r=b.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(r.right-menu.offsetWidth,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(r.bottom+6,innerHeight-menu.offsetHeight-8))+'px';return;}

 if(['account','nav','inspect','close-reader'].includes(op)){navigate(op==='account'?'/app/account':op==='nav'?YourStoryRouter.path({page:'studio',project:b.dataset.id}):routeURL(op==='inspect'?b.dataset.target:null));return;}
 if(op==='expand'){expanded.has(b.dataset.id)?expanded.delete(b.dataset.id):expanded.add(b.dataset.id);tree();return;}
 run(async()=>{switch(op){
 case 'confirm-proposal':project=await api('/api/project/confirm',{id:project.id,revision:project.revision,message_id:b.dataset.message});break;
 case 'delete-project':{const id=b.dataset.id;$('#project-dialog').hidePopover();const work=project?.id===id?project:await api('/api/work/'+id);await api('/api/project/delete',{id,revision:work.revision});expanded.delete(id);projectMenu=null;if(project?.id===id){project=null;inspecting=null;target=null;section='studio';writeURL('/app/new',true);}break;}
 case 'inspect':inspecting=b.dataset.target;section='studio';break;
 case 'close-reader':inspecting=null;break;
 case 'account':section='account';break;
 case 'checkout':{const r=await api('/api/billing/checkout',{plan:b.dataset.plan||$('#join-plan')?.value});window.location.assign(r.url);break;}
 case 'portal':{const r=await api('/api/billing/portal',{});window.location.assign(r.url);break;}
 case 'login-send':loginChallenge=await api('/api/auth/email/start',{email:$('#login-email').value});break;
 case 'login-verify':await api('/api/auth/email/finish',{challenge:loginChallenge.challenge,code:$('#login-code').value});loginChallenge=null;project=null;await refresh();if(catalog.projects.length)await open(catalog.projects[0].id);break;
 case 'google-login':{const r=await api('/api/auth/google',{});window.location.assign(r.url);break;}
 case 'delete-gemini-key':await api('/api/account/gemini-key',{delete:true});break;
 case 'logout':await api('/api/auth/logout',{});location.assign('/login');return;
 case 'create':project=await api('/api/project/new',{title:$('#new-title').value});expanded.add(project.id);section='studio';inspecting=null;$('#input').value='';writeURL(routeURL());break;
 case 'nav':await open(b.dataset.id);break;
 }if(op==='account')window.scrollTo(0,0);});});
document.addEventListener('change',e=>{if(e.target.dataset.hold!==undefined)run(()=>edit('panel_hold',{target,panel:Number(e.target.dataset.hold),held:e.target.checked}));});
$('#new-project').onclick=()=>navigate('/app/new');
$('#composer').onsubmit=submitChat;

run(async()=>{await refresh();const resume=sessionStorage.getItem('yourstory-return');sessionStorage.removeItem('yourstory-return');await applyRoute(location.pathname==='/app'&&resume&&YourStoryRouter.parse(resume).page!=='missing'?resume:location.pathname+location.search,true);});

setInterval(()=>{if(!busy&&project?.busy)run(async()=>{project=await api('/api/work/'+project.id);});},3000);

function profileForm(initial=false){return `<form id="profile-form" class="card"><h2>${initial?'あなたを何と呼びましょう？':'ユーザー名'}</h2><p>${initial?'YourStoryで使う名前を教えてください。あとから変更できます。':''}</p><p class="muted">ログイン中: ${esc(accountState.account.email)}</p><label for="display-name">ユーザー名</label><input id="display-name" class="field" name="display_name" required maxlength="30" autocomplete="nickname" value="${esc(accountState.account.display_name)}" placeholder="漫画づくりで使いたい名前"><button class="primary" type="submit">${initial?'この名前ではじめる':'名前を保存'}</button></form>`;}
function renderProfileSetup(){
 $('#composer').hidden=true;$('#breadcrumb').textContent='YourStory / はじめまして';
 $('#content').innerHTML=heading('WELCOME','YourStoryへようこそ')+profileForm(true)+btn('ログアウト','logout');
}
function renderConsentSetup(){
 if(catalog?.local){
  $('#composer').hidden=true;$('#breadcrumb').textContent='YourStory / はじめに';
  $('#content').innerHTML=heading('WELCOME','データの保存とAPI利用について','自分のPCで漫画を作るローカル版です。')+`<form id="consent-form" class="card"><p>作品はこのPCに保存されます。生成時には文章・参照画像をGoogleへ送信し、ご自身のAPIキーに利用料金が発生します。</p><p><a href="/privacy" target="_blank" rel="noopener">保存・送信の詳細</a></p><label><input type="checkbox" id="consent-accepted" required> この案内を確認しました</label><button type="submit" class="primary">始める</button></form>`;
  return;
 }

 $('#composer').hidden=true;$('#breadcrumb').textContent='YourStory / ご利用開始';
 $('#content').innerHTML=heading('WELCOME','利用規約をご確認ください','YourStoryを利用する前に、現在の規約とプライバシーポリシーをご確認ください。')+`<form id="consent-form" class="card consent-card"><p>作品の生成・保存を始めるには、以下への同意が必要です。</p><label class="check-row"><input type="checkbox" id="consent-accepted" required> <span><a href="/terms" target="_blank" rel="noopener">利用規約</a>と<a href="/privacy" target="_blank" rel="noopener">プライバシーポリシー</a>を読み、内容に同意します。</span></label><button class="primary" type="submit">同意して始める</button></form>`+btn('ログアウト','logout');
}
document.addEventListener('submit',e=>{
 if(e.target.id==='gemini-key-form'){e.preventDefault();const key=$('#gemini-api-key').value;$('#gemini-api-key').value='';run(async()=>{await api('/api/account/gemini-key',{key});});return;}
 if(e.target.id==='profile-form'){e.preventDefault();run(async()=>{await api('/api/account/profile',{display_name:$('#display-name').value});});return;}
 if(e.target.id==='consent-form'){e.preventDefault();run(async()=>{await api('/api/account/consent',{accepted:$('#consent-accepted').checked});});return;}
 if(e.target.id==='delete-account-form'){e.preventDefault();if(!$('#delete-confirm').checked){$('#error').textContent='削除への同意を確認してください。';return;}if(!window.confirm('アカウントを削除します。続けますか？'))return;run(async()=>{await api('/api/account/delete',{confirmed:true});location.assign('/login');});}
});
function renderLocalSettings(a){
 document.title='設定 | YourStory';
 const u=a.token_usage,n=v=>v==null?'未取得':Number(v).toLocaleString('ja-JP');
 $('#breadcrumb').textContent='設定';
 $('#content').innerHTML=heading('SETTINGS','設定','APIキーと使用したトークン数を確認できます。')+geminiKeyForm(a)+`<section class="card"><h2>使用したトークン</h2><p>入力：${n(u.input_tokens)} ／ 出力：${n(u.output_tokens)} ／ 合計：${n(u.total_tokens)}</p><p class="muted">このPCに記録された全期間の実測値です。出力には思考トークンを含みます。取得できなかった使用量や処理中の見込みは合計に含めません。</p>${u.unreported_calls?`<p>使用量未取得・処理中：${n(u.unreported_calls)}件</p>`:''}<h3>利用履歴（最新100件）</h3>${u.records.length?u.records.map(r=>`<article class="card"><strong>${r.kind==='image'?'画像生成':'会話'}</strong><p>${esc(new Date(r.created*1000).toLocaleString('ja-JP'))} · ${esc(r.model||'モデル不明')}</p><p>入力：${n(r.input_tokens)} ／ 出力：${n(r.output_tokens)} ／ 合計：${n(r.total_tokens)}</p>${r.total_tokens==null?`<p class="muted">${r.status==='reserved'?'処理中':'APIから使用量を取得できませんでした。'}</p>`:''}</article>`).join(''):'<p>まだ利用履歴はありません。</p>'}</section>`;
}

function renderAccount(){
 $('#composer').hidden=true;$('#breadcrumb').textContent=catalog?.local?'設定':'アカウント / プランと利用状況';
 const a=accountState;if(!a){$('#content').innerHTML='<p>読み込み中…</p>';return;}
 if(a.local){renderLocalSettings(a);return;}
 const m=a.membership;
 let html=heading('ACCOUNT',catalog?.local?'設定':'アカウントとプラン','表示名と、制作に使うAPIキーを確認・変更できます。');
 if(a.account?.consent_required)html+='<div class="card"><p>FreeのAPIキー方式への変更に伴い、利用規約・プライバシーポリシーを更新しました。制作を続ける前にご確認ください。</p><a href="/app">変更内容を確認して利用を再開</a></div>';
 if(!a.account){html+=`<div class="card"><h2>ログイン</h2><p>メール認証またはGoogleでログインできます。</p>${a.auth.google?btn('Googleでログイン','google-login'):'<p class="muted">Googleログインは接続設定待ちです。</p>'}${a.auth.email||a.auth.dev?`<label>メールアドレス<input type="email" id="login-email" class="field" autocomplete="email" placeholder="${a.auth.dev&&!a.auth.email?'creator@example.test':'you@example.com'}"></label>${btn('認証コードを送信','login-send','','primary')}`:'<p class="muted">メール配信は接続設定待ちです。</p>'}${a.auth.dev?'<p class="dev-notice">開発用認証が有効です。@example.test のみメールを送らず確認できます。実メールの本人確認ではありません。</p>':''}${loginChallenge?`<p>${esc(loginChallenge.message)}</p>${loginChallenge.dev_code?`<p class="dev-notice">開発用コード: <strong>${esc(loginChallenge.dev_code)}</strong></p>`:''}<label>6桁の認証コード<input id="login-code" class="field" inputmode="numeric" autocomplete="one-time-code" maxlength="6"></label>${btn('ログインする','login-verify','','primary')}`:''}</div>`;}
 else html+=profileForm()+`<div class="card row"><div><strong>${esc(a.account.display_name)}</strong><p>${esc(a.account.email)}</p><p>${a.account.verified?'認証済み':'開発用アカウント（メール未検証）'} · ${esc(m.limits.label)}</p></div>${catalog?.local?'':btn('ログアウト','logout')}</div>`;
 if(!catalog?.local&&a.account&&(!a.billing?.subscription||['canceled','incomplete_expired'].includes(a.billing.subscription.status))){
  html+=`<div class="card"><a href="/#plans">プラン・料金を見る</a>${a.billing?.enabled?`<p>現在はテスト決済です。実際のお支払いは発生しません。</p><label>加入するプラン<select id="join-plan" class="field"><option value="plus">Plus</option><option value="pro">Pro</option></select></label>${btn('選んだプランで手続きへ','checkout')}`:'<p>有料プランの申込は準備中です。</p>'}</div>`;
 }
 if(a.billing?.enabled)html+=`<div class="card"><h3>契約・決済の確認</h3><small>現在はテスト決済です。実際のお支払いは発生しません。</small><p>${subscriptionLabel(a.billing.subscription,m)}</p>${a.billing.subscription?'<p>ダウングレードは次回更新日に反映し、それまでは現在のプランをご利用いただけます。途中の減額・返金はありません。アップグレードは変更日から新しい1か月が始まり、新プランの月額から旧プランの残期間分を差し引いて請求します。決済完了後に利用枠が切り替わります。</p>'+btn('プラン変更・契約管理','portal'):''}<p><a href="/commerce">取引条件</a> · <a href="/terms">利用規約</a> · <a href="/privacy">プライバシー</a> · <a href="/support">お問い合わせ</a></p></div>`;
 if(m.plan==='free')html+=`<div class="card"><h2>APIの利用について</h2><p>YourStoryの利用料は0円です。会話・画像生成にはご自身のGemini APIキーを使用します。YourStoryから無料の生成枠は付与しません。</p><p>Gemini APIの料金と上限はご自身のGoogleプロジェクトに適用されます。<a href="https://aistudio.google.com/usage" target="_blank" rel="noopener">Google AI Studioで利用状況を確認</a></p></div>`;
 else html+=`<div class="card"><h2>今月の利用状況</h2><div class="usage-row"><div class="row"><span>月間利用枠</span><strong>${m.usage_percent.toFixed(1)}% 使用</strong></div><progress max="100" value="${m.usage_percent}" aria-label="月間利用枠の使用率">${m.usage_percent}%</progress></div><p class="muted">次のリセット日：${dateLabel(m.resets_at)}<br>会話と画像生成の利用量をまとめて表示しています。生成中の利用見込みも含みます。</p></div>`;
 if(a.account)html+=geminiKeyForm(a);
 if(a.account&&!catalog?.local)html+=`<div class="card danger-card"><h2>アカウント削除</h2><p>アカウントを削除すると、このアカウントでログインできなくなり、保存した漫画・キャラクター・世界観・会話履歴を閲覧・編集・ダウンロードできなくなります。ユーザーによる復元はできません。必要な作品は削除前にダウンロードしてください。</p><p>登録情報・作品・会話・利用履歴・決済記録などは、その場ですべて物理消去されるわけではありません。問い合わせ、請求・返金、紛争対応、不正利用防止、法令上の義務への対応に必要な範囲で、アクセスを制限して保管する場合があります。有料プランは先に契約管理から解約してください。アカウント削除だけで返金が発生するものではありません。</p><form id="delete-account-form"><label class="check-row"><input id="delete-confirm" type="checkbox" required> <span>上記を確認し、作品を利用できなくなること、ユーザーによる復元ができないこと、および必要な記録が保管される場合があることを理解して、アカウント削除を申し込みます。</span></label><button type="submit" class="danger">アカウントを削除する</button></form></div>`;
 $('#content').innerHTML=html;
}

document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!busy&&section==='account'&&!document.querySelector('dialog[open]'))run(async()=>{await refresh();});});

$('#project-dialog').addEventListener('toggle',e=>{if(e.newState==='closed')projectMenu=null;});
window.addEventListener('resize',()=>$('#project-dialog').hidePopover());

function dateLabel(seconds){return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(seconds*1000));}
function subscriptionLabel(sub,m){
 if(!sub)return '有料プランは未契約です。';
 const name=esc(m.plans[sub.plan]?.label||'有料');
 if(sub.status==='active')return `${name}プランを契約中、${sub.cancel_pending?dateLabel(sub.period_end)+'で解約予定':'次の更新日は'+dateLabel(sub.period_end)}`;
 if(sub.status==='canceled')return `${name}プランは解約済みです。`;
 if(['past_due','unpaid'].includes(sub.status))return 'お支払いを確認できていません。契約管理からご確認ください。';
 return '契約手続きの完了を確認しています。';
}

function renderArtifact(a,narrative=false){if(a.kind==='publication_formats')return renderPublicationFormats();if(a.kind==='downloads')return renderDownloads(a.files);if(a.kind==='style_samples')return renderStyleSamples();const images=(a.images||[]).map(p=>image(p,'漫画の画像','page')).join('');if(a.kind==='quote'||narrative)return images;return assistantMessage(a.text+(a.panels||[]).map((p,i)=>`\n\n${i+1}コマ目：${p.direction}\n「${p.text}」`).join(''))+images;}

function renderStyleSamples(){return `<section class="style-samples" aria-label="絵のテイスト見本"><div class="style-sample-grid">${(catalog.styles||[]).map(s=>`<button class="style-sample" data-op="choose-style" data-id="${esc(s.id)}" ${busy?'disabled':''}><img src="${esc(s.image)}" alt="${esc(s.label)}の作画見本" loading="lazy" width="1280" height="720"><strong>${esc(s.label)}</strong><span>${esc(s.description)}</span></button>`).join('')}</div><p class="muted">同じ人物・場面を描いた見本です。選んでから調整したり、候補にないテイストを文章で指定したりできます。</p></section>`;}

function renderDownloads(files){return `<div class="export-downloads">${(files||[]).map(f=>`<a href="${file(f.path)}" download>${icon('download')}${esc(f.label)}</a>`).join('')}</div>`;}
function renderPublicationFormats(){return `<section aria-label="掲載形式の見本" class="publication-formats">${(catalog.publication_formats||[]).map(f=>`<button class="format-choice" data-op="choose-format" data-id="${esc(f.id)}" ${busy?'disabled':''}><span class="format-preview format-${esc(f.id)}" aria-hidden="true">${Array.from({length:f.id==='page-two'?2:4},(_,i)=>`<span>${i+1}</span>`).join('')}</span><strong>${esc(f.label)}</strong><span>${esc(f.description)}</span></button>`).join('')}<p class="muted">用途が未定でも大丈夫です。掲載先や希望を話して、生成前に形を決めましょう。</p></section>`;}

function geminiKeyForm(a){const configured=a.gemini_key?.configured;return `<section class="card" aria-label="Gemini APIキー設定"><h2>Gemini APIキー</h2><p>${configured?'登録済みです。安全のためキーは表示しません。':'未登録です。制作を始める前に登録してください。'}</p>${a.membership.plan!=='free'?'<p>現在の有料プランではプランの利用枠を使用し、このキーは使用しません。</p>':''}<p><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI StudioでAPIキーを取得</a>し、Gemini APIを利用できるキーを入力してください。会話・画像モデルの利用には、Google側の請求設定が必要な場合があります。</p><p>キーは暗号化して保存し、あなたの制作リクエストをGoogleへ送るために使用します。Gemini APIの利用料金はご自身のGoogle側で発生します。保存時はモデルへのアクセスを確認し、生成は行いません。</p><form id="gemini-key-form" autocomplete="off"><label for="gemini-api-key">${configured?'新しいGemini APIキー':'Gemini APIキー'}</label><input id="gemini-api-key" class="field" type="password" autocomplete="new-password" spellcheck="false" required minlength="20" maxlength="2048" placeholder="APIキーを入力"><button class="primary" type="submit">${configured?'キーを確認して更新':'キーを確認して保存'}</button></form>${configured?btn('登録したキーを削除','delete-gemini-key'):''}<p class="muted">削除後の新しい生成は停止します。送信済みの処理は取り消せません。キーを無効にする場合はGoogle AI Studioでも削除してください。</p></section>`;}
