import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from infinite_director.core import Store, plan, validate_project, validate_transcript, reference_key, render_key, invalidate, shot_spec
from infinite_director.engine import validate_template, bind_template


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.p = self.store.create("Test")
        self.p["total_frames"] = 24 * 63 + 7
        self.p["assets"]["source"] = {"hash": "source", "audio": "master.wav", "poster": "source.png", "file": "source.mp4"}
        plan(self.p)

    def test_long_timeline_exact_coverage(self):
        for frames in (1, 23, 144, 241, 24*300+1, 24*600):
            p = copy.deepcopy(self.p)
            p["total_frames"] = frames
            plan(p)
            self.assertEqual(sum(s["end"]-s["start"] for s in p["shots"]), frames)
            for shot in p["shots"]:
                spec = shot_spec(p, shot)
                self.assertEqual((spec["num_frames"]-1) % 8, 0)
                self.assertGreaterEqual(spec["num_frames"], spec["trim_start"] + spec["edit_frames"])
            validate_project(p)

    def test_boundary_prefers_speech_ends(self):
        p = copy.deepcopy(self.p)
        p['transcript'] = [{'start':0,'end':5.5,'text':'A complete sentence.'}]
        plan(p)
        self.assertEqual(p['shots'][0]['end'],132)

    def test_invalid_intervals_and_nan(self):
        self.p["shots"][1]["start"] += 1
        with self.assertRaises(ValueError): validate_project(self.p)
        with self.assertRaises(ValueError): plan(self.p, float("nan"))
        with self.assertRaises(ValueError): validate_transcript([{"start":0,"end":float("nan"),"text":"x"}],10)
        with self.assertRaises(ValueError): validate_transcript([{"start":-1,"end":2,"text":"x"}],10)

    def test_selective_invalidation_and_restore(self):
        original = self.p['shots'][0]['camera']
        for s in self.p['shots']:
            s['candidates']=[{'id':s['id']+'take','key':render_key(self.p,s),'approved':True}]
            s['selected']=s['candidates'][0]['id']
        self.p['shots'][0]['camera']='cup_pov'
        invalidate(self.p)
        self.assertEqual(self.p['shots'][0]['status'],'planned')
        self.assertEqual(self.p['shots'][1]['status'],'approved')
        self.p['shots'][0]['camera']=original
        self.p['shots'][0]['selected']=self.p['shots'][0]['candidates'][0]['id']
        invalidate(self.p)
        self.assertEqual(self.p['shots'][0]['status'],'approved')

    def test_reference_cache_independent_of_video_notes(self):
        s=self.p['shots'][0]
        r,v=reference_key(self.p,s),render_key(self.p,s)
        s['notes']='A very slow push toward the eyes'
        self.assertEqual(reference_key(self.p,s),r)
        self.assertNotEqual(render_key(self.p,s),v)
        self.p['bible']='Blue coat'
        self.assertNotEqual(reference_key(self.p,s),r)

    def test_asset_paths_and_revision_conflict(self):
        for name in ('../secrets','/etc/passwd','.'):
            with self.assertRaises(ValueError): self.store.asset(self.p['id'],name)
        with self.assertRaises(ValueError): self.store.read('../outside')
        self.store.update(self.p['id'],lambda p:p.update(name='new'),revision=0)
        with self.assertRaises(ValueError): self.store.update(self.p['id'],lambda p:p.update(name='stale'),revision=0)
        self.assertEqual(self.store.read(self.p['id'])['name'],'new')

    def test_bundled_templates_and_bindings(self):
        root=Path(__file__).resolve().parents[1]/'workflows'
        for role, stem in [('reference','02-qwen-reference'),('video','03-ltx25-audio-video')]:
            graph=json.loads((root/(stem+'.api.json')).read_text())
            template=validate_template(graph,role)
            bound=bind_template(template,'project','shot_0001','context')
            self.assertEqual(bound[template['bridge']]['inputs']['job_id'],'context')
            self.assertEqual(graph[template['bridge']]['inputs']['job_id'],'')
            wf=json.loads((root/(stem+'.json')).read_text())
            nodes={n['id']:n for n in wf['nodes']}
            for lid,src,slot,dst,input_slot,typ in wf['links']:
                self.assertEqual(nodes[dst]['inputs'][input_slot]['link'],lid)
                self.assertIn(lid,nodes[src]['outputs'][slot]['links'])
            self.assertFalse(any('API' in n['class_type'] for n in graph.values()))

    def test_template_rejects_disconnected_and_partner_nodes(self):
        graph={'1':{'class_type':'IDShotInputs','inputs':{}},'2':{'class_type':'SaveImage','inputs':{}}}
        with self.assertRaises(ValueError): validate_template(graph,'reference')
        graph['2']['inputs']['images']=['1',2]
        info={'IDShotInputs':{},'SaveImage':{'api_node':True}}
        with self.assertRaises(ValueError): validate_template(graph,'reference',info=info)

if __name__=='__main__': unittest.main()
