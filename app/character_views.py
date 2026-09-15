"""Generate independent views; side/back always reference the saved front image."""
from PIL import Image, ImageOps
from app import gemini, studio as s, art_direction
NAMES=('front','side','back')
LABELS=('正面','横面','背面')


def selected(c, requested=None):
    saved=c.get('view_assets',{})
    ids=requested if requested is not None else [i for i,name in enumerate(NAMES) if name not in saved]
    if not ids:ids=[0,1,2]
    if not isinstance(ids,list) or any(type(i) is not int or i not in range(3) for i in ids) or len(set(ids))!=len(ids):raise ValueError('生成する向きが不正です。')
    if 0 in ids and saved and set(ids)!={0,1,2}:raise ValueError('正面を作り直す場合は、横面・背面も新しい正面から生成します。')
    if 0 not in ids and 'front' not in saved:raise ValueError('先に正面を生成してください。')
    return sorted(ids)


def generate(user,p,q):
    from app import workspace as w
    c=w.item(p,'characters',q['target']);saved=dict(c.get('view_assets',{}))
    for i in q['panels']:
        name=NAMES[i];dest=w.folder(p);path=dest/(name+'.png')
        reference=None if i==0 else s.DATA/saved['front']['file']
        direction=['FRONT view, looking directly at the camera','SIDE profile view facing left, exactly 90 degrees from the front','BACK view, facing away from the camera, face not visible'][i]
        prompt='Original Japanese FULL-COLOR manga character. ONE character, ONE full-body '+direction+'. Pure solid WHITE background (#FFFFFF), no scenery, no floor shadows, no panels, no collage, no turnaround sheet, no text. Neutral standing pose, entire figure including feet visible. Expressive ink lines and clean cel shading. '
        style=p.get('art_style') if i==0 else c.get('art_style',p.get('art_style'))
        prompt+='Art direction: '+art_direction.prompt(style)+'. '
        if reference:prompt+='Use the attached FRONT image as the exact character reference. Preserve identity, hair/eye/skin/clothing colors, clothing construction and proportions. Change only viewpoint; infer hidden details consistently. '
        prompt+='Character: '+c['description']
        meta=gemini.image(p['id'],prompt,path,reference,aspect_ratio='2:3')
        meta['geometry']=art_direction.normalize_file(path,(768,1152))
        if i==0:saved={};c['art_style']=style
        saved[name]={'file':w.relative(path),'api':meta}
        with s.transaction() as db:
            fresh=s.get_work(db,user,p['id']);character=w.item(fresh,'characters',c['id'])
            character['art_style']=c.get('art_style');character['view_assets']=saved.copy();character['asset']=None;s.put(db,fresh)
    if all(name in saved for name in NAMES):
        dest=w.folder(p);sheet=Image.new('RGB',(1200,600),'white')
        for i,name in enumerate(NAMES):
            with Image.open(s.DATA/saved[name]['file']) as im:
                fitted=ImageOps.contain(im.convert('RGB'),(400,600));sheet.paste(fitted,(i*400+(400-fitted.width)//2,(600-fitted.height)//2))
        sheet.save(dest/'reference.png')
        asset={name:saved[name]['file'] for name in NAMES}
        asset.update(sheet=w.relative(dest/'reference.png'),method='front_reference_three_images',api={name:saved[name]['api'] for name in NAMES})
        with s.transaction() as db:
            fresh=s.get_work(db,user,p['id']);character=w.item(fresh,'characters',c['id']);character['asset']=asset
            if character.get('name_state')=='unasked' or character['name']=='新しいキャラ':character['name_state']='pending'
            s.put(db,fresh)
