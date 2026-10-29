import json
import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from harness import make_app
from infinite_director.core import plan

class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();app,self.store,self.engine=make_app(self.tmp.name)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        response=await self.client.post('/infinite-director/projects',json={'name':'API test'})
        self.p=await response.json();self.base='/infinite-director/projects/'+self.p['id']
    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()
    async def test_revision_conflict_and_path_rejection(self):
        response=await self.client.patch(self.base,json={'bible':'Red coat','revision':0});self.assertEqual(response.status,200)
        response=await self.client.patch(self.base,json={'bible':'Blue coat','revision':0});self.assertEqual(response.status,400)
        response=await self.client.get(self.base+'/media?file=../../secret.mp4');self.assertEqual(response.status,400)
    async def test_plan_requires_media_and_preserves_history(self):
        response=await self.client.post(self.base+'/plan',json={});self.assertEqual(response.status,400)
        self.store.update(self.p['id'],lambda p:p.update(total_frames=240,assets={'source':{'duration':10}}))
        response=await self.client.post(self.base+'/plan',json={});self.assertEqual(response.status,200)
        response=await self.client.post(self.base+'/plan',json={});self.assertEqual(response.status,400)
        response=await self.client.post(self.base+'/plan',json={'replace':True});self.assertEqual(response.status,200)
        self.assertEqual(len(self.store.read(self.p['id'])['plan_history']),1)
    async def test_bad_transcript_and_boundary_atomicity(self):
        self.store.update(self.p['id'],lambda p:p.update(total_frames=480,assets={'source':{'duration':20}}))
        await self.client.post(self.base+'/plan',json={})
        before=self.store.read(self.p['id'])
        response=await self.client.post(self.base+'/boundary',json={'shot_id':'shot_0001','frame':100000});self.assertEqual(response.status,400)
        self.assertEqual(before,self.store.read(self.p['id']))
        response=await self.client.post(self.base+'/transcript',json={'segments':[{'start':-1,'end':3,'text':'bad'}]});self.assertEqual(response.status,400)
    async def test_read_hides_large_template_graphs(self):
        root=Path(__file__).resolve().parents[1]
        graph=json.loads((root/'workflows/02-qwen-reference.api.json').read_text())
        response=await self.client.post(self.base+'/templates/reference',json={'graph':graph});self.assertEqual(response.status,200)
        response=await self.client.get(self.base);p=await response.json();self.assertNotIn('graph',p['templates']['reference'])
        response=await self.client.get(self.base+'/manifest');p=await response.json();self.assertIn('graph',p['templates']['reference'])

if __name__=='__main__':unittest.main()

class ReferenceAPITests(APITests):
    async def test_other_images_and_metadata_and_bundled_route(self):
        import io
        from PIL import Image
        from aiohttp import FormData
        image=io.BytesIO();Image.new('RGB',(20,20),'red').save(image,format='PNG')
        for name in ('cup.png','wardrobe.png'):
            form=FormData();form.add_field('file',image.getvalue(),filename=name,content_type='image/png')
            response=await self.client.post(self.base+'/assets/other',data=form)
            self.assertEqual(response.status,200,await response.text())
        p=self.store.read(self.p['id']);self.assertEqual(len(p['other_references']),2)
        ref=p['other_references'][0]
        response=await self.client.patch(self.base+'/references/'+ref['id'],json={'role':'prop','notes':'White ceramic cup'})
        self.assertEqual(response.status,200)
        response=await self.client.post(self.base+'/templates/bundled',json={})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual(set(self.store.read(p['id'])['templates']),{'reference','video'})
    async def test_silent_reference_video(self):
        from aiohttp import FormData
        from infinite_director.media import run
        path=Path(self.tmp.name)/'depth.mp4'
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=gray:s=64x64:r=24:d=1','-c:v','libx264',path])
        form=FormData();form.add_field('file',path.read_bytes(),filename='depth.mp4',content_type='video/mp4')
        response=await self.client.post(self.base+'/assets/other?role=depth',data=form)
        self.assertEqual(response.status,200,await response.text())
        ref=self.store.read(self.p['id'])['other_references'][0]
        self.assertEqual(ref['media_type'],'video');self.assertEqual(ref['role'],'depth')
        self.assertTrue(self.store.asset(self.p['id'],ref['poster']).exists())
    async def test_develop_endpoint_commits_plan_and_generates_auditable_outputs(self):
        import asyncio
        from unittest.mock import patch
        self.store.update(self.p['id'],lambda p:p.update(total_frames=48,direction='(0-2 seconds) Front camera',assets={'source':{'poster':'source.png','file':'source.mp4','duration':2}}))
        response=await self.client.post(self.base+'/templates/bundled',json={});self.assertEqual(response.status,200)
        def fake(model,system,prompt,images=None):
            data=json.loads(prompt)
            if 'continuity supervisor' in system:return {'bible':'Character in blue shirt.', 'designs':[{'kind':'character','label':'Character','prompt':'Three-view character sheet','reference_ids':[]}], 'assumptions':[]}
            return {'shots':[{'id':s['id'],'camera':'front','image_prompt':'Single front frame','video_prompt':'Natural delivery','reference_ids':[]} for s in data['shots']]}
        with patch('infinite_director.intelligence.ollama',side_effect=fake):
            response=await self.client.post(self.base+'/intelligence',json={'action':'develop','model':'fixture','generate':True})
            self.assertEqual(response.status,200,await response.text())
            for _ in range(200):
                if not self.engine.busy(self.p['id']):break
                await asyncio.sleep(.01)
        p=self.store.read(self.p['id']);self.assertEqual(p['jobs'][-1]['status'],'complete',p['jobs'][-1])
        self.assertTrue(self.store.asset(p['id'],p['designs'][0]['file']).is_file())
        self.assertTrue(self.store.asset(p['id'],p['shots'][0]['reference']).is_file())
        response=await self.client.get(self.base);visible=await response.json()
        self.assertFalse(visible['designs'][0]['stale']);self.assertIn('compiled',visible['shots'][0])
        response=await self.client.patch(self.base+'/designs/'+p['designs'][0]['id'],json={'prompt':'Updated blue shirt design'})
        self.assertEqual(response.status,200)
        response=await self.client.get(self.base);visible=await response.json()
        self.assertTrue(visible['designs'][0]['stale']);self.assertNotIn('reference',visible['shots'][0])
