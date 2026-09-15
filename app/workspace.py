from app import publication
"""Project-centric manga workspace; immutable scene/reference snapshots, local only."""
import copy
import json
import re
import time
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app import studio as s, gemini, manga, membership, art_direction
from app.render import FONT

LAYOUTS = {'single': ('1コマ', [(0,0,1280,720)]),
           'two': ('上下2コマ', [(0,0,1280,720),(0,740,1280,1460)]),
           'three': ('大コマ＋下段2コマ（右→左）', [(0,0,1280,720),(660,740,1300,1100),(0,740,640,1100)]),
           'four': ('2×2（右→左）', [(660,0,1300,360),(0,0,640,360),(660,380,1300,740),(0,380,640,740)])}

def init():
    # Restart recovery never resends a paid request.
    with s.transaction() as db:
        for row in db.execute('SELECT data FROM works').fetchall():
            p=json.loads(row['data'])
            if p.get('version')==4 and p.get('busy'):
                p['busy']=None;p['error']='前回の処理は中断しました。自動再送しません。費用履歴を確認してください。'
                s.put(db,p)

def projects(user):
    with s.transaction() as db:
        return [{'id':p['id'],'title':p['title']} for row in db.execute('SELECT data FROM works WHERE owner=? ORDER BY updated DESC',(user,)) if (p:=json.loads(row[0])).get('version')==4 and not p.get('deleted_at')]

def create(user,title):
    title=string(title,80) or '無題の漫画'
    p={'id':s.uid(),'owner':user,'version':4,'title':title,'revision':1,'published':None,
       'world':{'text':'','revision':0},'world_draft':'','world_ready':False,'characters':[],'scenes':[], 'chats':[], 'busy':None,'error':None,'quotes':{}}
    with s.transaction() as db:
        if membership.ENFORCE:membership.project_allowed(user,db)
        db.execute('INSERT INTO works VALUES(?,?,?,?)',(p['id'],user,s.dump(p),time.time()))
        from app import metrics
        metrics.track_conn(db, user, 'project_created', p['id'])
    return p

def string(value,limit):
    if not isinstance(value,str) or len(value)>limit: raise ValueError('文字数または入力形式を確認してください。')
    return value.strip()

def load(db,user,pid,revision=None):
    p=s.get_work(db,user,pid)
    if p.get('version')!=4: raise ValueError('旧作品は閲覧専用です。')
    if p.get('busy'): raise ValueError('生成中です。完了してから操作してください。')
    if revision is not None and p['revision']!=revision: raise ValueError('別の操作で更新されました。再読込してください。')
    return p

def save(db,p):
    p['revision']+=1;s.put(db,p);return p

def item(p,kind,i):
    for v in p[kind]:
        if v['id']==i:return v
    raise ValueError('項目が見つかりません。')

def history(p,context,text,reply):
    p['chats'].append({'id':s.uid(),'context':context,'text':text,'reply':reply,'at':time.time()})

def confirmed(p):
    return sorted([x for x in p['scenes'] if x['confirmed']],key=lambda x:x.get('confirmed_at',0))

def folder(p):
    target=s.DATA/p['id']/'workspace'/s.uid();target.mkdir(parents=True);return target

def relative(path):return str(path.relative_to(s.DATA))

def approve_character(c, persona=False):
    if not c.get('asset'):raise ValueError('先に三面図を生成してください。')
    if c.get('name_state') in ['unasked','pending'] or c['name']=='新しいキャラ':raise ValueError('先にキャラの名前を教えてください。')
    if persona and (c.get('visual_state')!='confirmed' or c.get('persona_state')!='ready'):raise ValueError('先に性格・話し方の案を相談してください。')
    profile={'name':c['name'],'appearance':c.get('appearance',c['description']),
             'personality':c.get('personality','') if persona else '', 'speech':c.get('speech','') if persona else ''}
    description=profile['appearance']+('\n性格：'+profile['personality']+'\n話し方：'+profile['speech'] if persona else '')
    v={'id':s.uid(),'name':c['name'],'description':description,'asset':copy.deepcopy(c['asset']),'profile':profile,'art_style':copy.deepcopy(c.get('art_style'))}
    c['versions'].append(v);c['approved']=v['id'];c['visual_state']='confirmed'
    c['persona_state']='confirmed' if persona else 'interview'


def conversation_action(p, context, data):
    """Interpretation belongs to the LLM; apply only valid, already presented proposals."""
    action=data.get('action','update')
    if action=='update':return False
    if action=='clarify':return True
    if context=='world':
        if action!='approve':raise ValueError('世界観の会話操作が不正です。')
        if not p['world_draft']:raise ValueError('先に世界観の案を相談してください。')
        # Drafts are visible in chat even when the model still has follow-up questions.
        p['world_ready']=True
        p['world']={'text':p['world_draft'],'revision':p['world']['revision']+1}
        return True
    c=next((c for c in p['characters'] if c['id']==context),None)
    if c:
        if action=='revise_appearance':
            appearance=string(data.get('appearance',''),2000)
            if not appearance:raise ValueError('変更したい見た目を教えてください。')
            c.update(appearance=appearance,description=appearance,asset=None,visual_state='ready' if data.get('ready') is True else 'interview')
            c['view_assets']={}
            c.pop('appearance_accepted',None)
        elif action=='approve':
            if c.get('visual_state')=='confirmed':approve_character(c,persona=True)
            else:
                if not c.get('asset'):raise ValueError('先に三面図を生成してください。')
                name=string(data.get('name',''),60)
                if name:c.update(name=name,name_state='named')
                if c.get('name_state') in ['pending','unasked']:
                    c['appearance_accepted']=True
                    data['reply']='見た目はこの案にしましょう。このキャラの名前を教えてください。'
                else:
                    approve_character(c)
                    data['reply']=c['name']+'の見た目と名前を保存しました。次に、どんな性格・話し方にしますか？'
        else:raise ValueError('キャラの会話操作が不正です。')
        return True
    scene=item(p,'scenes',context)
    if action!='approve':raise ValueError('シーンの会話操作が不正です。')
    if not scene['output'] or not scene['summary']:raise ValueError('先に画像と展開の要約を揃えてください。')
    scene['confirmed']=True;scene['confirmed_at']=time.time()
    return True

def soft_delete(user,b):
    with s.transaction() as db:
        p=load(db,user,b['id'],b['revision'])
        p['deleted_at']=time.time();p['deleted_by']=user;p['quotes']={}
        save(db,p)
    return {'ok':True,'id':p['id']}

def mutate(user,b):
    with s.transaction() as db:
        p=load(db,user,b['id'],b['revision']);p['error']=None;op=b['op']
        if op=='character_new':
            if len(p['characters'])>=30:raise ValueError('1作品のキャラ保存上限は30人です。')
            c={'id':s.uid(),'name':'新しいキャラ','name_state':'unasked','description':'','asset':None,'versions':[],'approved':None,'appearance':'','visual_state':'interview','personality':'','speech':'','persona_state':'interview'}
            p['characters'].append(c)
        elif op=='world_save':
            text=string(b.get('text',p['world_draft']),2000)
            if not text:raise ValueError('世界観を入力してください。')
            p['world']={'text':text,'revision':p['world']['revision']+1};p['world_draft']=text
            history(p,'world','世界観を確定',text)
        elif op=='character_approve':
            c=item(p,'characters',b['target'])
            if not c['asset']:raise ValueError('三面図を生成して確認してください。')
            if c.get('name_state') in ['unasked','pending']:raise ValueError('チャットでキャラの名前を教えてください。')
            if c['versions'] and c['versions'][-1]['asset']==c['asset']:return p
            v={'id':s.uid(),'name':c['name'],'description':c['description'],'asset':copy.deepcopy(c['asset']),'profile':{'name':c['name'],'appearance':c.get('appearance',c['description']),'personality':'','speech':''}}
            c['versions'].append(v);c['approved']=v['id'];c['visual_state']='confirmed';c['persona_state']='interview';history(p,c['id'],'見た目を確定',c['name']+'の見た目を保存しました。次に、どんな性格・話し方にしますか？')
        elif op=='character_persona_approve':
            c=item(p,'characters',b['target'])
            if c.get('visual_state')!='confirmed' or c.get('persona_state')!='ready':raise ValueError('先に見た目と性格の相談を完了してください。')
            c['persona_state']='confirmed'
            v={'id':s.uid(),'name':c['name'],'description':c.get('appearance',c['description'])+'\n性格：'+c['personality']+'\n話し方：'+c['speech'],'asset':copy.deepcopy(c['asset'])}
            c['versions'].append(v);c['approved']=v['id'];history(p,c['id'],'キャラ設定を確定',v['description'])
        elif op=='character_visual_edit':
            c=item(p,'characters',b['target']);c['visual_state']='interview';c['asset']=None;c['view_assets']={}
            history(p,c['id'],'見た目の別案を相談','保存済みの見た目は過去のシーンに残ります。どこを変えますか？')
        elif op=='scene_new':
            if not p['world']['text']:raise ValueError('先に世界観を確定してください。')
            ids=b.get('characters',[])
            if not 1<=len(ids)<=2 or len(set(ids))!=len(ids):raise ValueError('ストックしたキャラを1〜2人選んでください。')
            cast=[]
            for cid in ids:
                c=item(p,'characters',cid)
                v=next((v for v in c['versions'] if v['id']==c['approved']),None)
                if not v or c.get('persona_state','confirmed')!='confirmed':raise ValueError('見た目と性格・話し方を確定してください。')
                cast.append(copy.deepcopy(v))
            layout=b['layout']
            if layout not in LAYOUTS:raise ValueError('コマ割りを選んでください。')
            p['scenes'].append({'id':s.uid(),'title':'新しいシーン','layout':layout,'characters':cast,'world':copy.deepcopy(p['world']), 'previous':[x['id'] for x in confirmed(p)], 'panels':[],'fixed_lines':[],'summary':'','confirmed':False,'output':None})
        elif op=='scene_confirm':
            scene=item(p,'scenes',b['target'])
            if scene['confirmed']:return p
            if not scene['output'] or not scene['summary']:raise ValueError('画像と展開の要約を確認してから確定してください。')
            scene['confirmed']=True;scene['confirmed_at']=time.time()
            history(p,scene['id'],'シーンを確定',scene['summary'])
        elif op=='scene_export':
            scene=item(p,'scenes',b['target'])
            if scene['confirmed']:raise ValueError('確定済みの出力を利用してください。')
            if not scene['panels'] or not all(x['asset'] for x in scene['panels']):raise ValueError('未生成のコマがあります。')
            scene['output']=assemble(p,scene)
        elif op=='scene_fork':
            old=item(p,'scenes',b['target']);new=copy.deepcopy(old)
            new.update(id=s.uid(),confirmed=False,title=old['title']+'（別案）',forked_from=old['id'])
            p['scenes'].append(new)
        elif op=='panel_hold':
            scene=item(p,'scenes',b['target'])
            if scene['confirmed']:raise ValueError('確定シーンは別案を作って編集してください。')
            index=b['panel']
            if type(index) is not int or not 0<=index<len(scene['panels']) or type(b['held']) is not bool:raise ValueError('コマの保持指定が不正です。')
            panel=scene['panels'][index];panel['held']=b['held']
        elif op=='summary_save':
            scene=item(p,'scenes',b['target'])
            if scene['confirmed']:raise ValueError('確定前に要約を編集してください。')
            scene['summary']=string(b['text'],800)
        else:raise ValueError('操作がありません。')
        return save(db,p)

def chat(user,b,on_text=None):
    text=string(b['text'],1500)
    if not text:raise ValueError('メッセージを入力してください。')
    context=b['context'];token=s.uid();unified=context=='studio';selected=set()
    with s.transaction() as db:
        p=load(db,user,b['id'],b['revision'])
        if unified:
            from app import conversation
            current=conversation.brief(p,b.get('viewing'));schema=conversation.SCHEMA
        elif context=='world':current={'world':p['world_draft'],'confirmed':p['world']};schema='{"reply":"未定項目を一つだけ質問。揃えば確認案内","world":"相談結果を蓄積した世界観プロンプト","ready":false} 舞台、世界のルール、雰囲気、画風を把握する。任意の順序。おまかせなら補完。揃うまでready=false、揃ったらtrue。確定済みなら依頼箇所だけ変更しtrue。'
        elif any(c['id']==context for c in p['characters']):
            c=item(p,'characters',context)
            visual=c.get('visual_state','confirmed' if c['approved'] else 'interview')
            if (c.get('name_state')=='pending' or c['name']=='新しいキャラ') and c['asset']:
                current={'appearance':c.get('appearance',c['description']),'name':c['name']}
                schema='{"reply":"名前の相談への返答","name":"ユーザーが指定したキャラ名。未定の場合は空文字"} 画像生成後の命名段階。見た目や性格は変更しない。単純な名前だけの発言も名前として受け取る。おまかせならオリジナルの名前を一つ提案してnameに入れる。'
            elif visual=='confirmed':
                current={'name':c['name'],'appearance':c.get('appearance',c['description']),'personality':c.get('personality',''),'speech':c.get('speech','')}
                schema='{"reply":"性格・口調についての返答または次の一問","personality":"性格","speech":"一人称・話し方・口癖","ready":false} 見た目は確定済みなので絶対に変更しない。性格と話し方だけ相談し、揃えばready=true。おまかせは提案として補完。'
            else:
                current={'name':c['name'],'appearance':c.get('appearance',c['description'])}
                schema='{"reply":"見た目の次の一問。揃えば三面図の生成案内","appearance":"年齢感・性別表現・髪/顔・体型・服装の設定全文","ready":false} 最初は見た目だけヒアリング。名前は画像生成後に聞くため、ここでは質問も命名もしない。性格や話し方を質問しない。ユーザーから性格の情報があれば会話に残すが外見を優先する。見た目が揃えばready=true。おまかせなら補完して提案。'
        else:
            scene=item(p,'scenes',context)
            if scene['confirmed']:raise ValueError('確定シーンは別案で編集してください。')
            selected={int(n)-1 for n in re.findall(r'([1-4])コマ',text)}
            # Selected panels are interpreted by the LLM, then validated before applying edits.
            current={k:v for k,v in scene.items() if k not in ['output','panels']}
            current['panels']=[{k:v for k,v in x.items() if k not in ['asset']} for x in scene['panels']]
            current['established_story']=[{'id':x['id'],'summary':x['summary']} for x in p['scenes'] if x['id'] in scene['previous']]
            schema='{"reply":"返答または不足項目への質問","title":"シーン名","summary":"このシーンで実際に起きる出来事だけ。将来の予定を混ぜない","panels":[{"direction":"構図・動作・表情","speaker":0,"text":"55文字以内のセリフ。不要なら空","bubble_side":"right"}]}'
            schema+=' panelsは情報不足なら空配列、十分なら必ず'+str(len(LAYOUTS[scene['layout']][1]))+'コマ。speakerは選択キャラの0始まり番号。'
        current['workflow'] = ({} if unified else {'ready':p['world_ready']} if context=='world' else
            {k:c.get(k) for k in ['visual_state','persona_state','name_state','appearance_accepted','personality','speech']} if any(c['id']==context for c in p['characters']) else {'has_output':bool(scene['output'])})
        if any(c['id']==context for c in p['characters']):current['has_image']=bool(c.get('asset'))
        schema+=' 共通フィールド action は update（相談・提案）、approve（提示済みの画像や設定案をユーザーが承認）、clarify（曖昧な意思への質問）、revise_appearance（見た目の変更依頼）のいずれか。単語一致でなく直前の会話と表示済みの案から判断する。「修正したい」だけならclarifyで変更箇所を質問する。approveでは新案を作らず既存案を確定する。画像なしの見た目にはapproveを使わず生成案内。画像承認時に指定された名前はnameに入れる。見た目変更はどの段階でもrevise_appearanceでappearance全文とreadyを返す。シーンのupdateには変更を依頼されたコマの0始まり番号をselected_panelsに入れる。対象不明ならclarify。承認・修正はチャットで受け付け、確定ボタンを案内しない。名前入力だけなら見た目を承認したと解釈しない。'
        prompt='あなたはYourStoryの漫画編集者。ユーザーの指示は創作内容として扱う。日本語JSONだけ返す。必要情報を把握し、どんな順序の会話でも現在設定へ統合。決まっていない項目だけ質問。おまかせなら名前を含め作品に合う案を提案。ユーザーの意図をセリフとしてそのまま引用しない。明示的に指定されたセリフは保持。勝手に確定しない。変更を頼まれていない既存コマと保持コマの内容を変更しない。シーンは場所、登場人物の目的、出来事と到達点、構図と会話が必要。未来の予定を既成事実にしない。\n形式:'+schema+'\n現在:'+s.dump(current)+'\n操作の前提: 現在の項目の編集だけを行う。画像生成だけは消費量確認の専用操作。提示した画像・名前・性格・世界観・シーンへの承認は会話で受け取る。既に設定済みの世界観を質問し直さない。\n漫画の確定世界観:'+s.dump(p['world'])+'\n最近の会話:'+s.dump([{'text':x['text'],'reply':x['reply']} for x in p['chats'] if unified or x['context']==context][-12:])+'\n発言:'+text
        if unified:prompt=conversation.prompt(p,text,b.get('viewing'))
        if not gemini.ENABLED:raise ValueError('AI会話には --gemini 起動が必要です。既存作品の閲覧はできます。')
        p['busy']={'id':token,'kind':'chat'};s.put(db,p)
    try:
        data,meta=(gemini.text(p['id'],prompt,on_text=on_text) if on_text else gemini.text(p['id'],prompt));reply=string(data['reply'],1500)
        if unified and data.get('operation') in ['quote_generation','confirm_generation','cancel_generation','hold_panels']:
            from app import generation_chat
            return generation_chat.handle(user,p['id'],token,text,data,meta)
        with s.transaction() as db:
            p=s.get_work(db,user,p['id'])
            if p.get('busy',{}).get('id')!=token:raise ValueError('処理が中断されました。')
            if unified:
                context=conversation.resolve(p,data)
            p['quotes']={}  # Any intervening creative conversation invalidates spending consent.
            handled=conversation_action(p,context,data)
            reply=string(data['reply'],1500)
            if handled:pass
            elif context=='world':
                p['world_draft']=string(data['world'],2000);p['world_ready']=data.get('ready') is True
                if not p['world_draft']:p['world_ready']=False
                if p['world_ready']:reply='世界観の案がまとまりました。下のプロンプトを確認し、チャットで「これでOK」または変更したい点を教えてください。'
            elif any(c['id']==context for c in p['characters']):
                c=item(p,'characters',context)
                if (c.get('name_state')=='pending' or c['name']=='新しいキャラ') and c['asset']:
                    name=string(data.get('name',''),60)
                    if name:
                        c['name']=name;c['name_state']='named'
                        reply=name+'ですね。三面図と名前はこれで良いですか？チャットで教えてください。'
                        if c.get('appearance_accepted'):
                            approve_character(c);reply=name+'の見た目と名前を保存しました。次に性格・話し方を教えてください。'
                    else:reply='このキャラの名前を教えてください。おまかせでも大丈夫です。'
                elif c.get('visual_state','confirmed' if c['approved'] else 'interview')=='confirmed':
                    c['personality']=string(data['personality'],1200);c['speech']=string(data['speech'],800)
                    c['persona_state']='ready' if data.get('ready') is True and c['personality'] and c['speech'] else 'interview'
                    if c['persona_state']=='ready':reply='性格・話し方の案がまとまりました。下の内容を確認し、チャットでOKか変更したい点を教えてください。見た目は変更していません。'
                else:
                    name=c['name'] if c.get('name_state') in ['unasked','named'] else string(data.get('name',c['name']),60);appearance=string(data.get('appearance',data.get('description','')),2000)
                    if (name,appearance)!=(c['name'],c.get('appearance',c['description'])):c['asset']=None;c['view_assets']={}
                    c.update(name=name,description=appearance,appearance=appearance,visual_state='ready' if data.get('ready') is True and appearance else 'interview')
                    for key,limit in [('personality',1200),('speech',800),('background',1200)]:
                        if data.get(key):c[key]=string(data[key],limit)
                    if c['visual_state']=='ready':reply='見た目の案がまとまりました。下の内容を確認し、「生成して」と話しかけてください。消費量をご案内します。'
            else:
                scene=item(p,'scenes',context);panels=data['panels']
                requested=data.get('selected_panels',list(selected))
                if not isinstance(requested,list) or any(type(i) is not int or not 0<=i<len(LAYOUTS[scene['layout']][1]) for i in requested):raise ValueError('変更対象のコマが不正です。')
                selected=set(requested)
                if scene['panels'] and not selected:raise ValueError('変更するコマを教えてください。')
                if not isinstance(panels,list) or len(panels) not in [0,len(LAYOUTS[scene['layout']][1])]:raise ValueError('コマ数が一致しません。再送せず停止しました。')
                validated=[]
                for i,x in enumerate(panels):
                    panel={'direction':string(x['direction'],800),'text':string(x['text'],55),'speaker':x['speaker'],'bubble_side':x.get('bubble_side','right'),'held':False,'asset':None}
                    if type(panel['speaker']) is not int or not 0<=panel['speaker']<len(scene['characters']) or panel['bubble_side'] not in ['left','right']:raise ValueError('コマの人物指定が不正です。')
                    old=scene['panels'][i] if i<len(scene['panels']) else None
                    if old and (old['held'] or (selected and i not in selected)):panel=old
                    elif old and all(panel[k]==old[k] for k in ['direction','speaker']):
                        panel['asset']=copy.deepcopy(old['asset'])
                        if panel['asset'] and any(panel[k]!=old[k] for k in ['text','bubble_side']):
                            dest=folder(p)/'panel.png';manga.letter(Image.open(s.DATA/panel['asset']['raw']),panel['text'],panel['bubble_side']).save(dest);panel['asset']['file']=relative(dest)
                    validated.append(panel)
                if not panels and scene['panels']:raise ValueError('既存コマを削除する案は保存しませんでした。')
                fixed=list(scene.get('fixed_lines',[]))
                if '固定解除' in text:fixed=[]
                elif any(t in text for t in ['セリフ','台詞','固定','言わせ']):
                    fixed+=re.findall(r'「([^「」]{1,55})」',text)
                if validated and any(not any(line in x['text'] for x in validated) for line in fixed):raise ValueError('固定セリフを保持していないため、変更を保存しませんでした。')
                scene['fixed_lines']=list(dict.fromkeys(fixed))
                scene.update(title=string(data['title'],100),summary=string(data['summary'],800),panels=validated,output=None)
                if validated and all(x['asset'] for x in validated):scene['output']=assemble(p,scene)
            if unified:
                p['active_context']=context
                if data.get('action')=='approve' and context=='world':
                    next_context=conversation.capture_character_intake(p,data)
                    if next_context:context=next_context;p['active_context']=context
                    # Keep the semantic reply; a fixed next-step question discards mixed intent.
                elif data.get('action')=='approve' and any(c['id']==context and c.get('persona_state')=='confirmed' for c in p['characters']):reply='キャラの設定を保存しました。もう一人つくりますか？それとも、このキャラで漫画を描き始めますか？'
            history(p,context,text,reply)
            from app import metrics
            metrics.track_conn(db, user, 'chat_turn_completed', p['id'], {'status':'succeeded'})
            if handled or data.get('action')=='approve' or p.get('world_ready') or any(c.get('persona_state')=='ready' for c in p.get('characters',[])):
                metrics.track_once_conn(db, user, 'first_value', p['id'], {'source':'chat'})
            if context=='world' and data.get('action','update')=='update' and p['world_draft']:
                p['chats'][-1]['proposal']={'kind':'world','text':p['world_draft'],'ready':p['world_ready']}
            p['chats'][-1]['api']=meta;p['busy']=None;p['error']=None
            return save(db,p)
    except Exception as error:
        fail(user,p['id'],token,str(error));raise

def fail(user,pid,token,error):
    with s.transaction() as db:
        p=s.get_work(db,user,pid)
        if p.get('busy') and p['busy']['id']==token:
            kind=p['busy'].get('kind','unknown');p['busy']=None;p['error']=error
            from app import metrics
            metrics.track_conn(db, user, 'generation_failed' if kind=='image' else 'chat_turn_completed', p['id'], {
                'kind':kind, 'status':'failed', 'error_class':type(error).__name__ if isinstance(error,BaseException) else 'generation_error',
            })
            save(db,p)

def make_quote(p,kind,target,b):
    if kind=='character':
        c=item(p,'characters',target)
        if c.get('visual_state')=='confirmed':raise ValueError('見た目を変更する場合は別案を相談してください。')
        if not c['description'] or c.get('visual_state')!='ready':raise ValueError('見た目のヒアリングを完了してください。')
        from app import character_views
        ids=character_views.selected(c,b.get('views'))
    elif kind=='scene':
        scene=item(p,'scenes',target)
        if scene['confirmed']:raise ValueError('確定済みです。別案を作成してください。')
        ids=b.get('panels',[])
        if not isinstance(ids,list) or not ids or any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):raise ValueError('生成するコマを教えてください。')
        for i in ids:
            if type(i) is not int or not 0<=i<len(scene['panels']) or scene['panels'][i]['held']:raise ValueError('保持したコマは生成できません。')
    else:raise ValueError('生成の種類が不正です。')
    q={'id':s.uid(),'kind':kind,'target':target,'panels':ids,'cap_jpy':len(ids)*gemini.CONFIG['image_request_cap_jpy'],'expires':time.time()+600,'revision':p['revision']+1,'status':'ready'}
    return q

def quote(user,b):
    with s.transaction() as db:
        p=load(db,user,b['id'],b['revision']);kind=b['kind'];target=b['target']
        q=make_quote(p,kind,target,b)
        p['quotes']={q['id']:q};save(db,p);return {'project':p,'quote':q}

def generate(user,b):
    token=s.uid()
    with s.transaction() as db:
        p=s.get_work(db,user,b['id']);q=p.get('quotes',{}).get(b['quote_id'])
        if not q:raise ValueError('見積もりを取り直してください。')
        if q['status']!='ready':return p
        p=load(db,user,b['id'],q['revision'])
        if time.time()>q['expires']:raise ValueError('見積もりの有効期限が切れました。')
        if q['kind']=='scene':
            for i in q['panels']:manga.validate_dialogue(item(p,'scenes',q['target'])['panels'][i]['text'])
        if not gemini.ENABLED:raise ValueError('実画像生成には --gemini 起動が必要です。')
        if membership.ENFORCE:membership.check_images(user,len(q['panels']),db)
        budget=gemini.budget()
        user_key=membership.ENFORCE and membership.plan(db,user)[0]=='free'
        if not user_key and budget['limit_jpy'] is not None and budget['reserved_or_spent_jpy']+q['cap_jpy']>budget['limit_jpy']:raise ValueError('運営側の生成上限に達したため、現在生成を停止しています。')
        q['status']='started';p['quotes'][q['id']]=q;p['busy']={'id':token,'kind':'image'}
        from app import metrics
        metrics.track_conn(db, user, 'generation_started', p['id'], {
            'kind':q['kind'], 'image_count':len(q['panels']),
            'cost_usd_estimated':0 if user_key else q['cap_jpy']/membership.USD_JPY,
            'payer':'user' if user_key else 'operator',
            'status':'started', 'provider':p.get('provider','gemini'),
        })
        s.put(db,p)
    try:
        if q['kind']=='character':
            from app import character_views
            character_views.generate(user,p,q)
        else:
            scene=item(p,'scenes',q['target']);refs=[]
            for c in scene['characters']:
                with Image.open(s.DATA/c['asset']['sheet']) as im:refs.append(art_direction.normalize(im,(960,480)))
            dest=folder(p);ref=Image.new('RGB',(960,480*len(refs)),'white')
            for i,im in enumerate(refs):ref.paste(im,(0,i*480))
            refpath=dest/'cast.png';ref.save(refpath)
            for i in q['panels']:
                panel=scene['panels'][i];dest=folder(p);raw=dest/'raw.png'
                work={'characters':[{k:c[k] for k in ['name','description']} for c in scene['characters']],'answers':{'story':scene['world']['text']+'\n'+scene['summary'],'style':art_direction.prompt(scene.get('art_style'))}}
                work['panel_size']=publication.panel_size(scene)
                shot={**panel,'expression':'シーンの指示に従う'}
                meta=gemini.image(p['id'],manga.art_prompt(work,shot)+'\nReference rows follow character order, each row front/side/back.',raw,refpath,aspect_ratio=(publication.spec(scene) or {}).get('panel_aspect',(publication.spec(scene) or {}).get('aspect','16:9')))
                meta['geometry']=art_direction.normalize_file(raw,publication.panel_size(scene))
                image=dest/'panel.png';manga.letter(Image.open(raw),panel['text'],panel['bubble_side'],publication.panel_size(scene)).save(image)
                panel['asset']={'raw':relative(raw),'file':relative(image),'api':meta}
                # Save each paid result before the next request; partial success is recoverable.
                with s.transaction() as db:
                    fresh=s.get_work(db,user,p['id']);item(fresh,'scenes',scene['id'])['panels'][i]=panel;item(fresh,'scenes',scene['id'])['output']=None;s.put(db,fresh)
            if all(x['asset'] for x in scene['panels']):
                output=assemble(p,scene)
                with s.transaction() as db:
                    fresh=s.get_work(db,user,p['id']);item(fresh,'scenes',scene['id'])['output']=output;s.put(db,fresh)
        with s.transaction() as db:
            p=s.get_work(db,user,p['id']);p['quotes'][q['id']]['status']='done';p['busy']=None;p['error']=None
            reply=f'{len(q["panels"])}枚を生成しました。'
            if q['kind']=='character' and item(p,'characters',q['target']).get('asset') and item(p,'characters',q['target']).get('name_state')=='pending':reply='三面図ができました。このキャラの名前を教えてください。'
            history(p,q['target'],'画像生成',reply)
            p['chats'][-1]['images']=([item(p,'characters',q['target'])['asset']['sheet']] if q['kind']=='character' and item(p,'characters',q['target']).get('asset') else [item(p,'characters',q['target'])['view_assets'][name]['file'] for name in ('front','side','back') if name in item(p,'characters',q['target']).get('view_assets',{})] if q['kind']=='character' else [item(p,'scenes',q['target'])['panels'][i]['asset']['file'] for i in q['panels']])
            from app import metrics
            metrics.track_conn(db, user, 'generation_completed', p['id'], {
                'kind':q['kind'], 'image_count':len(q['panels']), 'status':'succeeded',
            })
            return save(db,p)
    except Exception as error:
        fail(user,p['id'],token,str(error));raise

def assemble(p,scene):
    if publication.spec(scene):
        images=[]
        for panel in scene['panels']:
            with Image.open(s.DATA/panel['asset']['file']) as im:images.append(im.convert('RGB'))
        dest=folder(p)/'scene.png';publication.compose(scene,images).save(dest);return relative(dest)
    boxes=LAYOUTS[scene['layout']][1];w=max(b[2] for b in boxes);h=max(b[3] for b in boxes)
    page=Image.new('RGB',(w+40,h+100),'white');draw=ImageDraw.Draw(page)
    draw.text((20,15),scene['title'],font=ImageFont.truetype(FONT,28),fill='black')
    for panel,(x1,y1,x2,y2) in zip(scene['panels'],boxes):
        with Image.open(s.DATA/panel['asset']['file']) as im:page.paste(art_direction.normalize(im,(x2-x1,y2-y1)),(20+x1,80+y1))
        draw.rectangle((20+x1,80+y1,20+x2-1,80+y2-1),outline='black',width=3)
    dest=folder(p)/'scene.png';page.save(dest);return relative(dest)
