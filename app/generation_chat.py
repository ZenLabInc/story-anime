"""Conversational spending consent, bound to one unchanged server-side quote."""
import time
from app import studio as s, workspace as w, membership


def handle(user,pid,token,text,data,meta):
    execute=None
    with s.transaction() as db:
        p=s.get_work(db,user,pid)
        if not p.get('busy') or p['busy']['id']!=token:raise ValueError('処理が中断されました。')
        op=data['operation'];target=data.get('target');context=p.get('active_context') or 'world'
        if op=='quote_generation':
            kind='character' if any(c['id']==target for c in p['characters']) else 'scene'
            q=w.make_quote(p,kind,target,data)
            p['quotes']={q['id']:q};context=target
            label=w.item(p,'characters' if kind=='character' else 'scenes',target)['name' if kind=='character' else 'title']
            directions='・'.join(['正面','横面','背面'][i] for i in q['panels']) if kind=='character' else '・'.join(str(i+1)+'コマ目' for i in q['panels'])
            _,plan=membership.plan(db,user)
            percent=q['cap_jpy']/membership.USD_JPY/plan['monthly_budget_usd']*100 if plan['monthly_budget_usd'] else 0
            reply=f'「{label}」の{directions}を生成します。月間利用枠の最大{percent:.1f}%を使用する見込みです。完了後に実際の使用量へ調整します。\nこの内容で進めてよいですか？「お願いします」や、変更したい点を返信してください。見積もりは10分間有効です。'
            if not plan['monthly_budget_usd']:reply=f'「{label}」の{directions}をご自身のGemini APIキーで生成します。Google側のAPI利用料はご本人の負担です。生成してよいですか？'
        elif op=='confirm_generation':
            q=p.get('quotes',{}).get(data.get('quote_id'))
            if not q or q['status']!='ready' or q['revision']!=p['revision'] or q['expires']<time.time() or q['target']!=target:
                p['quotes']={};reply='見積もりが変更済みか期限切れです。生成は行っていません。生成したい対象を教えてください。消費量を改めてご案内します。'
            else:
                execute=q['id'];context=q['target'];q['revision']=p['revision']+1
                q['consent']={'text':text,'at':time.time(),'via':'llm_chat'}
                reply='提示した消費量で生成を開始します。失敗時は自動再試行せず、生成できた画像を保存します。'
        elif op=='cancel_generation':
            p['quotes']={};reply='生成を取りやめました。画像枠は消費していません。続けて相談できます。'
        else:
            scene=w.item(p,'scenes',target);ids=data.get('panels');held=data.get('held')
            if scene['confirmed'] or type(held) is not bool or not isinstance(ids,list) or not ids or any(type(i) is not int or not 0<=i<len(scene['panels']) for i in ids):raise ValueError('保持するコマを確認してください。確定シーンは変更できません。')
            for i in ids:scene['panels'][i]['held']=held
            p['quotes']={};context=target
            reply='・'.join(str(i+1)+'コマ目' for i in ids)+('を保持しました。生成対象から外します。' if held else 'の保持を解除しました。画像はまだ生成しません。')
        p['active_context']=context
        w.history(p,context,text,reply);p['chats'][-1]['api']=meta;p['busy']=None;p['error']=None
        w.save(db,p)
    if execute:
        try:return w.generate(user,{'id':pid,'quote_id':execute})
        except Exception as error:
            with s.transaction() as db:
                p=s.get_work(db,user,pid)
                # Even pre-flight failures require fresh consent; never leave a retryable quote.
                p['quotes']={};p['error']=str(error)
                w.history(p,context,'','生成を完了できませんでした。生成済みの画像は保持しています。再開する場合は「残りを生成して」と教えてください。消費量を改めて確認します。')
                return w.save(db,p)
    return p
