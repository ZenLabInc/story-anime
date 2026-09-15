"""Persisted art direction and distortion-free image normalization."""
from PIL import ImageOps, Image
DEFAULT='日本のフルカラー漫画。繊細なペン線と自然なセル塗り。'

def prompt(style):return (style or {}).get('prompt') or DEFAULT

def normalize(image,size):
    return ImageOps.pad(ImageOps.exif_transpose(image).convert('RGB'),size,method=Image.Resampling.LANCZOS,color='white')

def normalize_file(path,size):
    from pathlib import Path
    original=Path(path).with_suffix('.provider.png')
    Path(path).replace(original)
    with Image.open(original) as im:
        source=list(im.size);normalize(im,size).save(path)
    return {'source_size':source,'output_size':list(size),'provider_original':original.name}
