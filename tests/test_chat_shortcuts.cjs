const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');let listener,sent=0;
const send={disabled:false};const form={requestSubmit(button){assert.equal(button,send);sent++;}};
vm.runInNewContext(fs.readFileSync('web/chat-stream.js','utf8'),{document:{addEventListener(type,fn){listener=fn;},querySelector(s){return s==='#send'?send:form;}}});
const key=(extra={})=>{let prevented=false;listener({target:{id:'input'},key:'Enter',preventDefault(){prevented=true;},...extra});return prevented;};
assert.equal(key(),false);assert.equal(sent,0);
assert.equal(key({metaKey:true}),true);assert.equal(key({ctrlKey:true}),true);assert.equal(sent,2);
for(const extra of [{isComposing:true},{keyCode:229},{repeat:true},{shiftKey:true},{altKey:true},{target:{id:'other'}}])key({metaKey:true,...extra});
assert.equal(sent,2);send.disabled=true;key({ctrlKey:true});assert.equal(sent,2);
console.log('Enter/newline, Cmd/Ctrl submit, IME, repeat and disabled guards passed');
