"""Standalone canvas Director, typed references, sheet/shot selectors and review persistence."""
from __future__ import annotations
import json
from .infinite_director.runtime import runtime
from .infinite_director.core import digest, invalidate, reference_key, render_key, shot_spec
from .infinite_director.direction import ROLES, bound_references, current_designs, design_key
from .infinite_director.gpu import release_comfy, DEFAULT_MODEL
from .infinite_director.canvas import create_inputs, image_load, save_design, save_reference, save_take
from .infinite_director.references import make_board


def load_plan(plan):
    store,engine=runtime();pid=plan['project_id'];engine.idle(pid)
    return store,store.read(pid)


def board_tensor(store,p,refs,designs=()):
    import numpy as np
    import torch
    board=make_board(store,p['id'],refs,designs)
    if board is None:return image_load(store.asset(p['id'],p['assets']['source']['poster']))
    return torch.from_numpy(np.asarray(board,dtype=np.float32).copy()/255)[None,...]


class IDReference:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'label':('STRING',{'default':'Reference'}),'role':(list(ROLES),),'notes':('STRING',{'default':'','multiline':True})},
                'optional':{'image':('IMAGE',),'video':('VIDEO',),'previous':('ID_REFERENCES',)}}
    RETURN_TYPES=('ID_REFERENCES','STRING');RETURN_NAMES=('references','reference_id')
    FUNCTION='append';CATEGORY='Infinite Director/Canvas'
    def append(self,label,role,notes,image=None,video=None,previous=None):
        if (image is None)==(video is None):raise ValueError('Connect exactly one image or video to each Other Reference node')
        if role not in ROLES:raise ValueError('Unknown role')
        refs=list(previous or []);refs.append({'label':label,'role':role,'notes':notes,'type':'image' if image is not None else 'video','value':image if image is not None else video})
        return refs,f'@ref_{len(refs):03d}'


class IDDirector:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'name':('STRING',{'default':'Canvas scene'}),'direction':('STRING',{'default':'(0-6 seconds) Front medium shot. Natural delivery.','multiline':True}),
            'constraints':('STRING',{'default':'','multiline':True}),'provider':(['codex','codex_mcp','ollama'],),
            'model':('STRING',{'default':'','tooltip':'Blank uses Codex service default, or qwen3.6:27b-q8_0 for Ollama.'}),
            'fps':('INT',{'default':24,'min':8,'max':60}),'duration':('FLOAT',{'default':18,'min':.1,'max':3600}),
            'revision':('INT',{'default':0,'min':0,'tooltip':'Increment to create a new plan; keep fixed while rendering.'})},
            'optional':{'character':('IMAGE',),'performance':('VIDEO',),'references':('ID_REFERENCES',)}}
    RETURN_TYPES=('ID_PLAN','STRING','STRING','STRING','STRING','STRING')
    RETURN_NAMES=('plan','project_id','scene_bible','qwen_design_prompts','shot_segments','plan_json')
    FUNCTION='direct';CATEGORY='Infinite Director/Canvas';OUTPUT_NODE=True
    DESCRIPTION='Codex sends selected text/images to the Codex service. Ollama stays local. Never executes generated code. Planning does not render images or video.'
    def direct(self,name,direction,constraints,provider,model,fps,duration,revision,character=None,performance=None,references=None):
        from .infinite_director.intelligence import develop_scene,reasoning_backend
        from .infinite_director.providers import backend
        store,_=runtime();release_comfy()
        p=create_inputs(store,name,direction,constraints,fps,duration,character,performance,references or [])
        try:
            with reasoning_backend(backend(provider,model)):
                result=develop_scene(store,p,model or (DEFAULT_MODEL if provider=='ollama' else 'codex-default'))
            result['director_provider']=provider;result['planner']=provider+':'+(model or 'default')
            result['canvas_revision']=revision;store.write(result)
        finally:release_comfy()
        sheets=json.dumps(result['designs'],indent=2);shots=json.dumps([dict(s,compiled=shot_spec(result,s)) for s in result['shots']],indent=2)
        full=json.dumps(result,indent=2)
        return {'ui':{'text':[f"Project: {p['id']}\n{result['bible']}\n\n{sheets}\n\n{shots}"]},
                'result':({'project_id':p['id']},p['id'],result['bible'],sheets,shots,full)}


class IDLoadPlan:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'project_id':('STRING',{'default':''})}}
    RETURN_TYPES=('ID_PLAN',);RETURN_NAMES=('plan',);FUNCTION='load';CATEGORY='Infinite Director/Canvas'
    @classmethod
    def IS_CHANGED(cls,**kwargs):return float('nan')
    def load(self,project_id):
        store,engine=runtime();engine.idle(project_id);p=store.read(project_id)
        if not p['shots']:raise ValueError('Run Director first and paste its project ID')
        return ({'project_id':project_id},)


class IDDesignInputs:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plan':('ID_PLAN',)},'hidden':{'prompt':'PROMPT'}}
    RETURN_TYPES=('STRING','IMAGE','IMAGE','INT','STRING','ID_DESIGN_TASK')
    RETURN_NAMES=('qwen_prompt','character','other_references','seed','filename_prefix','design_task')
    OUTPUT_IS_LIST=(True,)*6;FUNCTION='select';CATEGORY='Infinite Director/Canvas'
    def select(self,plan,prompt=None):
        store,p=load_plan(plan);release_comfy();signature=digest(prompt or {})
        p=store.update(p['id'],lambda p:(p.update(canvas_design_signature=signature),invalidate(p)))
        if not p['designs']:raise ValueError('Director has not generated any designs')
        character=image_load(store.asset(p['id'],p['assets'].get('character',{}).get('file') or p['assets']['source']['poster']))
        rows=[]
        for d in p['designs']:
            task={'project_id':p['id'],'id':d['id'],'key':design_key(p,d),'graph_hash':signature}
            rows.append((d['prompt']+'\nContinuity: '+p['bible'],character,board_tensor(store,p,bound_references(p,d)),d['seed'],f"infinite_director/{p['id']}/{d['id']}",task))
        return tuple(list(values) for values in zip(*rows))


class IDStoreDesign:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'design_task':('ID_DESIGN_TASK',),'images':('IMAGE',)}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('project_id',);FUNCTION='save';OUTPUT_NODE=True;CATEGORY='Infinite Director/Canvas'
    def save(self,design_task,images):
        store,_=runtime()
        try:pid=save_design(store,design_task,images)
        finally:release_comfy()
        return {'ui':{'text':[f"Saved {design_task['id']} in project {pid}"]},'result':(pid,)}


class IDShotReferenceInputs:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plan':('ID_PLAN',),'shot_index':('INT',{'default':0,'min':0})},'hidden':{'prompt':'PROMPT'}}
    RETURN_TYPES=('STRING','IMAGE','IMAGE','INT','STRING','ID_SHOT_TASK')
    RETURN_NAMES=('qwen_prompt','character','other_references','seed','filename_prefix','shot_task')
    FUNCTION='select';CATEGORY='Infinite Director/Canvas'
    def select(self,plan,shot_index,prompt=None):
        store,p=load_plan(plan);release_comfy();signature=digest(prompt or {})
        # Ignore the selector's index in the renderer fingerprint: switching shots must not invalidate earlier shots.
        graph=json.loads(json.dumps(prompt or {}))
        for n in graph.values():
            if n.get('class_type')=='IDShotReferenceInputs':n['inputs']['shot_index']=0
        signature=digest(graph)
        p=store.update(p['id'],lambda p:(p.update(canvas_reference_signature=signature),invalidate(p)))
        if not 0<=shot_index<len(p['shots']):raise ValueError('Shot index is outside the plan')
        designs=current_designs(p)
        if len(designs)!=len(p['designs']):raise ValueError('Generate all current character/prop sheets with the sheet workflow first')
        shot=p['shots'][shot_index];spec=shot_spec(p,shot)
        char=next((d['file'] for d in designs if d['kind']=='character'),None) or p['assets']['source']['poster']
        task={'project_id':p['id'],'id':shot['id'],'key':reference_key(p,shot),'graph_hash':signature}
        return spec['reference_prompt'],image_load(store.asset(p['id'],char)),board_tensor(store,p,bound_references(p,shot),designs),shot['seed'],f"infinite_director/{p['id']}/{shot['id']}",task


class IDStoreShotReference:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'shot_task':('ID_SHOT_TASK',),'images':('IMAGE',)}}
    RETURN_TYPES=('ID_PLAN','STRING','IMAGE');RETURN_NAMES=('plan','shot_id','shot_image')
    FUNCTION='save';CATEGORY='Infinite Director/Canvas';OUTPUT_NODE=True
    def save(self,shot_task,images):
        store,_=runtime();pid=save_reference(store,shot_task,images)
        return {'ui':{'text':[f"Saved camera reference {shot_task['id']}"]},'result':({'project_id':pid},shot_task['id'],images)}


class IDVideoInputs:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'plan':('ID_PLAN',),'shot_id':('STRING',{'default':'shot_0001'}),'shot_image':('IMAGE',)},'hidden':{'prompt':'PROMPT'}}
    RETURN_TYPES=('STRING','IMAGE','AUDIO','FLOAT','INT','FLOAT','INT','STRING','ID_TAKE_TASK')
    RETURN_NAMES=('video_prompt','shot_image','audio','fps','num_frames','duration','seed','filename_prefix','take_task')
    FUNCTION='select';CATEGORY='Infinite Director/Canvas'
    def select(self,plan,shot_id,shot_image,prompt=None):
        from .infinite_director.media import audio_slice
        import torch
        store,p=load_plan(plan);release_comfy()
        graph=json.loads(json.dumps(prompt or {}))
        for n in graph.values():
            if n.get('class_type')=='IDShotReferenceInputs':n['inputs']['shot_index']=0
        signature=digest(graph)
        p=store.update(p['id'],lambda p:(p.update(canvas_video_signature=signature),invalidate(p)))
        shot=next(s for s in p['shots'] if s['id']==shot_id);spec=shot_spec(p,shot)
        if not shot.get('reference'):raise ValueError('Save the current camera reference first')
        waveform,sr=audio_slice(store.asset(p['id'],p['assets']['source']['audio']),spec['render_start'],spec['num_frames'],spec['fps'])
        task={'project_id':p['id'],'id':shot_id,'key':render_key(p,shot),'graph_hash':signature,'spec':spec,'reference':shot['reference']}
        return spec['prompt'],shot_image,{'waveform':torch.from_numpy(waveform)[None,...],'sample_rate':sr},float(spec['fps']),spec['num_frames'],spec['duration'],spec['seed'],f"infinite_director/{p['id']}/{shot_id}",task


class IDStoreTake:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'take_task':('ID_TAKE_TASK',),'video':('VIDEO',)}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('project_id',);FUNCTION='save';CATEGORY='Infinite Director/Canvas';OUTPUT_NODE=True
    def save(self,take_task,video):
        store,_=runtime()
        try:relative=save_take(store,take_task,video)
        finally:release_comfy()
        return {'ui':{'text':[f"Take ready for review: {relative}\nOpen Director Studio to compare, approve and export."]},'result':(take_task['project_id'],)}


class IDTimeline:
    @classmethod
    def INPUT_TYPES(cls):return {'required':{'project_id':('STRING',{'default':''})}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('timeline_json',);FUNCTION='preview';CATEGORY='Infinite Director/Canvas';OUTPUT_NODE=True
    @classmethod
    def IS_CHANGED(cls,**kwargs):return float('nan')
    def preview(self,project_id):
        store,_=runtime();p=store.read(project_id)
        text=json.dumps({'project_id':project_id,'fps':p['fps'],'bible':p['bible'],'shots':p['shots']},indent=2)
        return {'ui':{'text':[text]},'result':(text,)}

NODE_CLASS_MAPPINGS={c.__name__:c for c in (IDReference,IDDirector,IDLoadPlan,IDDesignInputs,IDStoreDesign,IDShotReferenceInputs,IDStoreShotReference,IDVideoInputs,IDStoreTake,IDTimeline)}
NODE_DISPLAY_NAME_MAPPINGS={k:'Infinite Director · '+v for k,v in {'IDReference':'Other Reference','IDDirector':'Director','IDLoadPlan':'Load Plan','IDDesignInputs':'Design Sheet Prompts','IDStoreDesign':'Save Design Sheet','IDShotReferenceInputs':'Shot Reference Prompt','IDStoreShotReference':'Save Shot Reference','IDVideoInputs':'LTX Shot Segment','IDStoreTake':'Save Take for Review','IDTimeline':'Timeline Preview'}.items()}
