"""Labeled visual boards for Qwen from selected references and canonical prop sheets."""
from __future__ import annotations
import math
from pathlib import Path


def make_board(store, pid, references, designs=()):
    from PIL import Image, ImageOps, ImageDraw
    entries=[]
    for d in designs:
        if d.get('kind')=='prop' and d.get('file'):
            entries.append((d['file'],f"{d['id']} | {d['label']}"))
    for r in references:
        entries.append((r.get('poster') or r['file'],f"{r['id']} | {r.get('role','general')} | {r.get('label','')}"))
    if not entries: return None
    if len(entries)>16: raise ValueError('Reference board exceeds 16 panels; select fewer references')
    columns=min(4,math.ceil(math.sqrt(len(entries))));rows=math.ceil(len(entries)/columns)
    width,height=512,384
    board=Image.new('RGB',(columns*width,rows*height),(235,235,230));draw=ImageDraw.Draw(board)
    for i,(relative,label) in enumerate(entries):
        x=(i%columns)*width;y=(i//columns)*height
        with Image.open(store.asset(pid,relative)) as image:
            thumb=ImageOps.contain(ImageOps.exif_transpose(image).convert('RGB'),(width-16,height-48))
            board.paste(thumb,(x+(width-thumb.width)//2,y+8))
        # ASCII-safe labels work with Pillow's bundled bitmap font on minimal Linux pods.
        draw.text((x+8,y+height-32),label[:70].encode('ascii','replace').decode(),fill=(20,20,20))
    return board
