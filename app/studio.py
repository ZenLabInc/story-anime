"""Chat-first local studio. No external AI calls. SQLite owns permissions and credits."""
import copy
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from scripts.cost_model import load_config, studio_quote
from app import gemini

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.local' / 'studio'
DB = DATA / 'studio.db'
CONFIG = load_config()
STEPS = ['mode', 'characters', 'story', 'fixed', 'style', 'review']
QUESTIONS = {
    'mode': '漫画とアニメ、どちらを作りたいですか？ 漫画は4コマ・20cr、アニメは30秒・240crが初回の目安です。',
    'characters': 'どんな人物を登場させたいですか？ 2人まで、名前と特徴を教えてください。2人なら「アオ：無口な旅人／ユイ：明るい案内人」のように区切れます。',
    'story': 'どんな話にしましょう？ 舞台と、始まりから結末までをざっくり教えてください。決まっていなければ「おまかせ」でも大丈夫です。',
    'fixed': 'そのまま残したいセリフはありますか？ 55文字以内で教えてください。結末や演出は先ほどのあらすじと一緒に台本で確認できます。なければ「なし」。',
    'style': 'どんな雰囲気にしたいですか？ 「やさしい」「クール」「モノクロ」から選ぶか、希望を書いてください。ローカル版では色調だけを切り替えます。',
}


def uid(): return uuid.uuid4().hex

def dump(v): return json.dumps(v, ensure_ascii=False)

@contextmanager
def transaction():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with transaction() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, balance INTEGER NOT NULL CHECK(balance>=0));
        CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), data TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, quote_id TEXT UNIQUE NOT NULL, work TEXT NOT NULL REFERENCES works(id), owner TEXT NOT NULL REFERENCES users(id), data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), job TEXT NOT NULL, kind TEXT NOT NULL, delta INTEGER NOT NULL, UNIQUE(job,kind));
        CREATE TABLE IF NOT EXISTS likes(work TEXT REFERENCES works(id), user TEXT REFERENCES users(id), PRIMARY KEY(work,user));
        ''')
        # No automatic resend after interruption; unused reservation is refunded once.
        for row in db.execute('SELECT * FROM jobs').fetchall():
            j = json.loads(row['data'])
            if j['status'] == 'running':
                settle_failure(db, j, 'サーバーが再起動したため中断しました。予約は返還済みです。')

    from app import accounts, membership
    accounts.init();membership.init()
    from app import billing
    billing.init()
    from app import metrics
    # Keep product and measurement rows in the same SQLite backup/restore unit.
    metrics.DB = DB
    metrics.init(DB)


def session(token=None):
    hashed = hashlib.sha256((token or '').encode()).hexdigest()
    with transaction() as db:
        row = db.execute('SELECT id,name,balance FROM users WHERE token_hash=?', (hashed,)).fetchone()
        if row: return dict(row), None
        token = secrets.token_urlsafe(32)
        user = {'id': uid(), 'name': 'ゲスト', 'balance': CONFIG['studio']['initial_credits']}
        user['name'] += user['id'][:4]
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user['id'], hashlib.sha256(token.encode()).hexdigest(), user['name'], user['balance']))
        return user, token


def authenticate(token):
    with transaction() as db:
        row = db.execute('SELECT id,name,balance FROM users WHERE token_hash=?', (hashlib.sha256((token or '').encode()).hexdigest(),)).fetchone()
        if not row: raise PermissionError('セッションがありません。画面を開き直してください。')
        return dict(row)


def get_work(db, user, wid):
    row = db.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
    if not row or row['owner'] != user: raise PermissionError('この作品は開けません。')
    work=json.loads(row['data'])
    if work.get('deleted_at'):raise PermissionError('削除済みの漫画です。')
    return work


def put(db, w):
    db.execute('UPDATE works SET data=?,updated=? WHERE id=?', (dump(w), time.time(), w['id']))


def message(w, role, text):
    w['messages'].append({'id': uid(), 'role': role, 'text': text})


def create(user):
    w = {'provider': 'gemini' if gemini.ENABLED else 'local_demo', 'id': uid(), 'owner': user, 'title': '新しい物語', 'revision': 1, 'approved': None,
         'step': 'mode', 'mode': None, 'answers': {}, 'characters': [], 'shots': [], 'messages': [],
         'reference': None, 'history': [], 'quote': None, 'job': None, 'output': None, 'published': None}
    message(w, 'assistant', 'あなたが原作者です。作りたいものを、少しずつ聞かせてください。\n' + QUESTIONS['mode'])
    with transaction() as db:
        db.execute('INSERT INTO works VALUES(?,?,?,?)', (w['id'], user, dump(w), time.time()))
    return w


def snapshot(w):
    return copy.deepcopy({k: w.get(k) for k in ['profile', 'reference', 'step', 'mode', 'answers', 'characters', 'shots', 'title', 'output']})


def checkpoint(w):
    w['history'].append(snapshot(w))
    w['history'] = w['history'][-30:]


def changed(w):
    w['revision'] += 1
    w['approved'] = None
    w['quote'] = None


def ensure_idle(w):
    if w['job'] and w['job']['status'] == 'running': raise ValueError('生成中です。完了してから編集してください。')


def check_revision(w, revision):
    if revision != w['revision']: raise ValueError('別の画面で更新されています。作品を開き直してください。')


def characters(text, style):
    parts = re.split(r'[／/\n]', text)
    colors = ['#80b8bb', '#c39496'] if style != 'モノクロ' else ['#77818a', '#a5a5a5']
    if style == 'クール': colors = ['#45649b', '#7865a0']
    people = []
    for i, part in enumerate(parts):
        pair = re.split('[：:]', part, maxsplit=1)
        name = pair[0].strip()
        if not name or len(name) > 20: raise ValueError('名前は20文字以内。特徴は「名前：特徴」の形で書けます。')
        people.append({'name': name, 'description': pair[1].strip() if len(pair) > 1 else '',
                       'color': colors[i], 'voice': 'Kyoko' if i == 0 else 'Eddy (日本語（日本）)'})
    return people


def draft(w):
    w['reference'] = None
    count = CONFIG['studio']['comic_panels' if w['mode'] == 'comic' else 'anime_shots']
    w['characters'] = characters(w['answers']['characters'], w['answers']['style'])
    # Explicitly a proposal template; user's complete synopsis is retained in answers and review.
    sentences = [x.strip() for x in re.split(r'[\n。！？]+', w['answers']['story']) if x.strip()]
    lines = ['ここから、始めよう。', '一緒なら、きっと大丈夫。', '少しだけ、勇気を出した。', 'また、会おう。']
    if count == 6: lines = lines[:3] + ['風の音が、聞こえた。', 'ふたりは、顔を見合わせた。'] + lines[3:]
    fixed = w['answers']['fixed']
    if fixed != 'なし': lines[-1] = fixed
    w['shots'] = [{'id': str(i + 1), 'text': lines[i], 'direction': sentences[min(i, len(sentences)-1)] if sentences else '静かな場面',
                   'speaker': i % len(w['characters']), 'pause': 0.3, 'expression': 'neutral', 'locked': False, 'asset': None}
                  for i in range(count)]
    w['title'] = sentences[0][:28] if sentences else 'はじまりの物語'
    w['step'] = 'review'
    message(w, 'assistant', '人物と台本案を用意しました。台詞はローカルの定型提案です。あらすじの意味に沿ったAI脚本ではないため、下の台本を確認して直してください。\n「2コマ目のセリフを『…』に」「1場面目を保持」のように伝えられます。')


def chat(user, wid, text, revision, proposal=None, reply=None, ai_meta=None):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000: raise ValueError('1〜1000文字で入力してください。')
    text = text.strip()
    with transaction() as db:
        w = get_work(db, user, wid); ensure_idle(w); check_revision(w, revision)
        message(w, 'user', text)
        if text in ['戻る', 'ひとつ前へ戻す']:
            if not w['history']: raise ValueError('戻れる履歴はありません。')
            w.update(w['history'].pop()); changed(w)
            message(w, 'assistant', 'ひとつ前の編集内容に戻しました。消費済みクレジットは戻りません。\n' + QUESTIONS.get(w['step'], '台本を再確認してください。'))
        elif w['step'] != 'review':
            checkpoint(w)
            step = w['step']
            if step == 'mode':
                modes = {'漫画': 'comic', '漫画モード': 'comic', 'アニメ': 'anime', 'アニメモード': 'anime'}
                if text not in modes: raise ValueError('「漫画」か「アニメ」を選んでください。')
                w['mode'] = modes[text]
            elif step == 'characters':
                if text == 'おまかせ': text = 'アオ：無口な旅人／ユイ：明るい案内人'
                if not 1 <= len(re.split(r'[／/\n]', text)) <= 2: raise ValueError('登場人物は2人までです。')
                characters(text, 'やさしい')
            elif step == 'story' and text == 'おまかせ':
                text = '帰り道で二人が出会う。言えなかった気持ちを伝える。明日また会う約束をする。'
            elif step == 'fixed':
                if text in ['おまかせ', '特になし']: text = 'なし'
                if len(text) > 55: raise ValueError('固定セリフは55文字以内にしてください。')
            elif step == 'style' and text == 'おまかせ': text = 'やさしい'
            w['answers'][step] = text
            w['step'] = STEPS[STEPS.index(step) + 1]
            changed(w)
            if w['step'] == 'review':
                draft(w)
                if proposal:
                    w['title'] = proposal['title']
                    for shot, generated in zip(w['shots'], proposal['shots']): shot.update(generated)
                    w['messages'][-1]['text'] = 'Geminiが人物・あらすじに沿った台本案を作りました。固定セリフと結末、各コマの演出を確認してください。修正は番号を指定して伝えられます。'
            else: message(w, 'assistant', reply or QUESTIONS[w['step']])
        else:
            edit(w, text)
        if ai_meta: w.setdefault('ai_calls', []).append(ai_meta)
        put(db, w)
        return w


def edit(w, text):
    title = re.fullmatch(r'タイトル[をは：:]\s*(.+)', text)
    if title:
        if len(title[1]) > 40: raise ValueError('タイトルは40文字以内です。')
        checkpoint(w); w['title'] = title[1]; changed(w)
        # Export ZIP manifest contains the title, so it too must be regenerated.
        w['output'] = None
        message(w, 'assistant', 'タイトルを変更しました。台本を承認すると既存素材から無料で出力し直せます。'); return
    m = re.fullmatch(r'([1-6])(?:コマ|場面)目(?:の)?(.*)', text)
    if not m or int(m[1]) > len(w['shots']):
        message(w, 'assistant', 'ローカル版で変更できるのは、番号を指定したセリフ・演出メモ・表情・間・保持です。例：2コマ目のセリフを「また会おう」に。入力は保存しましたが、台本は変更していません。'); return
    shot = w['shots'][int(m[1])-1]; command = m[2].rstrip('。')
    if command in ['を保持', 'を保持する', '保持を解除', 'の保持を解除']:
        checkpoint(w); shot['locked'] = '解除' not in command; changed(w)
        message(w, 'assistant', f'{m[1]}番の保持を' + ('解除しました。' if not shot['locked'] else '設定しました。')); return
    if shot['locked']: raise ValueError('保持した部分です。先に「' + m[1] + 'コマ目の保持を解除」と伝えてください。')
    key, value = None, None
    line = re.fullmatch(r'(セリフ|演出メモ)を[「『](.*)[」』]に(?:して)?', command, re.DOTALL)
    if line:
        key = 'text' if line[1] == 'セリフ' else 'direction'; value = line[2]
        if len(value) > (55 if key == 'text' else 200): raise ValueError('セリフは55文字、演出メモは200文字以内です。')
        if key == 'text' and w['answers']['fixed'] != 'なし' and w['answers']['fixed'] in shot['text'] and w['answers']['fixed'] not in value: raise ValueError('その部分には固定セリフがあります。変更できません。')
    elif command in ['を微笑む表情に', 'を静かな表情に']:
        key, value = 'expression', 'smile' if '微笑む' in command else 'neutral'
    else:
        pause = re.fullmatch(r'間を([0-3](?:\.\d)?)秒に(?:して)?', command)
        if pause and w['mode'] == 'anime' and float(pause[1]) <= 3: key, value = 'pause', float(pause[1])
    if key is None:
        message(w, 'assistant', '変更を特定できませんでした。例：2コマ目のセリフを「また会おう」に。漫画の間や自由な動作の生成は、このローカル版にはありません。'); return
    if shot[key] == value:
        message(w, 'assistant', 'すでに同じ内容です。再生成は不要です。'); return
    checkpoint(w); old = shot[key]; shot[key] = value; shot['asset'] = None; w['output'] = None; changed(w)
    message(w, 'assistant', f'{m[1]}番だけ変更しました：{old} → {value}。他の部分はそのままです。台本を再承認すると、この部分だけを見積します。')


def approve(user, wid, revision):
    with transaction() as db:
        w = get_work(db, user, wid); ensure_idle(w); check_revision(w, revision)
        if w['step'] != 'review' or not w['shots']: raise ValueError('先に台本を作ってください。')
        ids = [s['id'] for s in w['shots'] if s['asset'] is None]
        if any(s['locked'] for s in w['shots'] if s['id'] in ids): raise ValueError('未生成の部分を保持しています。保持を解除してから生成してください。')
        w['approved'] = w['revision']
        if ids:
            values = studio_quote(w['mode'], len(ids), CONFIG)
            if w.get('provider') == 'gemini' and w['mode'] == 'comic':
                if not gemini.ENABLED: raise ValueError('この作品にはGemini接続が必要です。')
                values['reference_images'] = 1 if w.get('version') == 3 and not w.get('reference') else 0
                values['images'] += values['reference_images']
                values['external_api_cap_jpy'] = (len(ids)+values['reference_images'])*gemini.CONFIG['image_request_cap_jpy']
                values['external_api_cost_jpy'] = None
                values['kind'] = 'gemini'
                values['image_model'] = gemini.CONFIG['image_model']
            w['quote'] = dict(values, id=uid(), revision=w['revision'], mode=w['mode'], ids=ids, expires=time.time()+600)
            message(w, 'assistant', f'台本を承認しました。対象は{",".join(ids)}番、{values["credits"]}crです。下の見積を確認して実行してください。')
        else:
            w['quote'] = None
            message(w, 'assistant', '台本を承認しました。素材は揃っています。「出力する」で無料でまとめられます。')
        put(db, w); return w


def generate(user, wid, quote_id):
    with transaction() as db:
        w = get_work(db, user, wid)
        old = db.execute('SELECT data FROM jobs WHERE quote_id=? AND work=? AND owner=?', (quote_id, wid, user)).fetchone()
        if old: return json.loads(old['data'])
        ensure_idle(w); q = w['quote']
        if not q or q['id'] != quote_id or q['revision'] != w['revision'] or w['approved'] != w['revision'] or q['expires'] < time.time(): raise ValueError('見積が古くなりました。台本を承認し直してください。')
        if q.get('kind') == 'gemini':
            if not gemini.ENABLED: raise ValueError('Geminiは停止中です。')
            b = gemini.budget()
            if b['limit_jpy'] is not None and b['reserved_or_spent_jpy'] + q['external_api_cap_jpy'] > b['limit_jpy']: raise ValueError('検証の安全上限が不足しています。生成を開始しません。')
        balance = db.execute('SELECT balance FROM users WHERE id=?', (user,)).fetchone()[0]
        if balance < q['credits']: raise ValueError('デモクレジットが不足しています。追加購入や自動課金はありません。')
        j = {'id': uid(), 'quote_id': quote_id, 'work': wid, 'owner': user, 'revision': w['revision'], 'ids': q['ids'], 'credits': q['credits'], 'status': 'running', 'completed': 0, 'started': time.time(), 'external_api_cost_jpy': None if q.get('kind') == 'gemini' else 0, 'provider': q.get('kind', 'local_demo')}
        db.execute('UPDATE users SET balance=balance-? WHERE id=?', (q['credits'], user))
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?)', (uid(), user, j['id'], 'reserve', -q['credits']))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', (j['id'], quote_id, wid, user, dump(j)))
        w['job'] = j; put(db, w)
        frozen = copy.deepcopy(w)
    try:
        threading.Thread(target=worker, args=(frozen, j), daemon=True).start()
    except Exception:
        with transaction() as db: settle_failure(db, j, '生成処理を開始できませんでした。')
    return j


def settle_failure(db, j, error):
    if db.execute("SELECT 1 FROM ledger WHERE job=? AND kind IN ('release','settle')", (j['id'],)).fetchone(): return
    db.execute('UPDATE users SET balance=balance+? WHERE id=?', (j['credits'], j['owner']))
    db.execute('INSERT INTO ledger VALUES(?,?,?,?,?)', (uid(), j['owner'], j['id'], 'release', j['credits']))
    j.update(status='failed', error=error, elapsed=round(time.time()-j['started'], 2))
    db.execute('UPDATE jobs SET data=? WHERE id=?', (dump(j), j['id']))
    w = get_work(db, j['owner'], j['work']); w['job'] = j
    message(w, 'assistant', error + ' 予約したクレジットは返還しました。自動再試行はしません。'); put(db, w)


def worker(w, j):
    try:
        from app.studio_render import make_asset, assemble, prepare_reference
        prepare_reference(w)
        for shot in w['shots']:
            if shot['id'] not in j['ids']: continue
            shot['asset'] = make_asset(w, shot)
            j['completed'] += 1
            with transaction() as db:
                db.execute('UPDATE jobs SET data=? WHERE id=?', (dump(j), j['id']))
                current = get_work(db, j['owner'], w['id']); current['job'] = j; put(db, current)
        output = assemble(w)
        with transaction() as db:
            current = get_work(db, j['owner'], w['id'])
            if current['revision'] != j['revision']: raise ValueError('作品の版が変わったため適用しません。')
            checkpoint(current); current['shots'] = w['shots']; current['output'] = output
            if w.get('reference'): current['reference'] = w['reference']
            current['revision'] += 1; current['approved'] = current['revision']; current['quote'] = None
            j.update(status='succeeded', elapsed=round(time.time()-j['started'], 2)); current['job'] = j
            db.execute('UPDATE jobs SET data=? WHERE id=?', (dump(j), j['id']))
            db.execute('INSERT INTO ledger VALUES(?,?,?,?,?)', (uid(), j['owner'], j['id'], 'settle', 0))
            message(current, 'assistant', '作品ができました。気になる部分はこのチャットで修正できます。作品棚への掲載は、あなたが選ぶまで行いません。')
            put(db, current)
    except Exception as error:
        with transaction() as db:
            settle_failure(db, j, str(error) if isinstance(error, ValueError) else 'ローカル出力に失敗しました。音声とFFmpegの設定を確認してください。')


def export(user, wid, revision):
    from app.studio_render import assemble
    with transaction() as db:
        w = get_work(db, user, wid); ensure_idle(w); check_revision(w, revision)
        if w['approved'] != w['revision'] or any(s['asset'] is None for s in w['shots']) or not w['shots']: raise ValueError('台本を承認し、必要な部分を生成してください。')
        if w['output'] is None: w['output'] = assemble(w)
        put(db, w); return w


def publish(user, wid, revision, visible):
    if type(visible) is not bool: raise ValueError('公開状態が不正です。')
    with transaction() as db:
        w = get_work(db, user, wid); check_revision(w, revision)
        if visible:
            ensure_idle(w)
            if not w['output'] or any(s['asset'] is None for s in w['shots']) or w['approved'] != w['revision']: raise ValueError('確認済みの完成版を出力してから掲載してください。')
            w['published'] = {'revision': w['revision'], 'title': w['title'], 'mode': w['mode'], 'file': w['output']['file'], 'poster': w['output']['poster'], 'at': time.time(), 'kind': w['output'].get('kind','local_demo')}
        else: w['published'] = None
        put(db, w); return w


def like(user, wid, liked):
    if type(liked) is not bool: raise ValueError('いいね状態が不正です。')
    with transaction() as db:
        row = db.execute('SELECT data,owner FROM works WHERE id=?', (wid,)).fetchone()
        if not row or not json.loads(row['data'])['published']: raise PermissionError('公開作品が見つかりません。')
        if row['owner'] == user: raise ValueError('自分の作品にはいいねできません。')
        if liked: db.execute('INSERT OR IGNORE INTO likes VALUES(?,?)', (wid, user))
        else: db.execute('DELETE FROM likes WHERE work=? AND user=?', (wid, user))
    return {'ok': True}


def adapt(user, wid):
    with transaction() as db:
        source = get_work(db, user, wid); ensure_idle(source)
        if source['mode'] != 'comic' or not source['output']: raise ValueError('完成した漫画からアニメを作れます。')
        w = copy.deepcopy(source); w.update(id=uid(), revision=1, approved=None, mode='anime', title=source['title']+' — アニメ版', job=None, quote=None, output=None, published=None, history=[], messages=[])
        w['source_id'] = wid; w['answers']['mode'] = 'アニメ'
        w['shots'] = copy.deepcopy(source['shots'][:-1]) + [dict(source['shots'][-1], text='', direction='余韻を見せる'), dict(source['shots'][-1], text='', direction='相手の反応を見せる')] + [copy.deepcopy(source['shots'][-1])]
        for i, s in enumerate(w['shots']): s.update(id=str(i+1), asset=None, locked=False)
        message(w, 'assistant', '漫画を残したままアニメ版を作りました。4・5場面目は無音の余韻として追加した提案です。台本を確認してください。生成は新規見積で、元の漫画の素材を動画素材として流用しません。')
        db.execute('INSERT INTO works VALUES(?,?,?,?)', (w['id'], user, dump(w), time.time()))
        return w


def state(user):
    with transaction() as db:
        person = dict(db.execute('SELECT id,name,balance FROM users WHERE id=?', (user,)).fetchone())
        rows = db.execute('SELECT w.*,u.name FROM works w JOIN users u ON w.owner=u.id ORDER BY updated DESC').fetchall()
        mine, gallery = [], []
        for row in rows:
            w = json.loads(row['data'])
            if w.get('version') == 4: continue
            if row['owner'] == user: mine.append({'id': w['id'], 'title': w['title'], 'mode': w['mode'], 'step': w['step'], 'output': w['output'], 'published': bool(w['published'])})
            pub = w['published']
            if pub:
                total = db.execute('SELECT COUNT(*) FROM likes WHERE work=?', (w['id'],)).fetchone()[0]
                liked = bool(db.execute('SELECT 1 FROM likes WHERE work=? AND user=?', (w['id'], user)).fetchone())
                gallery.append(dict(pub, id=w['id'], author=row['name'], own=row['owner']==user, likes=total, liked=liked))
        gallery.sort(key=lambda p: p['at'], reverse=True)
        events = [dict(r) for r in db.execute('SELECT job,kind,delta FROM ledger WHERE owner=? ORDER BY rowid DESC LIMIT 20', (user,))]
        return {'user': person, 'mine': mine, 'gallery': gallery, 'ledger': events, 'runtime': 'gemini' if gemini.ENABLED else 'local_demo', 'api_budget': gemini.budget() if gemini.ENABLED else None, 'external_api_cost_jpy': None if gemini.ENABLED else 0}


def read_work(user, wid):
    with transaction() as db: return get_work(db, user, wid)


def file_path(user, path):
    parts = Path(path).parts
    if not parts or not re.fullmatch('[a-f0-9]{32}', parts[0]): raise PermissionError('素材が見つかりません。')
    target = (DATA / path).resolve()
    if not target.is_relative_to((DATA / parts[0]).resolve()) or not target.is_file(): raise PermissionError('素材が見つかりません。')
    with transaction() as db:
        row = db.execute('SELECT data,owner FROM works WHERE id=?', (parts[0],)).fetchone()
        if not row: raise PermissionError('素材が見つかりません。')
        w = json.loads(row['data'])
        if w.get('deleted_at'):raise PermissionError('削除済みの漫画の素材です。')
        if row['owner'] != user:
            pub = w['published']
            if not pub or path not in [pub['file'], pub['poster']]: raise PermissionError('この素材は非公開です。')
    if target.suffix not in ['.png', '.mp4', '.srt', '.zip']: raise PermissionError('取得できない形式です。')
    return target
