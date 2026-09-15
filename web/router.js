/* URL grammar shared by navigation and isolated tests. No view or data dependencies. */
(function(root){
 const id='[a-zA-Z0-9_-]+';
 function parse(path){
  if(path==='/app'||path==='/app/')return {page:'home'};
  if(path==='/app/account')return {page:'account'};
  if(path==='/app/new')return {page:'new'};
  const m=path.match(new RegExp('^/app/manga/('+id+')(?:/materials/('+id+'))?/?$'));
  return m?{page:'studio',project:m[1],material:m[2]||null}:{page:'missing'};
 }
 function path(route){
  if(route.page==='account')return '/app/account';
  if(route.page==='new')return '/app/new';
  if(route.page==='studio')return '/app/manga/'+encodeURIComponent(route.project)+(route.material?'/materials/'+encodeURIComponent(route.material):'');
  return '/app';
 }
 const api={parse,path};root.YourStoryRouter=api;
 if(typeof module!=='undefined')module.exports=api;
})(globalThis);
