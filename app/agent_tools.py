"""Independent manga tools. Model chooses order; server enforces canon and spend guards."""
import copy,time
from PIL import Image
from app import manga, style_catalog, publication
from app import workspace as w, studio as s, conversation, membership

def schema(name,description,properties=None,required=None):
    return {'name':name,'description':description,**({'parameters':{'type':'OBJECT','properties':properties,'required':required or []}} if properties else {})}
S={'type':'STRING'};B={'type':'BOOLEAN'};I={'type':'INTEGER'}
STRINGS={'type':'ARRAY','items':S};INDICES={'type':'ARRAY','items':I,'description':'0始まりの番号。1コマ目は0、2コマ目は1。全2コマなら[0,1]。'}
CHAR={k:S for k in ['name','appearance','personality','speech','background']}
PANEL={'type':'OBJECT','properties':{'direction':S,'speaker':{'type':'INTEGER','description':'cast配列の0始まりの人物番号'},'text':S,'bubble_side':{'type':'STRING','enum':['right','left']}},'required':['direction','speaker','text','bubble_side']}
PANEL['properties']['bubbles']={'type':'ARRAY','description':'1〜4吹き出し。各textは120文字以内。指定時はtextは全文連結、speaker/bubble_sideは最初の吹き出しと同じにする。','items':{'type':'OBJECT','properties':{k:PANEL['properties'][k] for k in ['text','speaker','bubble_side']},'required':['text','speaker','bubble_side']}}
TOOLS=[
 schema('show_publication_formats','用途・掲載先に合わせた完成形式の見本を表示。候補外の掲載先も聞き、対応可能な候補を提案する。'),
 schema('propose_publication','掲載先と完成形式の候補を保存。まだ確定しない。寸法・順序を返答で説明して「この形でよいですか？」と聞く。',{'preset':{'type':'STRING','enum':list(publication.PRESETS)},'destination':S},['preset','destination']),
 schema('confirm_publication','前の会話で提案した完成形式をユーザーの了承で確定。新しいシーンだけに適用し既存は保持。'),
 schema('export_manga','完成画像から指定順に書き出す。画像再生成なし。既存素材は保持。MP4は1コマ5秒の無音スライド。形式変更では余白で合わせる。',{'scenes':STRINGS,'preset':{'type':'STRING','enum':list(publication.PRESETS)}},['scenes','preset']),
 schema('show_style_samples','保存済みの絵のテイスト見本画像をチャットへ表示。未選択時や別の候補を見たいときに使う。自由な指定も可能。'),
 schema('set_art_style','ユーザーが選んだ絵のテイストを作品へ保存。具体的な線・塗り・頭身・雰囲気。既存確定画像は変更しない。',{'prompt':S},['prompt']),
 schema('get_workspace','世界観・人物・シーン・見積の現在状態を読む。保存済み情報を質問し直す前に参照。'),
 schema('update_world','世界観の下書き全文を保存。ユーザーに見せる本文は最終返答へ自分で書く。確定済みの世界観は承認まで変えない。',{'text':S},['text']),
 schema('confirm_world','以前の会話で提示した世界観の下書きを、利用者の明示承認で確定。'),
 schema('create_character','新しい人物を下書き保存。名前・外見・性格・経歴は自由な順序で受付。画像生成は別ツール。',CHAR),
 schema('update_character','指定人物の変更項目だけを保存。指定項目は既存情報を保持した全文。確定版と過去シーンは保持。',{'id':S,**CHAR},['id']),
 schema('confirm_character','以前に提示した画像・名前・人物設定を明示承認で確定。scope=appearanceは画像と名前、profileは性格/話し方も確定。',{'id':S,'scope':{'type':'STRING','enum':['appearance','profile']}},['id','scope']),
 schema('create_scene','確定世界観と確定人物で新しい漫画シーンを下書き作成。画像生成は別。',{'cast':STRINGS,'layout':{'type':'STRING','enum':['single','two','three','four']},'title':S},['cast','layout','title']),
 schema('update_scene','シーン台本を保存。内容は最終返答へ自分で書く。全コマの配列を返すが変更はselected_panelsだけ。保持/対象外コマは変更不可。',{'id':S,'title':S,'summary':S,'panels':{'type':'ARRAY','items':PANEL},'selected_panels':INDICES},['id','title','summary','panels','selected_panels']),
 schema('fork_scene','確定シーンの元を残して修正用コピーを作る。新IDへupdate_scene。',{'id':S},['id']),
 schema('hold_panels','コマを保持/保持解除。解除だけで生成しない。',{'id':S,'panels':INDICES,'held':B},['id','panels','held']),
 schema('set_fixed_lines','ユーザーが原文保持を求めたセリフをシーンに登録する。既存固定は維持。',{'id':S,'lines':STRINGS},['id','lines']),
 schema('release_fixed_lines','ユーザーが明示的に固定解除を求めたセリフだけ解除。既存確定シーンはfork_sceneが必要。',{'id':S,'lines':STRINGS},['id','lines']),
 schema('confirm_scene','以前に提示した画像付きシーンを明示承認で確定。',{'id':S},['id']),
 schema('generate_images','生成の許可をLLMが会話から判断する。通常はconfirmationと直前confirmation_id。明示の生成依頼・継続委任はuser_requestと利用者の原文instruction。正面承認後の残り方向はfront_approvedと今回の承認原文instruction。人物views=0正面/1横/2背面、シーンpanelsは0始まり。',{'id':S,'confirmation_id':S,'authorization':{'type':'STRING','enum':['confirmation','user_request','front_approved']},'instruction':S,'completion_message':S,'panels':INDICES,'views':INDICES},['id']),
 schema('cancel_generation','見積を取り消す。画像を生成しない。')]

def public_state(p):
    state=conversation.brief(p)
    state['art_style']=p.get('art_style')
    state['publication']=p.get('publication');state['publication_draft']=p.get('publication_draft');state['exports']=p.get('exports',[])
    state['characters']=copy.deepcopy(p['characters'])
    for c in state['characters']:
        c['has_image']=bool(c.get('asset'));c.pop('versions',None);c.pop('asset',None);c.pop('view_assets',None)
    state['scenes']=[{'id':x['id'],'title':x['title'],'summary':x['summary'],'confirmed':x['confirmed'],'layout':x['layout'],'publication':x.get('publication'),'has_output':bool(x['output']),'cast':[c['name'] for c in x['characters']],'panels':[{k:v for k,v in a.items() if k!='asset'}|{'has_image':bool(a.get('asset'))} for a in x['panels']]} for x in p['scenes']]
    return state

class Toolset:
    def __init__(self,p,user,text):
        self.p=p;self.original=copy.deepcopy(p);self.user=user;self.text=text;self.artifacts=[];self.trace=[];self.execute=None;self.quoted=False;self.changed=False
    def artifact(self,kind,text='',**extra):self.artifacts.append({'kind':kind,'text':text,**extra})
    def call(self,name,args):
        if name not in {t['name'] for t in TOOLS}:raise ValueError('Unknown tool')
        if not isinstance(args,dict):raise ValueError('ツール入力はオブジェクトです。')
        declaration=next(t for t in TOOLS if t['name']==name).get('parameters',{'properties':{},'required':[]})
        if any(k not in declaration['properties'] for k in args) or any(k not in args for k in declaration['required']):raise ValueError('ツールの項目が不正です。')
        for k,value in args.items():
            expected=declaration['properties'][k]['type']
            if (expected=='STRING' and not isinstance(value,str)) or (expected=='BOOLEAN' and type(value) is not bool) or (expected=='ARRAY' and not isinstance(value,list)):raise ValueError('ツールの型が不正です。')
        before=copy.deepcopy(self.p);artifacts=copy.deepcopy(self.artifacts)
        try:
            if self.execute and name!='get_workspace':raise ValueError('画像生成を予約した後は編集できません。')
            result=self.apply(name,args)
        except Exception:
            self.p.clear();self.p.update(before);self.artifacts=artifacts;raise
        self.trace.append({'name':name,'ok':True})
        return result
    def invalidate(self):self.p['quotes']={};self.changed=True
    def apply(self,name,a):
        p=self.p
        if name=='get_workspace':return public_state(p)
        if name=='show_publication_formats':
            self.artifact('publication_formats');return {'formats':publication.catalog()}
        if name=='propose_publication':
            p['publication_draft']=publication.proposal(a['preset'],a['destination']);self.invalidate();return {'draft':p['publication_draft'],'needs_confirmation':True}
        if name=='confirm_publication':
            draft=p.get('publication_draft')
            if not draft or draft!=self.original.get('publication_draft'):raise ValueError('今回の形式案は先に提示し、次の発言で了承を得てください。')
            p['publication']=copy.deepcopy(draft);self.invalidate();return {'confirmed':True,'publication':p['publication']}
        if name=='export_manga':
            ids=a['scenes']
            if len(set(ids))!=len(ids):raise ValueError('シーンが重複しています。')
            scenes=[w.item(p,'scenes',sid) for sid in ids]
            result=publication.export(p,scenes,a['preset']);self.artifact('downloads',files=result['files']);return result
        if name=='show_style_samples':
            self.artifact('style_samples');return {'styles':style_catalog.STYLES,'custom_supported':True}
        if name=='set_art_style':
            value=w.string(a['prompt'],1000)
            if not value:raise ValueError('絵のテイストを教えてください。')
            p['art_style']={'prompt':value,'revision':(p.get('art_style') or {}).get('revision',0)+1};self.invalidate();return {'saved':True,'art_style':p['art_style']}
        if name=='update_world':
            text=w.string(a['text'],2000)
            if not text:raise ValueError('世界観の下書きが空です。')
            p.update(world_draft=text,world_ready=True,active_context='world');self.invalidate()
            return {'saved':True,'draft':text}
        if name=='confirm_world':
            if not p['world_draft'] or p['world_draft']!=self.original['world_draft']:raise ValueError('今回作った案は先に利用者へ提示してください。')
            p['world']={'text':p['world_draft'],'revision':p['world']['revision']+1};p['world_ready']=True;self.invalidate()
            return {'confirmed':True,'world':p['world']}
        if name in ['create_character','update_character']:
            if name=='create_character':
                cid=conversation.resolve(p,{'operation':'new_character','action':'update'})
            else:cid=a['id']
            c=w.item(p,'characters',cid)
            limits={'name':60,'appearance':2000,'personality':1200,'speech':800,'background':1200}
            for k,limit in limits.items():
                if k not in a:continue
                value=w.string(a[k],limit)
                if k=='appearance' and value!=c.get(k):c.update(asset=None,view_assets={},visual_state='interview');c.pop('appearance_accepted',None)
                c[k]=value
            c['description']=c.get('appearance','')
            if c.get('name') and c['name']!='新しいキャラ':c['name_state']='named'
            if c.get('appearance') and c.get('visual_state')!='confirmed':c['visual_state']='ready'
            if c.get('personality') and c.get('speech'):c['persona_state']='ready'
            p['active_context']=cid;self.invalidate()
            return {'saved':True,'id':cid,'character':next(x for x in public_state(p)['characters'] if x['id']==cid)}
        if name=='confirm_character':
            c=w.item(p,'characters',a['id']);old=w.item(self.original,'characters',a['id'])
            if not c.get('asset') or c.get('asset')!=old.get('asset') or any(c.get(k)!=old.get(k) for k in ['name','appearance','personality','speech']):raise ValueError('新しい画像や設定は先に提示して確認してください。')
            if a['scope'] not in ['appearance','profile']:raise ValueError('確定対象を確認してください。')
            if a['scope']=='profile':
                if not c.get('personality') or not c.get('speech'):raise ValueError('性格・話し方の案を先に提示してください。')
                if c.get('visual_state')!='confirmed':w.approve_character(c)
                c['persona_state']='ready'
            w.approve_character(c,persona=a['scope']=='profile')
            if a['scope']=='appearance' and c.get('personality') and c.get('speech'):c['persona_state']='ready'
            p['active_context']=c['id'];self.invalidate();return {'confirmed':True,'id':c['id']}
        if name=='create_scene':
            if not p.get('publication'):raise ValueError('用途・掲載形式を提案し、了承を得てconfirm_publicationで確定してください。')
            if a['layout'] not in p['publication']['layouts']:raise ValueError('確定した形式のコマ数に合わせてください。対応: '+str(p['publication']['layouts']))
            sid=conversation.resolve(p,{'operation':'new_scene','cast':a['cast'],'layout':a['layout']})
            scene=w.item(p,'scenes',sid);scene['publication']=copy.deepcopy(p['publication']);scene['art_style']=copy.deepcopy(p.get('art_style'));scene['title']=w.string(a['title'],100);p['active_context']=sid;self.invalidate();return {'id':sid,'scene':scene}
        if name=='fork_scene':
            old=w.item(p,'scenes',a['id'])
            if not old['confirmed']:raise ValueError('確定したシーンを指定してください。')
            new=copy.deepcopy(old);new.update(id=s.uid(),confirmed=False,forked_from=old['id'],title=old['title']+'（別案）');p['scenes'].append(new);self.invalidate();return {'id':new['id']}
        if name=='release_fixed_lines':
            scene=w.item(p,'scenes',a['id'])
            if scene['confirmed']:raise ValueError('確定シーンの固定は変更できません。')
            if not a['lines'] or any(line not in scene.get('fixed_lines',[]) for line in a['lines']):raise ValueError('既存の固定セリフを指定してください。')
            scene['fixed_lines']=[line for line in scene['fixed_lines'] if line not in a['lines']];self.invalidate();return {'fixed_lines':scene['fixed_lines']}
        if name=='set_fixed_lines':
            scene=w.item(p,'scenes',a['id'])
            if scene['confirmed']:raise ValueError('確定シーンの固定は変更できません。')
            lines=[w.string(line,120) for line in a['lines']]
            if not lines or any(not line or line not in self.text for line in lines):raise ValueError('今回の発言で指定された原文だけ固定できます。')
            scene['fixed_lines']=list(dict.fromkeys(scene.get('fixed_lines',[])+lines));self.invalidate();return {'fixed_lines':scene['fixed_lines']}
        if name in ['update_scene','hold_panels','confirm_scene']:
            scene=w.item(p,'scenes',a['id'])
            if scene['confirmed']:raise ValueError('確定シーンはfork_sceneで元を残して編集してください。')
            if name=='update_scene':self.update_scene(scene,a)
            elif name=='hold_panels':
                ids=a['panels']
                if not ids or any(type(i) is not int or not 0<=i<len(scene['panels']) for i in ids):raise ValueError('コマ番号が不正です。')
                for i in ids:scene['panels'][i]['held']=a['held']
            else:
                old=w.item(self.original,'scenes',scene['id'])
                if not scene['output'] or scene['output']!=old['output'] or scene['panels']!=old['panels']:raise ValueError('画像を先に提示して確認してください。')
                scene.update(confirmed=True,confirmed_at=time.time())
            p['active_context']=scene['id'];self.invalidate();return {'saved':True,'id':scene['id'],'confirmed':scene['confirmed']}
        if name=='generate_images':
            if not (p.get('art_style') or {}).get('prompt'):raise ValueError('画像生成前に絵のテイストを聞き取り、set_art_styleで保存してください。')
            previous=self.original.get('chats',[])
            authorization=a.get('authorization','confirmation')
            if authorization=='confirmation':
                if self.changed or not previous or a.get('confirmation_id')!=previous[-1]['id']:raise ValueError('前のAI返答で生成対象を確認し、次の発言で了承を得てください。今回変更した案は先に提示してください。')
            elif authorization in ['user_request','front_approved']:
                sources=[self.text]+([x.get('text','') for x in previous] if authorization=='user_request' else [])
                instruction=a.get('instruction','').strip()
                if not instruction or not any(instruction in source for source in sources):raise ValueError('生成を許可した利用者の発言を原文で指定してください。')
                if authorization=='front_approved':
                    original=w.item(self.original,'characters',a['id'])
                    current=w.item(p,'characters',a['id'])
                    if not original.get('view_assets',{}).get('front') or original!=current:raise ValueError('提示済みの正面を変更せず使用してください。')
                    a=dict(a,views=[i for i,key in [(1,'side'),(2,'back')] if key not in current.get('view_assets',{})])
                    if not a['views']:raise ValueError('横面・背面は生成済みです。')
            else:raise ValueError('生成許可の種類が不正です。')
            kind='character' if any(c['id']==a['id'] for c in p['characters']) else 'scene'
            q=w.make_quote(p,kind,a['id'],a)
            completion=w.string(a.get('completion_message',''),1500)
            if completion:q['completion_message']=completion
            q['consent']={'text':self.text,'at':time.time(),'via':'agent_tool','confirmation_id':a.get('confirmation_id'),'authorization':authorization,'instruction':a.get('instruction')}
            p['quotes']={q['id']:q};self.execute=q['id']
            return {'scheduled':True,'image_count':len(q['panels']),'selected_indices':q['panels'],'status':'回答後に対象全枚を生成し、全て成功した後にまとめて画像と完了案内を表示します。まだ画像は完成していません。'}
        if name=='cancel_generation':self.invalidate();return {'cancelled':True}
        raise ValueError('ツールが見つかりません。')
    def update_scene(self,scene,a):
        panels=a['panels'];ids=a['selected_panels'];count=len(w.LAYOUTS[scene['layout']][1])
        if len(panels)!=count or not ids or any(type(i) is not int or not 0<=i<count for i in ids):raise ValueError('コマ数・変更対象が不正です。')
        validated=[]
        for i,panel in enumerate(panels):
            bubbles=manga.dialogues(panel)
            if any(not 0<=b['speaker']<len(scene['characters']) for b in bubbles):raise ValueError('吹き出しの話者が不正です。')
            manga.bubble_layout(bubbles,publication.panel_size(scene))
            item={'direction':w.string(panel['direction'],800),'text':''.join(b['text'] for b in bubbles),'speaker':panel['speaker'],'bubble_side':panel['bubble_side'],'held':False,'asset':None}
            if type(item['speaker']) is not int or not 0<=item['speaker']<len(scene['characters']) or item['bubble_side'] not in ['right','left']:raise ValueError('話者/吹き出しが不正です。')
            if 'bubbles' in panel:item['bubbles']=copy.deepcopy(bubbles)
            old=scene['panels'][i] if i<len(scene['panels']) else None
            if old and (old['held'] or i not in ids):
                if any(item[k]!=old[k] for k in ['direction','text','speaker','bubble_side']) or manga.dialogues(item)!=manga.dialogues(old):raise ValueError('保持/対象外のコマを変更できません。')
                item=old
            elif old and all(item[k]==old[k] for k in ['direction','speaker']):
                item['asset']=copy.deepcopy(old['asset'])
                if item['asset'] and manga.dialogues(item)!=manga.dialogues(old):
                    dest=w.folder(self.p)/'panel.png'
                    manga.letter_panel(Image.open(s.DATA/item['asset']['raw']),item,publication.panel_size(scene)).save(dest)
                    item['asset']['file']=w.relative(dest)
            validated.append(item)
        if any(not any(line in x['text'] for x in validated) for line in scene.get('fixed_lines',[])):raise ValueError('固定セリフを保持してください。')
        scene.update(title=w.string(a['title'],100),summary=w.string(a['summary'],800),panels=validated,output=None)
        if validated and all(x['asset'] for x in validated):scene['output']=w.assemble(self.p,scene)
        if scene['output']:self.artifact('image',images=w.scene_preview_images(scene))
