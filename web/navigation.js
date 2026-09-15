/* Persistent app shell: URLs control the view; creative state stays on the server. */
let routeError=null, queuedNavigation=null;
const chatDrafts=new Map();
function routeURL(material=inspecting){return YourStoryRouter.path({page:'studio',project:project.id,material});}
function rememberDraft(){if(project)chatDrafts.set(project.id,$('#input').value);}
function writeURL(url,replace=false){if(location.pathname+location.search!==url)history[replace?'replaceState':'pushState']({},'',url);}
async function applyRoute(url,replace=false){
 window.dispatchEvent(new Event('yourstory:before-navigate'));
 rememberDraft();routeError=null;$('#project-dialog').hidePopover();
 const parsedURL=new URL(url,location.origin);let route=YourStoryRouter.parse(parsedURL.pathname);
 if(parsedURL.searchParams.has('billing')||parsedURL.searchParams.has('plan'))route={page:'account'};
 if(route.page==='home')route=catalog.projects.length?{page:'studio',project:catalog.projects[0].id}:{page:'new'};
 if(route.page==='account'){section='account';inspecting=null;}
 else if(route.page==='new'){section='studio';project=null;inspecting=null;}
 else if(route.page==='studio'){
  try{
   const next=await api('/api/work/'+route.project);
   if(next.version!==4)throw Error('この漫画は旧形式です。');
   const material=route.material;
   if(material && !(material==='world'&&next.world.text) && !next.characters.some(c=>c.id===material&&c.approved) && !next.scenes.some(s=>s.id===material&&s.confirmed))throw Error('この設定・素材は見つかりません。');
   project=next;section='studio';inspecting=material;expanded.add(project.id);
  }catch(error){project=null;inspecting=null;section='missing';routeError='ページを開けません。削除済み、または閲覧できない漫画・素材です。';}
 }else{project=null;inspecting=null;section='missing';routeError='ページが見つかりません。';}
 $('#input').value=project?(chatDrafts.get(project.id)||''):'';
 writeURL(route.page==='missing'?parsedURL.pathname:YourStoryRouter.path(route),replace);
 document.title=section==='account'?'アカウント | YourStory':project?project.title+' | YourStory':'YourStory — 漫画のアトリエ';
 window.dispatchEvent(new Event('yourstory:navigate'));
 window.scrollTo(0,0);
}
function navigate(url,replace=false){
 if(busy){queuedNavigation={url,replace};return;}
 run(()=>applyRoute(url,replace));
}
window.addEventListener('popstate',()=>navigate(location.pathname+location.search,true));
document.addEventListener('click',e=>{
 const a=e.target.closest('a[href]');if(!a||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target||a.hasAttribute('download'))return;
 const url=new URL(a.href,location.origin);if(url.origin!==location.origin||!/^\/app(?:\/|$)/.test(url.pathname))return;
 e.preventDefault();navigate(url.pathname+url.search);
});
