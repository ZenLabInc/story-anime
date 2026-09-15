const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
class Element extends EventTarget{constructor(){super();this.value='';this.hidden=false;this.maxLength=1500;this.attrs={};this.children={};}setAttribute(k,v){this.attrs[k]=v;}querySelector(s){return this.children[s]??=new Element();}showModal(){this.open=true;}close(){this.open=false;}}
function setup(supported=true){const els=Object.fromEntries(['#input','#mic','#send','#composer','#voice-status'].map(x=>[x,new Element()]));const win=new EventTarget(),doc=new EventTarget();let dialog;const timers=[];
 class Recognition{constructor(){Recognition.last=this;}start(){}stop(){this.stopping=true;}abort(){this.aborted=true;}result(text,final=true){const r=[{transcript:text}];r.isFinal=final;this.onresult({resultIndex:0,results:[r]});}}
 if(supported)win.SpeechRecognition=Recognition;
 doc.querySelector=s=>els[s];doc.createElement=()=>new Element();doc.body={append:d=>dialog=d};
 const context=vm.createContext({window:win,document:doc,Event,setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;},clearTimeout(){},YOURSTORY_ICONS:{mic:'mic',square:'stop'},busy:false});vm.runInContext(fs.readFileSync('web/voice.js','utf8'),context);
 return {els,win,doc,context,Recognition,timers,start(){els['#mic'].onclick();dialog.querySelector('[data-voice=accept]').onclick();}};
}
const a=setup();a.els['#input'].value='書きかけ';a.start();assert.equal(a.els['#send'].disabled,true);assert.equal(a.els['#input'].readOnly,true);
const old=a.Recognition.last;old.result('途中',false);assert.equal(a.els['#input'].value,'書きかけ');old.result('日本語の確定文');assert.equal(a.els['#input'].value,'書きかけ 日本語の確定文');
a.win.dispatchEvent(new Event('yourstory:before-navigate'));old.result('遅れた結果');assert.equal(a.els['#input'].value,'書きかけ 日本語の確定文');assert.equal(old.aborted,true);assert.equal(a.els['#input'].readOnly,false);
a.els['#mic'].onclick();const graceful=a.Recognition.last;a.els['#mic'].onclick();assert.equal(graceful.stopping,true);graceful.result('最後の言葉');graceful.onend();assert.match(a.els['#input'].value,/最後の言葉$/);assert.equal(a.els['#input'].readOnly,false);
a.els['#mic'].onclick();a.Recognition.last.onerror({error:'not-allowed'});assert.match(a.els['#voice-status'].textContent,/許可/);assert.equal(a.els['#input'].readOnly,false);
a.els['#input'].value='あ'.repeat(1499);a.els['#mic'].onclick();a.Recognition.last.result('いうえ');assert.equal(a.els['#input'].value.length,1500);assert.equal(a.els['#mic'].attrs['aria-pressed'],'false');
const b=setup(false);b.els['#mic'].onclick();assert.match(b.els['#voice-status'].textContent,/利用できません/);
console.log('Dictation: draft preservation, interim/final, stale result, permission error, length cap, unsupported passed');

const continuous=setup();continuous.start();const first=continuous.Recognition.last;
assert.equal(continuous.timers.length,0);first.result('前半');first.onend();
assert.equal(continuous.els['#mic'].attrs['aria-pressed'],'true');continuous.timers.at(-1).fn();
const second=continuous.Recognition.last;assert.notEqual(second,first);second.result('後半');assert.equal(continuous.els['#input'].value,'前半 後半');
second.onerror({error:'no-speech'});second.onend();continuous.timers.at(-1).fn();assert.notEqual(continuous.Recognition.last,second);
continuous.els['#mic'].onclick();const stopped=continuous.Recognition.last;stopped.onend();assert.equal(continuous.els['#input'].readOnly,false);
console.log('Continuous dictation: no time limit, natural end/no-speech restart, draft continuity, manual stop passed');
