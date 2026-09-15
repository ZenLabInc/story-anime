"""Approved publication presets, deterministic composition and reusable exports."""
import copy, subprocess, shutil, zipfile
from pathlib import Path
from PIL import Image, ImageDraw
from app import art_direction, studio as s

PRESETS={
 'shorts':{'label':'ショート動画','description':'縦型9:16・1画面1コマ・5秒ずつ表示する無音MP4','size':[1080,1920],'panel_size':[720,1280],'panel_aspect':'9:16','layouts':['single','two','three','four']},
 'scroll':{'label':'縦読み漫画','description':'幅1080px・上から順に読む縦スクロール・PNGと分割画像ZIP','size':[1080,0],'panel_size':[864,1080],'panel_aspect':'4:5','layouts':['single','two','three','four']},
 'page-two':{'label':'ページ漫画・上下2コマ','description':'1080×1536px・上→下・PNG','size':[1080,1536],'panel_size':[1280,720],'panel_aspect':'16:9','layouts':['two']},
 'page-four':{'label':'ページ漫画・4コマ','description':'1080×1536px・右上→左上→右下→左下・PNG','size':[1080,1536],'panel_size':[864,1080],'panel_aspect':'4:5','layouts':['four']},
}

def catalog():return [{'id':k,**v} for k,v in PRESETS.items()]
def spec(scene):return scene.get('publication')
def panel_size(scene):return tuple(spec(scene)['panel_size']) if spec(scene) else (1280,720)
def proposal(preset,destination):
    if preset not in PRESETS:raise ValueError('用意した掲載形式から選んでください。')
    return {'preset':preset,'destination':str(destination)[:120],**copy.deepcopy(PRESETS[preset]),'output_aspect':('9:16' if preset=='shorts' else 'variable' if preset=='scroll' else '45:64')}

def compose(scene,images):
    f=spec(scene);key=f['preset'];width,height=f['size']
    if key=='shorts':return art_direction.normalize(images[0],(width,height))
    if key=='scroll':
        height=len(images)*1350+(len(images)-1)*48
        boxes=[(0,i*1398,1080,1350) for i in range(len(images))]
    elif key=='page-two':boxes=[(40,170,1000,563),(40,803,1000,563)]
    else:boxes=[(556,80,484,605),(40,80,484,605),(556,851,484,605),(40,851,484,605)]
    page=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(page)
    for im,(x,y,w,h) in zip(images,boxes):
        page.paste(art_direction.normalize(im,(w,h)),(x,y));draw.rectangle((x,y,x+w-1,y+h-1),outline='black',width=2)
    return page

def export(p,scenes,preset):
    from app import workspace as w
    if not scenes or len(scenes)>6:raise ValueError('一度に書き出せるシーンは1〜6件です。')
    f=proposal(preset,'書き出し');files=[];images=[]
    signature=[(panel.get('asset') or {}).get('file') for scene in scenes for panel in scene['panels']]
    if not signature or len(signature)>24:raise ValueError('一度に1〜24コマまで書き出せます。')
    for previous in reversed(p.get('exports',[])):
        if previous.get('source_files')==signature and previous.get('scenes')==[x['id'] for x in scenes] and previous['preset']==preset and all((s.DATA/x['path']).is_file() for x in previous['files']):return previous
    dest=w.folder(p)
    for scene in scenes:
        if not scene['panels'] or any(not x.get('asset') for x in scene['panels']):raise ValueError('画像を完成させてから書き出してください。')
        for panel in scene['panels']:
            with Image.open(s.DATA/panel['asset']['file']) as im:images.append(im.convert('RGB'))
    if len(images)>24:raise ValueError('一度に24コマまで書き出せます。')
    if preset=='shorts':
        if not shutil.which('ffmpeg'):raise ValueError('動画書き出し環境が未設定です。')
        for i,im in enumerate(images):art_direction.normalize(im,(1080,1920)).save(dest/f'frame-{i:03}.png')
        out=dest/'shorts.mp4'
        subprocess.run(['ffmpeg','-nostdin','-y','-loglevel','error','-framerate','1/5','-i',str(dest/'frame-%03d.png'),'-vf','fps=24','-c:v','libx264','-threads','2','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(out)],check=True,timeout=180,capture_output=True)
        files=[{'path':w.relative(out),'label':'MP4をダウンロード（無音・1コマ5秒）'}]
        for path in dest.glob('frame-*.png'):path.unlink()
    else:
        # Each strip/page is bounded in height; ZIP also contains individual panels.
        chunk=2 if preset=='page-two' else 4
        for start in range(0,len(images),chunk):
            part=images[start:start+chunk];out=dest/f'page-{start//chunk+1:02}.png';compose({'publication':f},part).save(out)
            files.append({'path':w.relative(out),'label':f'{start//chunk+1}ページ目のPNG'})
        for i,im in enumerate(images):im.save(dest/f'panel-{i+1:02}.png')
        archive=dest/'manga.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(dest.glob('*.png')):z.write(path,path.name)
        files.append({'path':w.relative(archive),'label':'ページ・コマ画像ZIP'})
    record={'id':s.uid(),'preset':preset,'scenes':[x['id'] for x in scenes],'files':files,'source_files':signature}
    p.setdefault('exports',[]).append(record)
    return record
