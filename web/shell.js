/* Responsive shell owns presentation only; it never calls a generation API. */
(()=>{
 const body=document.body, sidebar=document.querySelector('#sidebar'), main=document.querySelector('main');
 const toggle=document.querySelector('#sidebar-toggle'), close=document.querySelector('#sidebar-close'), backdrop=document.querySelector('#sidebar-backdrop');
 const compact=matchMedia('(max-width: 960px)');
 let opened=false, scrollY=0;
 const focusables=()=>[...sidebar.querySelectorAll('a[href],button:not(:disabled)')].filter(el=>el.getClientRects().length);
 function setOpen(value,restore=true){
  const wasOpen=opened;opened=value&&compact.matches;
  body.classList.toggle('sidebar-open',opened);toggle.setAttribute('aria-expanded',String(opened));
  sidebar.inert=compact.matches&&!opened;main.inert=opened;backdrop.hidden=!opened;
  if(opened){sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-modal','true');if(!wasOpen){scrollY=window.scrollY;body.style.top=`-${scrollY}px`;requestAnimationFrame(()=>{if(opened){sidebar.getBoundingClientRect();close.focus({preventScroll:true});}});}}
  else{sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');body.style.top='';if(wasOpen){window.scrollTo(0,scrollY);if(restore)toggle.focus();}}
 }
 toggle.onclick=()=>setOpen(!opened);close.onclick=()=>setOpen(false);backdrop.onclick=()=>setOpen(false);
 document.addEventListener('keydown',e=>{
  if(!opened)return;
  if(e.key==='Escape'){e.preventDefault();setOpen(false);}
  if(e.key==='Tab'){const els=focusables(),first=els[0],last=els.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}
 });
 sidebar.addEventListener('transitionend',()=>{if(opened&&!sidebar.contains(document.activeElement))close.focus({preventScroll:true});});
 compact.addEventListener('change',()=>setOpen(false,false));setOpen(false,false);
 window.addEventListener('yourstory:navigate',()=>{setOpen(false,false);requestAnimationFrame(()=>document.querySelector('#content').focus({preventScroll:true}));});
 const input=document.querySelector('#input'),composer=document.querySelector('#composer');
 function sizeInput(){input.style.height='auto';input.style.height=Math.min(180,Math.max(48,input.scrollHeight))+'px';}
 function measure(){body.style.setProperty('--composer-height',composer.hidden?'0px':`${composer.getBoundingClientRect().height}px`);}
 input.addEventListener('input',sizeInput);
 new ResizeObserver(measure).observe(composer);
 new MutationObserver(()=>{sizeInput();measure();}).observe(composer,{attributes:true,attributeFilter:['hidden']});
 window.addEventListener('yourstory:navigate',()=>requestAnimationFrame(sizeInput));
 function viewport(){const v=window.visualViewport;const editing=document.activeElement===input;const inset=v&&v.scale===1?Math.max(0,innerHeight-v.height-v.offsetTop):0;body.classList.toggle('keyboard-open',editing&&inset>100);body.style.setProperty('--keyboard-inset',editing?`${inset}px`:'0px');}
 window.visualViewport?.addEventListener('resize',viewport);window.visualViewport?.addEventListener('scroll',viewport);input.addEventListener('focus',viewport);input.addEventListener('blur',viewport);
 // Native dialog provides keyboard focus containment and Escape dismissal.
 const viewer=document.createElement('dialog');viewer.className='image-viewer';viewer.setAttribute('aria-label','画像を拡大');
 viewer.innerHTML='<button class="viewer-close shell-control" autofocus aria-label="画像を閉じる">✕</button><img alt=""><p></p>';
 body.append(viewer);viewer.querySelector('button').onclick=()=>viewer.close();
 viewer.addEventListener('click',e=>{if(e.target===viewer)viewer.close();});
 function zoom(img){viewer.querySelector('img').src=img.src;viewer.querySelector('img').alt=img.alt;viewer.querySelector('p').textContent=img.alt;viewer.showModal();}
 document.querySelector('#content').addEventListener('click',e=>{if(e.target.matches('img')&&!e.target.closest('button,a'))zoom(e.target);});
 document.querySelector('#content').addEventListener('keydown',e=>{if(e.target.matches('img')&&!e.target.closest('button,a')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();zoom(e.target);}});
 new MutationObserver(()=>{document.querySelectorAll('#content img:not([tabindex])').forEach(img=>{if(img.closest('button,a'))return;img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label',`${img.alt}を拡大`);});sizeInput();}).observe(document.querySelector('#content'),{childList:true,subtree:true});
 sizeInput();measure();
})();
