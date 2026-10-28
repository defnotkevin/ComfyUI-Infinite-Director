"""Generate readable, flat ComfyUI workflows and matching API templates.
LTX sampling topology follows Lightricks' official 2.5 A2V example.
No remote text encoding or API nodes are included.
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / 'workflows'

class Graph:
    def __init__(self):
        self.nodes, self.links, self.api = [], [], {}
    def add(self, cls, inputs, outputs, widgets=None, title=None, x=0, y=0):
        nid = len(self.nodes)+1
        api_inputs, ui_inputs, values = {}, [], []
        for name, value, typ in inputs:
            if isinstance(value, tuple):
                origin, slot = value
                lid = len(self.links)+1
                self.links.append([lid, origin, slot, nid, len(ui_inputs), typ])
                self.nodes[origin-1]['outputs'][slot]['links'].append(lid)
                ui_inputs.append({'name':name, 'type':typ, 'link':lid})
                api_inputs[name] = [str(origin), slot]
            else:
                ui_inputs.append({'name':name, 'type':typ, 'link':None, 'widget':{'name':name}})
                api_inputs[name] = value
                values.append(value)
        node = {'id':nid, 'type':cls, 'pos':[x,y], 'size':[325, max(120, 70+len(inputs)*30, 60+len(outputs)*24)],
                'flags':{}, 'order':nid-1, 'mode':0, 'inputs':ui_inputs,
                'outputs':[{'name':n,'type':t,'links':[]} for n,t in outputs],
                'properties':{'Node name for S&R':cls}, 'widgets_values': values if widgets is None else widgets}
        if title: node['title']=title
        self.nodes.append(node)
        self.api[str(nid)]={'class_type':cls,'inputs':api_inputs,'_meta':{'title':title or cls}}
        return nid
    def bridge(self):
        return self.add('IDShotInputs',[('project_id','','STRING'),('shot_id','shot_0001','STRING'),('job_id','','STRING')],
            [('video_prompt','STRING'),('reference_prompt','STRING'),('shot_image','IMAGE'),('character','IMAGE'),('scene','IMAGE'),
             ('audio','AUDIO'),('fps','FLOAT'),('num_frames','INT'),('duration','FLOAT'),('seed','INT'),('filename_prefix','STRING')],x=0,y=0)
    def save(self,name):
        workflow={'last_node_id':len(self.nodes),'last_link_id':len(self.links),'nodes':self.nodes,'links':self.links,
                  'groups':[],'config':{},'extra':{'ds':{'scale':.65,'offset':[50,50]}},'version':.4}
        (ROOT/(name+'.json')).write_text(json.dumps(workflow,indent=2)+'\n')
        (ROOT/(name+'.api.json')).write_text(json.dumps(self.api,indent=2)+'\n')

q=Graph(); b=q.bridge()
u=q.add('UNETLoader',[('unet_name','qwen_image_edit_2511_bf16.safetensors','COMBO'),('weight_dtype','default','COMBO')],[('MODEL','MODEL')],x=390,y=0)
c=q.add('CLIPLoader',[('clip_name','qwen_2.5_vl_7b_fp8_scaled.safetensors','COMBO'),('type','qwen_image','COMBO'),('device','default','COMBO')],[('CLIP','CLIP')],x=390,y=200)
v=q.add('VAELoader',[('vae_name','qwen_image_vae.safetensors','COMBO')],[('VAE','VAE')],x=390,y=420)
pos=q.add('TextEncodeQwenImageEditPlus',[('clip',(c,0),'CLIP'),('prompt',(b,1),'STRING'),('vae',(v,0),'VAE'),('image1',(b,3),'IMAGE'),('image2',(b,4),'IMAGE')],[('CONDITIONING','CONDITIONING')],x=780,y=0)
neg=q.add('TextEncodeQwenImageEditPlus',[('clip',(c,0),'CLIP'),('prompt','collage, contact sheet, text, watermark, duplicated people','STRING'),('vae',(v,0),'VAE'),('image1',(b,3),'IMAGE'),('image2',(b,4),'IMAGE')],[('CONDITIONING','CONDITIONING')],x=780,y=240)
latent=q.add('EmptySD3LatentImage',[('width',1024,'INT'),('height',576,'INT'),('batch_size',1,'INT')],[('LATENT','LATENT')],x=780,y=490)
model=q.add('ModelSamplingAuraFlow',[('model',(u,0),'MODEL'),('shift',3.1,'FLOAT')],[('MODEL','MODEL')],x=1160,y=0)
s=q.add('KSampler',[('model',(model,0),'MODEL'),('seed',(b,9),'INT'),('steps',24,'INT'),('cfg',4.,'FLOAT'),('sampler_name','euler','COMBO'),('scheduler','simple','COMBO'),('positive',(pos,0),'CONDITIONING'),('negative',(neg,0),'CONDITIONING'),('latent_image',(latent,0),'LATENT'),('denoise',1.,'FLOAT')],[('LATENT','LATENT')], widgets=[0,'fixed',24,4.,'euler','simple',1.],x=1160,y=200)
d=q.add('VAEDecode',[('samples',(s,0),'LATENT'),('vae',(v,0),'VAE')],[('IMAGE','IMAGE')],x=1550,y=200)
q.add('SaveImage',[('images',(d,0),'IMAGE'),('filename_prefix',(b,10),'STRING')],[],widgets=['InfiniteDirector/reference'],x=1930,y=200)
q.save('02-qwen-reference')

l=Graph();b=l.bridge()
u=l.add('UNETLoader',[('unet_name','ltx-2.5-22b-distilled-transformer-bf16.safetensors','COMBO'),('weight_dtype','default','COMBO')],[('MODEL','MODEL')],x=390,y=0)
c=l.add('CLIPLoader',[('clip_name','gemma4-12b-with-proj-ltx-2.5-bf16.safetensors','COMBO'),('type','ltxv','COMBO'),('device','default','COMBO')],[('CLIP','CLIP')],x=390,y=180)
v=l.add('VAELoader',[('vae_name','ltx-2.5-video-vae-bf16.safetensors','COMBO')],[('VAE','VAE')],x=390,y=370)
a=l.add('VAELoader',[('vae_name','ltx-2.5-audio-vae-bf16.safetensors','COMBO')],[('VAE','VAE')],x=390,y=510)
p=l.add('CLIPTextEncode',[('clip',(c,0),'CLIP'),('text',(b,0),'STRING')],[('CONDITIONING','CONDITIONING')],widgets=[''],x=780,y=0)
n=l.add('CLIPTextEncode',[('clip',(c,0),'CLIP'),('text','','STRING')],[('CONDITIONING','CONDITIONING')],x=780,y=160)
cond=l.add('LTXVConditioning',[('positive',(p,0),'CONDITIONING'),('negative',(n,0),'CONDITIONING'),('frame_rate',(b,6),'FLOAT')],[('positive','CONDITIONING'),('negative','CONDITIONING')],widgets=[24],x=1160,y=0)
im=l.add('LTXVPreprocess',[('image',(b,2),'IMAGE'),('img_compression',18,'INT')],[('IMAGE','IMAGE')],x=780,y=350)
e=l.add('EmptyLTXVLatentVideo',[('width',960,'INT'),('height',544,'INT'),('length',(b,7),'INT'),('batch_size',1,'INT')],[('LATENT','LATENT')],widgets=[960,544,121,1],x=780,y=500)
i=l.add('LTXVImgToVideoInplace',[('vae',(v,0),'VAE'),('image',(im,0),'IMAGE'),('latent',(e,0),'LATENT'),('strength',.8,'FLOAT'),('bypass',False,'BOOLEAN')],[('LATENT','LATENT')],x=1160,y=250)
ae=l.add('LTXVAudioVAEEncode',[('audio',(b,5),'AUDIO'),('audio_vae',(a,0),'VAE')],[('LATENT','LATENT')],x=780,y=710)
mask=l.add('SolidMask',[('value',0.,'FLOAT'),('width',1024,'INT'),('height',1024,'INT')],[('MASK','MASK')],x=780,y=890)
af=l.add('SetLatentNoiseMask',[('samples',(ae,0),'LATENT'),('mask',(mask,0),'MASK')],[('LATENT','LATENT')],x=1160,y=620)
av=l.add('LTXVConcatAVLatent',[('video_latent',(i,0),'LATENT'),('audio_latent',(af,0),'LATENT')],[('LATENT','LATENT')],x=1540,y=350)
def sample(latent, sigmas, x, y, sampler):
 noise=l.add('RandomNoise',[('noise_seed',(b,9),'INT')],[('NOISE','NOISE')],widgets=[0,'fixed'],x=x,y=y)
 guide=l.add('CFGGuider',[('model',(u,0),'MODEL'),('positive',(cond,0),'CONDITIONING'),('negative',(cond,1),'CONDITIONING'),('cfg',1.,'FLOAT')],[('GUIDER','GUIDER')],x=x,y=y+130)
 sam=l.add('KSamplerSelect',[('sampler_name',sampler,'COMBO')],[('SAMPLER','SAMPLER')],x=x,y=y+330)
 sig=l.add('ManualSigmas',[('sigmas',sigmas,'STRING')],[('SIGMAS','SIGMAS')],x=x,y=y+470)
 s=l.add('SamplerCustomAdvanced',[('noise',(noise,0),'NOISE'),('guider',(guide,0),'GUIDER'),('sampler',(sam,0),'SAMPLER'),('sigmas',(sig,0),'SIGMAS'),('latent_image',(latent,0),'LATENT')],[('output','LATENT'),('denoised_output','LATENT')],x=x+380,y=y+180)
 return l.add('LTXVSeparateAVLatent',[('av_latent',(s,0),'LATENT')],[('video_latent','LATENT'),('audio_latent','LATENT')],x=x+760,y=y+180)
s1=sample(av,'1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0',1920,0,'euler_ancestral')
up=l.add('LatentUpscaleModelLoader',[('model_name','ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors','COMBO')],[('LATENT_UPSCALE_MODEL','LATENT_UPSCALE_MODEL')],x=2680,y=400)
upl=l.add('LTXVLatentUpsampler',[('samples',(s1,0),'LATENT'),('upscale_model',(up,0),'LATENT_UPSCALE_MODEL'),('vae',(v,0),'VAE')],[('LATENT','LATENT')],x=3060,y=180)
i2=l.add('LTXVImgToVideoInplace',[('vae',(v,0),'VAE'),('image',(im,0),'IMAGE'),('latent',(upl,0),'LATENT'),('strength',1.,'FLOAT'),('bypass',False,'BOOLEAN')],[('LATENT','LATENT')],x=3440,y=180)
av2=l.add('LTXVConcatAVLatent',[('video_latent',(i2,0),'LATENT'),('audio_latent',(af,0),'LATENT')],[('LATENT','LATENT')],x=3820,y=180)
s2=sample(av2,'0.909375, 0.725, 0.421875, 0.0',4200,0,'euler')
d=l.add('VAEDecodeTiled',[('samples',(s2,0),'LATENT'),('vae',(v,0),'VAE'),('tile_size',512,'INT'),('overlap',64,'INT'),('temporal_size',128,'INT'),('temporal_overlap',32,'INT')],[('IMAGE','IMAGE')],x=5340,y=180)
cv=l.add('CreateVideo',[('images',(d,0),'IMAGE'),('audio',(b,5),'AUDIO'),('fps',(b,6),'FLOAT')],[('VIDEO','VIDEO')],widgets=[24,8],x=5720,y=180)
l.add('SaveVideo',[('video',(cv,0),'VIDEO'),('filename_prefix',(b,10),'STRING'),('format','auto','COMBO'),('codec','auto','COMBO')],[],widgets=['InfiniteDirector/video','auto','auto'],x=6100,y=180)
l.save('03-ltx25-audio-video')

g=Graph();g.bridge();g.add('IDScenePlan',[('project_id','','STRING')],[('scene_json','STRING'),('shot_count','INT')],x=400,y=0)
g.add('IDExportScene',[('project_id','','STRING'),('width',1280,'INT'),('height',720,'INT')],[('export_path','STRING')],x=800,y=0)
g.save('01-director')
