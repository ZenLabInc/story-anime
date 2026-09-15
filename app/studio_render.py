"""Procedural placeholder media; manga path never invokes TTS or video generation."""
import hashlib
import json
import textwrap
import zipfile
from PIL import Image, ImageDraw, ImageFont
from app import studio, gemini, manga
from app.render import FONT, frame, render, run


def prepare_reference(work):
    if work.get('version') != 3 or work.get('provider') != 'gemini' or work.get('reference'): return
    folder = studio.DATA/work['id']/'assets'/studio.uid(); folder.mkdir(parents=True)
    prompt = 'Original Japanese BLACK AND WHITE manga character design reference sheet, expressive G-pen linework and screentones, white background. Draw ONLY these one or two characters, standing separately side by side, full body plus face closeups. Use precisely the hair LENGTH, silhouette, gender and clothes described; choose a distinct and repeatable costume for each. No story scene, no text, no lettering, no panels, no speech bubbles. Left to right in the list order: '+json.dumps(work['characters'],ensure_ascii=False)+'. A model must be able to reproduce each identity and hair length from this reference exactly.'
    meta = gemini.image(work['id'],prompt,folder/'reference.png')
    work['reference'] = str((folder/'reference.png').relative_to(studio.DATA))
    work['reference_api'] = meta


def make_asset(work, shot):
    aid = studio.uid(); folder = studio.DATA/work['id']/'assets'/aid
    folder.mkdir(parents=True)
    meta = None
    if work['mode'] == 'anime': render(work, shot, folder)
    elif work.get('provider') == 'gemini':
        import json
        reference = work.get('reference')
        prompt = 'Create ONE polished Japanese manga panel, cinematic composition, expressive original characters, high quality anime illustration. No text, no speech bubbles, no letters or captions. Landscape 16:9. Keep exact character identities, hair and clothes from the attached reference if provided. Draw this specific scene with its described action and expression, not a character sheet. Character definitions: '+json.dumps(work['characters'], ensure_ascii=False)+'\nStory: '+work['answers']['story']+'\nVisual style: '+work['answers']['style']+'\nThis panel direction: '+shot['direction']+'\nExpression: '+shot['expression']+'\nDialogue for emotional context only (do not draw text): '+shot['text']
        if work.get('version') == 3: prompt = manga.art_prompt(work,shot)
        meta = gemini.image(work['id'], prompt, folder/'raw.png', studio.DATA/reference if reference else None)
        with Image.open(folder/'raw.png') as source:
            source = source.convert('RGB'); source.thumbnail((1280, 560))
            image = Image.new('RGB', (1280,720), '#fcfaf5')
            image.paste(source, ((1280-source.width)//2, (560-source.height)//2))
        d = ImageDraw.Draw(image); font = ImageFont.truetype(FONT, 29)
        label = work['characters'][shot['speaker']]['name']+'：'+shot['text']
        for i, line in enumerate(textwrap.wrap(label, 38)): d.text((35,575+38*i),line,font=font,fill='#23313d')
        d.text((35,690),f'AI / Gemini · {shot["id"]}',font=ImageFont.truetype(FONT,18),fill='#666666')
        if work.get('version') == 3:
            with Image.open(folder/'raw.png') as raw: image = manga.letter(raw,shot['text'],shot.get('bubble_side','right'))
        image.save(folder/'board.png')
        if not reference: work['reference'] = str((folder/'raw.png').relative_to(studio.DATA))
    else:
        image = frame(work, dict(shot, text=''))
        # Vertical four-panel strip with independently replaceable panels and speech bubbles.
        d = ImageDraw.Draw(image); font = ImageFont.truetype(FONT, 28)
        d.rounded_rectangle((90, 138, 1190, 245), radius=28, fill='#fcfaf5', outline='#283643', width=3)
        for i, line in enumerate(textwrap.wrap(shot['text'], 36)):
            d.text((120, 153 + 38*i), line, font=font, fill='#23313d')
        d.text((35, 645), f'LOCAL COMIC / {shot["id"]}', font=font, fill='#dddddd')
        if work['answers']['style'] == 'モノクロ': image = image.convert('L').convert('RGB')
        image.save(folder/'board.png')
    filename = 'clip.mp4' if work['mode'] == 'anime' else 'board.png'
    return {'id': aid, 'file': str((folder/filename).relative_to(studio.DATA)),
            'image': str((folder/'board.png').relative_to(studio.DATA)),
            'sha256': hashlib.sha256((folder/filename).read_bytes()).hexdigest(), 'provider': 'gemini' if meta else 'local_demo', 'api': meta}


def assemble(work):
    folder = studio.DATA/work['id']/'exports'/studio.uid(); folder.mkdir(parents=True)
    if work['mode'] == 'comic':
        sheet = Image.new('RGB', (1320, 4*740+100), '#faf7f0')
        d = ImageDraw.Draw(sheet); d.text((25, 25), work['title'], font=ImageFont.truetype(FONT, 32), fill='#222222')
        for i, s in enumerate(work['shots']):
            with Image.open(studio.DATA/s['asset']['image']) as im: sheet.paste(im, (20, 80+i*740))
        sheet.save(folder/'comic.png')
        with Image.open(folder/'comic.png') as thumbnail:
            thumbnail.thumbnail((440, 1000)); thumbnail.save(folder/'poster.png')
        filename = 'comic.png'
    else:
        clips = [studio.DATA/s['asset']['file'] for s in work['shots']]
        (folder/'concat.txt').write_text('\n'.join("file '" + str(f) + "'" for f in clips))
        run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(folder/'concat.txt'), '-c', 'copy', '-movflags', '+faststart', str(folder/'film.mp4')])
        with Image.open(studio.DATA/work['shots'][0]['asset']['image']) as im: im.save(folder/'poster.png')
        (folder/'captions.srt').write_text('\n\n'.join(f'{i+1}\n00:00:{i*5:02d},000 --> 00:00:{(i+1)*5:02d},000\n{s["text"]}' for i,s in enumerate(work['shots']) if s['text']))
        filename = 'film.mp4'
    manifest = {k: work[k] for k in ['title', 'mode', 'answers', 'characters', 'shots']}
    manifest['format_version'] = work.get('version',2)
    if work.get('profile'): manifest['profile'] = work['profile']
    manifest['provider'] = work.get('provider', 'local_demo')
    with zipfile.ZipFile(folder/'project.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('project.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.write(folder/filename, filename)
        if work['mode'] == 'anime': archive.write(folder/'captions.srt', 'captions.srt')
        if work.get('reference'): archive.write(studio.DATA/work['reference'],'character-reference.png')
        for s in work['shots']:
            assetdir = studio.DATA/s['asset']['file']; assetdir = assetdir.parent
            for f in assetdir.iterdir():
                if f.suffix in ['.png', '.mp4', '.wav']: archive.write(f, f'assets/{s["asset"]["id"]}/{f.name}')
    rel = lambda name: str((folder/name).relative_to(studio.DATA))
    return {'file': rel(filename), 'poster': rel('poster.png'), 'zip': rel('project.zip'), 'srt': rel('captions.srt') if work['mode']=='anime' else None, 'kind': 'gemini' if work.get('provider') == 'gemini' and work['mode'] == 'comic' else 'local_demo'}
