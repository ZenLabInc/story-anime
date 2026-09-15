/* Optional browser dictation. Audio is never uploaded to our application. */
(()=>{
 const input=document.querySelector('#input'),mic=document.querySelector('#mic'),send=document.querySelector('#send'),form=document.querySelector('#composer'),status=document.querySelector('#voice-status');
 const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
 let recognition=null,active=false,accepted=false,base='',finalText='',timer=null,wanted=false;
 function state(){input.readOnly=active;send.disabled=busy||active||!input.value.trim();mic.disabled=busy;mic.setAttribute('aria-pressed',String(active));mic.setAttribute('aria-label',active?'音声入力を停止':'音声入力を開始');mic.title=active?'音声入力を停止':'音声入力';mic.innerHTML=YOURSTORY_ICONS[active?'square':'mic'];}
 function finish(message){clearTimeout(timer);timer=null;active=false;wanted=false;recognition=null;if(message!==undefined)status.textContent=message;state();}
 function stop(cancel=false){wanted=false;const old=recognition;if(!old)return;if(cancel){finish('音声入力を停止しました。文章を確認して送信してください。');old.abort();return;}status.textContent='最後の音声を確認しています…';clearTimeout(timer);try{old.stop();timer=setTimeout(()=>{if(recognition===old){finish('文章を確認して送信してください。');old.abort();}},4000);}catch{finish('文章を確認して送信してください。');old.abort();}}
 function start(restarting=false){
  if(busy||(active&&!restarting)||form.hidden)return;
  if(restarting&&!wanted)return;
  if(!Recognition){status.textContent='このブラウザでは音声入力を利用できません。端末のキーボードの音声入力をお使いください。';return;}
  if(input.value.length>=input.maxLength){status.textContent='文字数の上限です。文章を短くしてください。';return;}
  base=input.value;finalText='';const session=new Recognition();recognition=session;active=true;wanted=true;state();status.textContent='マイクの接続を待っています…';
  session.lang='ja-JP';session.continuous=true;session.interimResults=true;
  session.onstart=()=>{if(recognition!==session)return;status.textContent='聞き取り中… もう一度マイクを押すと停止します。';};
  session.onresult=e=>{
   if(recognition!==session)return;let interim='';
   for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)finalText+=e.results[i][0].transcript;else interim+=e.results[i][0].transcript;}
   const text=base+(base&&finalText&&!/\s$/.test(base)?' ':'')+finalText;
   input.value=text.slice(0,input.maxLength);input.dispatchEvent(new Event('input',{bubbles:true}));
   status.textContent=interim||'聞き取り中…';
   if(text.length>=input.maxLength){stop(true);status.textContent='文字数の上限に達したため停止しました。';}
  };
  session.onerror=e=>{if(recognition!==session)return;if(e.error==='no-speech'&&wanted){status.textContent='聞き取り中… 話し始めるのを待っています。';return;}const messages={'not-allowed':'マイクが許可されていません。ブラウザのサイト設定を確認してください。','audio-capture':'マイクが見つかりません。接続を確認してください。','network':'音声認識に接続できませんでした。通信環境を確認してください。','no-speech':'音声を聞き取れませんでした。もう一度お試しください。','language-not-supported':'このブラウザでは日本語の音声認識を利用できません。'};finish(messages[e.error]||'音声入力を終了しました。もう一度お試しください。');session.abort();};
  session.onend=()=>{if(recognition!==session)return;if(wanted){status.textContent='聞き取りを続けています…';clearTimeout(timer);timer=setTimeout(()=>{if(wanted&&recognition===session)start(true);},300);}else finish('文章を確認・編集してから送信してください。');};
  try{session.start();}catch{finish('音声入力を開始できませんでした。マイクの設定を確認してください。');}
 }
 const consent=document.createElement('dialog');consent.className='voice-consent';consent.setAttribute('aria-labelledby','voice-consent-title');
 consent.innerHTML='<h2 id="voice-consent-title">音声で入力する</h2><p>音声はブラウザ提供元の音声認識サービスへ送信される場合があります。YourStoryには録音を保存しません。認識した文章は、送信前に確認・編集できます。</p><div class="actions"><button type="button" data-voice="cancel">キャンセル</button><button type="button" class="primary" data-voice="accept">音声入力を始める</button></div>';
 document.body.append(consent);consent.querySelector('[data-voice=cancel]').onclick=()=>consent.close();consent.querySelector('[data-voice=accept]').onclick=()=>{accepted=true;consent.close();start();};
 mic.onclick=()=>{if(active){stop();return;}if(!Recognition||accepted)start();else consent.showModal();};
 input.addEventListener('input',state);window.addEventListener('yourstory:busy',state);
 window.addEventListener('yourstory:before-navigate',()=>{if(active)stop(true);consent.close();status.textContent='';});
 window.addEventListener('yourstory:navigate',()=>{state();});
 window.addEventListener('pagehide',()=>{if(active)stop(true);});
 form.addEventListener('submit',e=>{if(active){e.preventDefault();e.stopImmediatePropagation();}},true);
 state();
})();
