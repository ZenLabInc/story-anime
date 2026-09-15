"""Snapshot-bound, local confirmation buttons; no generation or model calls."""
import hashlib
from app import studio as s, workspace as w


def proposal(p,target):
    if target=='world':
        if not p.get('world_draft') or p['world_draft']==p['world']['text']:return None
        return ('world','世界観を確定する',p['world_draft'],{})
    c=next((x for x in p['characters'] if x['id']==target),None)
    if c:
        if not c.get('asset') or not c.get('name') or c['name']=='新しいキャラ':return None
        scope='profile' if c.get('personality') and c.get('speech') else 'appearance'
        snapshot={k:c.get(k) for k in ['name','appearance','personality','speech','background','asset']}
        approved=next((v for v in c.get('versions',[]) if v['id']==c.get('approved')),None)
        # Explicit confirmation state is reset by edits; also compare saved profile.
        if c.get('visual_state')=='confirmed' and (scope=='appearance' or c.get('persona_state')=='confirmed'):
            if approved and approved.get('asset')==c.get('asset') and all(approved.get('profile',{}).get(k,'')==c.get(k,'') for k in (['name','appearance','background']+(['personality','speech'] if scope=='profile' else []))):return None
        return ('character','キャラクターを確定する',snapshot,{'scope':scope})
    scene=next((x for x in p['scenes'] if x['id']==target),None)
    if not scene or scene.get('confirmed') or not scene.get('output'):return None
    return ('scene','このシーンを確定する',{k:scene.get(k) for k in ['panels','output','title','summary']},{})


def digest(value):return hashlib.sha256(s.dump(value).encode()).hexdigest()


def attach(p,target=None):
    for chat in p.get('chats',[]):
        old=chat.get('confirmation')
        if old and old.get('status')=='pending':
            current=proposal(p,old['target'])
            if not current or digest(current[2])!=old['digest']:old['status']='superseded'
    target=target or p.get('active_context')
    value=proposal(p,target)
    if not value or not p.get('chats'):return
    kind,label,snapshot,args=value
    for chat in p['chats']:
        old=chat.get('confirmation')
        if old and old['target']==target and old.get('status')=='pending':old['status']='superseded'
    p['chats'][-1]['confirmation']={'kind':kind,'target':target,'label':label,'digest':digest(snapshot),'args':args,'status':'pending'}


def accept(user,body):
    from app.agent_tools import Toolset
    with s.transaction() as db:
        p=w.load(db,user,body['id'],body['revision'])
        chat=next((x for x in p['chats'] if x['id']==body['message_id']),None)
        request=chat.get('confirmation') if chat else None
        if not request or request['status']!='pending':raise ValueError('この確認は完了済み、または新しい案に置き換わっています。')
        current=proposal(p,request['target'])
        if not current or digest(current[2])!=request['digest']:raise ValueError('案が更新されています。最新の内容をチャットで確認してください。')
        tool=Toolset(p,user,request['label'])
        kind=request['kind']
        args={} if kind=='world' else {'id':request['target'],**request['args']}
        tool.call('confirm_'+kind,args)
        # Toolset may update dictionaries; retrieve the stored message again.
        next(x for x in p['chats'] if x['id']==body['message_id'])['confirmation']['status']='accepted'
        reply='世界観を確定しました。次は登場人物を考えましょう。' if kind=='world' else 'キャラクターを確定しました。次に描きたい場面を教えてください。' if kind=='character' else 'シーンを確定しました。続きを作るか、PNG・無音動画としてダウンロードできます。希望を話してください。'
        w.history(p,request['target'],request['label'],reply)
        return w.save(db,p)
