"""Shared persistence for the standalone canvas nodes. No nested ComfyUI queue waits."""
from __future__ import annotations
import hashlib
import json
import math
import shutil
import uuid
import wave
from pathlib import Path
from .core import digest, now, invalidate, reference_key, render_key, shot_spec
from .direction import migrate, design_key
from .media import prepare_source, probe, extract_frame, validate_clip


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def image_save(tensor,path):
    from PIL import Image
    import numpy as np
    if len(tensor)!=1: raise ValueError('Connect a single image per reference, not a frame batch')
    array=tensor[0].detach().cpu().numpy()
    Image.fromarray(np.clip(array*255,0,255).astype('uint8')).convert('RGB').save(path)


def image_load(path):
    import numpy as np
    import torch
    from PIL import Image
    with Image.open(path) as im: return torch.from_numpy(np.asarray(im.convert('RGB'),dtype=np.float32).copy()/255)[None,...]


def save_video(video,path):
    from comfy_api.latest import Types
    video.save_to(str(path),format=Types.VideoContainer('mp4'),codec=Types.VideoCodec('h264'))


def create_inputs(store,name,direction,bible,fps,duration,character=None,performance=None,references=()):
    from PIL import Image
    p=migrate(store.create(name,fps));pid=p['id'];folder=store.folder(pid)
    if character is not None:
        image_save(character,folder/'character.png');p['assets']['character']={'file':'character.png','hash':file_hash(folder/'character.png')}
    if performance is not None:
        save_video(performance,folder/'performance.mp4')
        meta=prepare_source(folder/'performance.mp4',folder)
        p['assets']['source']={'file':'performance.mp4','poster':'source.png','audio':'master.wav','hash':file_hash(folder/'performance.mp4'),'duration':meta['duration']}
        duration=meta['duration']
    else:
        if not math.isfinite(duration) or not 0<duration<=3600: raise ValueError('Duration must be within 0–3600 seconds')
        if character is not None: shutil.copy2(folder/'character.png',folder/'source.png')
        else: Image.new('RGB',(512,512),(128,128,128)).save(folder/'source.png')
        with wave.open(str(folder/'master.wav'),'wb') as stream:
            stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(48000)
            remaining=round(duration*48000)
            while remaining:
                count=min(48000,remaining);stream.writeframes(b'\0'*(count*4));remaining-=count
        p['assets']['source']={'file':'source.png','poster':'source.png','audio':'master.wav','hash':file_hash(folder/'source.png'),'duration':duration,'silent':True}
    if len(references)>24:raise ValueError('At most 24 Other References per scene')
    for i,ref in enumerate(references):
        rid=f'ref_{i+1:03d}'
        if ref['type']=='image':
            file=f'{rid}.png';image_save(ref['value'],folder/file)
            asset={'file':file,'media_type':'image'}
        else:
            file=f'{rid}.mp4';save_video(ref['value'],folder/file);meta=probe(folder/file)
            if not meta['video'] or meta['duration']>3600:raise ValueError('Reference video must be at most one hour')
            extract_frame(folder/file,folder/f'{rid}.jpg',0)
            asset={'file':file,'poster':f'{rid}.jpg','duration':meta['duration'],'media_type':'video'}
        p['other_references'].append(dict(asset,id=rid,role=ref['role'],label=ref['label'],notes=ref['notes'],hash=file_hash(folder/file)))
    p.update(total_frames=math.ceil(duration*fps),direction=direction,bible=bible)
    store.write(p)
    return p


def save_design(store,task,image):
    pid=task['project_id'];relative=f"designs/{task['key']}.png";target=store.asset(pid,relative);target.parent.mkdir(exist_ok=True)
    # Validate before and inside the final atomic update in case another UI edited the scene.
    p=store.read(pid);d=next(d for d in p['designs'] if d['id']==task['id'])
    if design_key(p,d)!=task['key']:raise ValueError('Design inputs changed; requeue the sheet graph')
    image_save(image,target)
    def commit(p):
        d=next(d for d in p['designs'] if d['id']==task['id'])
        if design_key(p,d)!=task['key']:raise ValueError('Design changed during generation')
        d.update(file=relative,key=task['key'],provenance={'method':'canvas','graph_hash':task['graph_hash']})
        invalidate(p)
    store.update(pid,commit)
    return pid


def save_reference(store,task,image):
    pid=task['project_id'];relative=f"references/{task['key']}.png";target=store.asset(pid,relative);target.parent.mkdir(exist_ok=True)
    image_save(image,target)
    def commit(p):
        shot=next(s for s in p['shots'] if s['id']==task['id'])
        if reference_key(p,shot)!=task['key']:raise ValueError('Shot inputs changed; requeue the shot graph')
        shot.pop('reference_override',None);shot['reference']=relative
        shot['reference_provenance']={'method':'canvas','graph_hash':task['graph_hash']}
        invalidate(p)
    store.update(pid,commit)
    return pid


def save_take(store,task,video):
    pid=task['project_id'];cid=uuid.uuid4().hex[:16];relative=f"takes/{task['id']}/{cid}.mp4"
    path=store.asset(pid,relative);path.parent.mkdir(parents=True,exist_ok=True)
    save_video(video,path);checks=validate_clip(path,task['spec'])
    def commit(p):
        shot=next(s for s in p['shots'] if s['id']==task['id'])
        if render_key(p,shot)!=task['key']:raise ValueError('Shot inputs changed during generation; take was not registered')
        shot['candidates'].append({'id':cid,'file':relative,'key':task['key'],'approved':False,'created':now(),
                                  'checks':checks,'reference':task['reference'],'provenance':{'method':'canvas','graph_hash':task['graph_hash'],'seed':task['spec']['seed']}})
        shot.update(selected=cid,status='review');p.pop('export',None)
    store.update(pid,commit)
    return relative
