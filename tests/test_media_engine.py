import copy
import json
import shutil
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from infinite_director.core import Store, plan, shot_spec, render_key
from infinite_director.media import run, prepare_source, probe, audio_slice, validate_clip, assemble
from infinite_director.engine import Engine, validate_template, Cancelled, ComfyClient


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MediaEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'projects');self.p=self.store.create('Integration')
        self.folder=self.store.folder(self.p['id']); self.source=self.folder/'source.mp4'
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x96:rate=24:duration=5',
             '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',self.source])
        meta=prepare_source(self.source,self.folder)
        self.p.update(total_frames=120)
        self.p['assets']['source']={'file':'source.mp4','audio':'master.wav','poster':'source.png','hash':'fixture','duration':5.}
        plan(self.p,2)
        self.store.write(self.p)

    def test_audio_slice_alignment_and_padding(self):
        import numpy as np
        chunk,sr=audio_slice(self.folder/'master.wav',24,25,24)
        with wave.open(str(self.folder/'master.wav'),'rb') as w:
            w.setpos(48000);raw=np.frombuffer(w.readframes(50000),dtype='<i2').reshape(-1,2).T.astype(np.float32)/32768
        np.testing.assert_array_equal(chunk,raw)
        tail,_=audio_slice(self.folder/'master.wav',119,25,24)
        self.assertEqual(tail.shape,(2,50000))
        self.assertTrue(np.all(tail[:,-100:]==0))

    def test_export_exact_frames_and_preserved_audio(self):
        for shot in self.p['shots']:
            spec=shot_spec(self.p,shot);name=shot['id']+'.mp4'
            run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=green:s=160x96:r=24',
                 '-frames:v',spec['num_frames'],'-c:v','libx264',self.folder/name])
            shot.update(candidates=[{'id':shot['id'],'file':name,'key':render_key(self.p,shot),'approved':True}],selected=shot['id'])
        result=assemble(self.store,self.p,320,192)
        info=probe(self.store.asset(self.p['id'],result['file']))
        self.assertEqual(int(info['video']['nb_frames']),120)
        self.assertAlmostEqual(info['duration'],5.,places=2)
        self.assertTrue(info['audio'])
        self.assertEqual(self.store.asset(self.p['id'],result['master']).read_bytes(),(self.folder/'master.wav').read_bytes())
        self.p['shots'][0]['camera']='cup_pov'
        with self.assertRaisesRegex(ValueError,'approve'):assemble(self.store,self.p,320,192)

    def test_short_video_rejected(self):
        with self.assertRaisesRegex(ValueError,'too short'):
            validate_clip(self.source,{'fps':24,'trim_start':0,'edit_frames':240})

    def test_engine_resume_alternate_take_and_restart(self):
        class FakeClient:
            def __init__(self,outer):self.calls=[];self.outer=outer
            def control(self,*args,**kwargs):return {"released":True}
            def request(self,path,data=None):return {'IDShotInputs':{},'SaveImage':{},'SaveVideo':{}}
            def execute(self,graph,output_node,role,cancel,on_queued):
                self.calls.append(role);on_queued('fake-prompt')
                if role=='reference':return self.outer.folder/'source.png'
                context=json.loads(self.outer.store.asset(self.outer.p['id'],f"contexts/{graph['1']['inputs']['job_id']}.json").read_text())
                file=self.outer.folder/f"fake-{len(self.calls)}.mp4"
                run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x96:r=24','-frames:v',context['spec']['num_frames'],'-c:v','libx264',file])
                return file
        for role,cls in [('reference','SaveImage'),('video','SaveVideo')]:
            graph={'1':{'class_type':'IDShotInputs','inputs':{}},'2':{'class_type':cls,'inputs':{'input':['1',2]}}}
            self.p['templates'][role]=validate_template(graph,role)
        self.store.write(self.p);client=FakeClient(self);engine=Engine(self.store,client)
        def wait():
            for _ in range(200):
                if not engine.busy(self.p['id']):return
                time.sleep(.05)
            self.fail('worker did not complete')
        engine.render(self.p['id']);wait()
        p=self.store.read(self.p['id']);self.assertEqual(p['jobs'][-1]['status'],'complete',p['jobs'][-1])
        self.assertTrue(all(s['status']=='review' for s in p['shots']))
        calls=len(client.calls);engine.render(self.p['id']);wait();self.assertEqual(len(client.calls),calls)
        sid=p['shots'][0]['id'];engine.render(self.p['id'],[sid],force=True);wait()
        p=self.store.read(self.p['id']);takes=p['shots'][0]['candidates']
        self.assertEqual(len(takes),2);self.assertNotEqual(takes[0]['provenance']['seed'],takes[1]['provenance']['seed'])
        self.assertEqual(client.calls.count('reference'),len(p['shots']))
        self.store.update(p['id'],lambda p:p['jobs'].append({'id':'crash','status':'running'}))
        Engine(self.store,client)
        self.assertEqual(self.store.read(p['id'])['jobs'][-1]['status'],'interrupted')

    def test_cancel_never_global_interrupt(self):
        client=ComfyClient('http://127.0.0.1:8188',self.root,self.root)
        event=threading.Event();event.set();calls=[]
        def fake(path,data=None):
            calls.append((path,data));return {'prompt_id':'mine'} if path=='/prompt' else {}
        with patch.object(client,'request',fake), self.assertRaises(Cancelled):
            client.execute({},'1','video',event)
        self.assertEqual(calls[-1],('/queue',{'delete':['mine']}))
        self.assertFalse(any(path=='/interrupt' for path,_ in calls))

if __name__=='__main__': unittest.main()
