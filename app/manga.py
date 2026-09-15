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
    if not isinstance(text,str) or len(text)>120:raise ValueError('吹き出しのセリフは120文字までです。')
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

def dialogues(panel):
    bubbles=panel.get('bubbles')
    if bubbles is None:bubbles=[{k:panel.get(k, 'right' if k=='bubble_side' else 0 if k=='speaker' else '') for k in ['text','speaker','bubble_side']}]
    if not isinstance(bubbles,list) or not 1<=len(bubbles)<=4:raise ValueError('1コマの吹き出しは1〜4つにしてください。')
    for bubble in bubbles:
        validate_dialogue(bubble.get('text'))
        if bubble.get('bubble_side') not in ['right','left'] or type(bubble.get('speaker')) is not int:raise ValueError('吹き出しの位置・話者を確認してください。')
    return bubbles


def bubble_layout(bubbles,size):
    width,height=size; result=[];occupied={'right':0,'left':0}
    count=len(bubbles);capacity=2 if count>2 or len({b['bubble_side'] for b in bubbles})<count else 1
    for bubble in bubbles:
        side=bubble['bubble_side']
        if occupied[side]>=capacity:side='left' if side=='right' else 'right'
        slot=occupied[side];occupied[side]+=1
        maxw=width*(.60 if count==1 else .44);maxh=height*(.78 if capacity==1 else .40)
        cols=columns(bubble['text']);rows=max([len(c) for c in cols] or [1])
        fs=min(28,int((maxw-32)/max(1,len(cols))/1.3),int((maxh-32)/rows/1.25))
        if fs<14:raise ValueError('このコマサイズにはセリフが収まりません。吹き出しの文字数を減らしてください。')
        bw=max(90,len(cols)*fs*1.3+32);bh=max(85,rows*fs*1.25+32)
        x=width-bw-20 if side=='right' else 20
        y=20 if slot==0 else height-bh-40
        result.append({'box':(x,y,x+bw,y+bh),'font_size':fs,'side':side,'text':bubble['text']})
    return result


def bubble_box(text,side,size=(1280,720)):
    return bubble_layout([{'text':text,'bubble_side':side}],size)[0]['box']


def art_prompt(work,shot):
    import json
    size=work.get('panel_size',(1280,720));box=[x['box'] for x in bubble_layout(dialogues(shot),size)]
    return '''Draw exactly ONE panel of an original Japanese FULL-COLOR manga. Apply the requested art direction to linework, shading, proportions and color palette. Use confident manga ink contours. Preserve manga composition and acting, not a generic standalone illustration. Natural stylized anatomy, believable hands, purposeful negative space, expressive acting and dynamic manga framing. Avoid generic glossy 3D rendering or photorealism. Honor the selected coloring technique, including watercolor-like washes, soft pastel colors or crisp cel shading. Do NOT divide into subpanels or collage. ABSOLUTELY NO TEXT anywhere: no letters, numbers, sound effects, logos, captions, symbols resembling writing, speech bubbles or empty balloons. Screens, books, newspapers, signs and labels must show blank surfaces or abstract non-text shapes only.
The speaking character must be visibly in this panel. Compose faces and important action OUTSIDE the following approximate area. DO NOT draw its bounding rectangle, box or outline; just leave unobstructed natural light background at these pixel coordinates (canvas size is specified below): '''+str(box)+'''. Keep this area simple/light with no outline or white shape. Keep the character below or inward from this area. Draw other characters only if needed by the scene. Color mode is FULL COLOR, including when an older reference or world description mentions black-and-white. For monochrome references retain the design and choose coherent colors guided by the character description. Keep EXACT hair shape, clothing construction/sleeves/accessories and identity from the reference, but use the new scene composition. Do not copy the reference's pose or framing. Do NOT shorten long hair: maintain the same hair length in ALL panels, especially after battle. Preserve clear ground plane and perspective.
'''+json.dumps({'canvas_size':size,'characters':work['characters'],'story':work['answers']['story'],'style':work['answers']['style'],'scene':shot['direction'],'speakers':[work['characters'][b['speaker']]['name'] for b in dialogues(shot)],'expression':shot['expression']},ensure_ascii=False)

def letter_panel(image,panel,size=(1280,720)):
    bubbles=dialogues(panel);im=normalize(image,size);d=ImageDraw.Draw(im)
    for layout in bubble_layout(bubbles,size):
        text=layout['text']
        if not text:continue
        x1,y1,x2,y2=layout['box'];fs=layout['font_size'];side=layout['side'];mid=(x1+x2)/2
        tip=(x1+12,y2+22) if side=='right' else (x2-12,y2+22)
        d.polygon([(mid-12,y2-10),tip,(mid+12,y2-10)],fill='white')
        d.line([(mid-12,y2-10),tip,(mid+12,y2-10)],fill='black',width=2)
        d.rounded_rectangle((x1,y1,x2,y2),radius=24,fill='white',outline='black',width=2)
        cols=columns(text);startx=(x1+x2)/2+(len(cols)-1)*fs*.65
        for col,units in enumerate(cols):
            for row,unit in enumerate(units):
                x=startx-col*fs*1.3;y=y1+16+row*fs*1.25
                if re.fullmatch('[A-Za-z0-9]{1,3}',unit):
                    f=ImageFont.truetype(FONT,max(10,int(fs*(1 if len(unit)==1 else .78 if len(unit)==2 else .60))))
                    d.text((x,y+fs/2),unit,font=f,fill='black',anchor='mm')
                else:
                    f=ImageFont.truetype(FONT,fs,layout_engine=ImageFont.Layout.RAQM)
                    d.text((x,y),unit,font=f,fill='black',direction='ttb',language='ja',anchor='mt',features=['vert'])
    return im


def letter(image,text,side='right',size=(1280,720)):
    return letter_panel(image,{'text':text,'bubble_side':side,'speaker':0},size)
