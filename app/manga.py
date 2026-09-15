"""Manga-specific art direction and deterministic in-panel Japanese lettering."""
import math, re, unicodedata
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, features
from app.art_direction import normalize
from app.render import FONT

@lru_cache(maxsize=1)
def font():
    if not FONT or not features.check_feature('raqm'):raise ValueError('日本語縦書きフォントの実行環境を確認してください。')
    return ImageFont.truetype(FONT,28,layout_engine=ImageFont.Layout.RAQM)

def validate_dialogue(text):
    if not isinstance(text,str) or len(text)>55:raise ValueError('吹き出しのセリフは55文字までです。')
    f=font();missing=bytes(f.getmask(chr(0x10ffff)))
    for ch in text:
        if unicodedata.category(ch).startswith('C') or (not ch.isspace() and bytes(f.getmask(ch))==missing):
            raise ValueError('表示できない文字がセリフに含まれます。一般的な日本語・英数字へ置き換えてください。')
    return text

def columns(text):
    # Keep short Latin/number runs upright; avoid closing punctuation at a column start.
    units=re.findall(r'[A-Za-z0-9]{1,3}|.',text)
    result=[];current=[]
    for unit in units:
        if len(current)>=12 or (len(current)>=10 and unit not in '、。，．！？!?）」』】〉》…ー'):
            if current[-1] in '（「『【〈《':carry=current.pop();result.append(current);current=[carry]
            else:result.append(current);current=[]
        current.append(unit)
    if current:result.append(current)
    return result

def bubble_box(text,side,size=(1280,720)):
    cols=columns(text);rows=max([len(c) for c in cols] or [1])
    width=max(150,len(cols)*36+64);height=max(140,rows*34+64)
    x=size[0]-width-35 if side=='right' else 35
    return (x,30,x+width,30+height)

def art_prompt(work,shot):
    import json
    size=work.get('panel_size',(1280,720));box=bubble_box(shot['text'],shot.get('bubble_side','right'),size)
    return '''Draw exactly ONE panel of an original Japanese FULL-COLOR manga. Apply the requested art direction to linework, shading, proportions and color palette. Use confident manga ink contours. Preserve manga composition and acting, not a generic standalone illustration. Natural stylized anatomy, believable hands, purposeful negative space, expressive acting and dynamic manga framing. Avoid generic glossy 3D rendering or photorealism. Honor the selected coloring technique, including watercolor-like washes, soft pastel colors or crisp cel shading. Do NOT divide into subpanels or collage. ABSOLUTELY NO TEXT anywhere: no letters, numbers, sound effects, logos, captions, symbols resembling writing, speech bubbles or empty balloons. Screens, books, newspapers, signs and labels must show blank surfaces or abstract non-text shapes only.
The speaking character must be visibly in this panel. Compose faces and important action OUTSIDE the following approximate area. DO NOT draw its bounding rectangle, box or outline; just leave unobstructed natural light background at these pixel coordinates (canvas size is specified below): '''+str(box)+'''. Keep this area simple/light with no outline or white shape. Keep the character below or inward from this area. Draw other characters only if needed by the scene. Color mode is FULL COLOR, including when an older reference or world description mentions black-and-white. For monochrome references retain the design and choose coherent colors guided by the character description. Keep EXACT hair shape, clothing construction/sleeves/accessories and identity from the reference, but use the new scene composition. Do not copy the reference's pose or framing. Do NOT shorten long hair: maintain the same hair length in ALL panels, especially after battle. Preserve clear ground plane and perspective.
'''+json.dumps({'canvas_size':size,'characters':work['characters'],'story':work['answers']['story'],'style':work['answers']['style'],'scene':shot['direction'],'speaker':work['characters'][shot['speaker']]['name'],'expression':shot['expression']},ensure_ascii=False)

def letter(image,text,side='right',size=(1280,720)):
    validate_dialogue(text)
    im=normalize(image,size)
    if not text:return im
    d=ImageDraw.Draw(im);x1,y1,x2,y2=bubble_box(text,side,size)
    mid=(x1+x2)//2
    tip=(x1-25,y2+45) if side=='right' else (x2+25,y2+45)
    d.polygon([(mid-22,y2-12),tip,(mid+20,y2-12)],fill='white')
    d.line([(mid-22,y2-12),tip,(mid+20,y2-12)],fill='black',width=3)
    d.rounded_rectangle((x1,y1,x2,y2),radius=40,fill='white',outline='black',width=3)
    d.rectangle((mid-17,y2-6,mid+14,y2+1),fill='white')
    cols=columns(text);startx=(x1+x2)/2+(len(cols)-1)*18
    for col,units in enumerate(cols):
        for row,unit in enumerate(units):
            x=startx-col*36;y=y1+32+row*34
            if re.fullmatch('[A-Za-z0-9]{1,3}',unit):
                size=28 if len(unit)==1 else 22 if len(unit)==2 else 17
                f=ImageFont.truetype(FONT,size)
                d.text((x,y+15),unit,font=f,fill='black',anchor='mm')
            else:d.text((x,y),unit,font=font(),fill='black',direction='ttb',language='ja',anchor='mt',features=['vert'])
    return im
