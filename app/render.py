"""Offline animatic renderer. Procedural figures are NOT generative anime or lip sync."""
import array
import glob
import math
import os
from pathlib import Path
import subprocess
import textwrap
import wave
from PIL import Image, ImageDraw, ImageFont

FONT = os.environ.get('YOURSTORY_FONT') or next(iter(glob.glob('/System/Library/Fonts/ヒラ*W3.ttc')+glob.glob('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')),None)

def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)

def frame(project, shot, t=0, talking=False):
    im = Image.new('RGB', (1280, 720), '#18263b')
    d = ImageDraw.Draw(im)
    font = lambda n: ImageFont.truetype(FONT, n) if FONT else ImageFont.load_default()
    d.rectangle((0, 445, 1280, 720), fill='#273c50')
    d.ellipse((925, 60, 1055, 190), fill='#eacb91')
    for i, c in enumerate(project['characters']):
        x = 430 + i * 400
        y = int(280 + 4 * math.sin(t * 2 + i))
        coat = c['color']
        d.rounded_rectangle((x-65, y+65, x+65, 560), 35, fill=coat)
        d.ellipse((x-58, y-55, x+58, y+75), fill='#efd4bc')
        d.pieslice((x-62,y-65,x+62,y+60), 175, 355, fill='#232431')
        blink = t % 3.6 > 3.45
        for dx in [-23, 23]:
            d.line((x+dx-6,y+14,x+dx+6,y+14), fill='#263343', width=4) if blink else d.ellipse((x+dx-4,y+9,x+dx+4,y+20),fill='#263343')
        if talking and shot['speaker'] == i:
            d.ellipse((x-10,y+39,x+10,y+51), fill='#805963')
        elif shot['expression'] == 'smile':
            d.arc((x-17,y+25,x+17,y+48), 0, 180, fill='#805963',width=3)
        else:
            d.line((x-12,y+42,x+12,y+42), fill='#805963',width=3)
        d.text((x-75,565),c['name'],font=font(24),fill='#f5ede0')
    d.text((40,28),'STORY ANIME / LOCAL ANIMATIC',font=font(21),fill='#a9c9d7')
    d.text((40,80),shot['direction'][:40],font=font(26),fill='#f5ede0')
    d.rectangle((0,610,1280,720), fill='#101925')
    for i, line in enumerate(textwrap.wrap(shot['text'], 38)):
        d.text((65,620+i*39),line,font=font(28),fill='#fff4e4')
    return im

def render(project, shot, folder):
    folder.mkdir(parents=True, exist_ok=True)
    frame(project, shot).save(folder/'board.png')
    text = shot['text']
    levels = []
    if text.strip():
        (folder/'speech.txt').write_text(text)
        voice = project['characters'][shot['speaker']]['voice']
        run(['say','-v',voice,'-r','230','-f',str(folder/'speech.txt'),'-o',str(folder/'speech.aiff')])
        run(['ffmpeg','-y','-i',str(folder/'speech.aiff'),'-ar','16000','-ac','1',str(folder/'speech.wav')])
        with wave.open(str(folder/'speech.wav')) as w:
            duration=w.getnframes()/w.getframerate()
            samples=array.array('h', w.readframes(w.getnframes()))
        if duration + shot['pause'] > 5:
            raise ValueError('音声が5秒に収まりません。セリフを短くするか、間を減らしてください（自動切断はしません）。')
        for n in range(125):
            start=int((n/25-shot['pause'])*16000)
            chunk=samples[max(0,start):max(0,start+640)] if start>=0 else []
            levels.append(bool(chunk) and max(abs(x) for x in chunk)>750)
        run(['ffmpeg','-y','-i',str(folder/'speech.wav'),'-af',f"adelay={int(shot['pause']*1000)}:all=1,apad",'-t','5','-ar','48000','-ac','2',str(folder/'audio.wav')])
    else:
        run(['ffmpeg','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','5',str(folder/'audio.wav')])
    # Audio-amplitude mouth opening is an explicit placeholder, not phoneme alignment.
    args=['ffmpeg','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1280x720','-r','25','-i','-','-i',str(folder/'audio.wav'),'-c:v','libx264','-preset','ultrafast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-t','5','-movflags','+faststart',str(folder/'clip.mp4')]
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as p:
        try:
            for n in range(125):
                p.stdin.write(frame(project,shot,n/25,levels[n] if levels else False).tobytes())
            p.stdin.close()
            if p.wait(timeout=120):
                raise RuntimeError('MP4生成に失敗しました')
        except BaseException:
            p.kill()
            p.wait()
            raise
    return {'video':'clip.mp4','image':'board.png','audio':'audio.wav','provider':'local-procedural + macOS-say','external_cost_jpy':0}
