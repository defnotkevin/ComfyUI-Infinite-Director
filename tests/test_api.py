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
