/* Deliberately small Markdown subset. Raw HTML, embeds and link URLs stay inert. */
(function(root){
 const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function inline(s){return s.split(/(`[^`]+`)/g).map(x=>x.startsWith('`')&&x.endsWith('`')?'<code>'+escape(x.slice(1,-1))+'</code>':escape(x).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/\*([^*\n]+)\*/g,'<em>$1</em>')).join('');}
 function render(text){
  const lines=String(text||'').replace(/\r\n?/g,'\n').split('\n');let html='',paragraph=[],list=null,code=null;
  const flush=()=>{if(paragraph.length){html+='<p>'+paragraph.map(inline).join('<br>')+'</p>';paragraph=[];}if(list){html+='</'+list+'>';list=null;}};
  for(const line of lines){
   if(/^\s*```/.test(line)){flush();if(code!==null){html+='<pre><code>'+escape(code.join('\n'))+'</code></pre>';code=null;}else code=[];continue;}
   if(code!==null){code.push(line);continue;}
   if(!line.trim()){flush();continue;}
   if(/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)){flush();html+='<hr>';continue;}
   const h=line.match(/^#{1,6}\s+(.+)$/),li=line.match(/^\s*(?:([-*+])|\d+[.)])\s+(.+)$/);
   if(h){flush();html+='<h3>'+inline(h[1])+'</h3>';continue;}
   if(li){const type=li[1]?'ul':'ol';if(paragraph.length||list!==type){flush();list=type;html+='<'+type+'>';}html+='<li>'+inline(li[2])+'</li>';continue;}
   if(list)flush();paragraph.push(line);
  }
  flush();if(code!==null)html+='<pre><code>'+escape(code.join('\n'))+'</code></pre>';return html;
 }
 root.YourStoryMarkdown={render};if(typeof module!=='undefined')module.exports=root.YourStoryMarkdown;
})(globalThis);
