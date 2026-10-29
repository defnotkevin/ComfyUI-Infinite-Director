import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from infinite_director.core import Store, reference_key, shot_spec
from infinite_director.direction import plan_direction, migrate, bound_references, design_key
from infinite_director.intelligence import develop_scene

class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);self.p=self.store.create('Director')
        self.p.update(total_frames=18*24,direction='(0-4 seconds) Default camera\n(5-7 seconds) Inside the cup like THIS IMAGE\n(8-11 seconds) Slowly crane up\n(11-15 seconds) Overhead\n(16-18 seconds) Right profile')
        self.p['assets']['source']={'poster':'poster.png','file':'performance.mp4','hash':'source'}
        self.p['other_references']=[{'id':'ref_cup','file':'cup.png','hash':'cup','role':'prop','media_type':'image'}]
    def test_exact_user_ranges_and_explicit_holds(self):
        plan_direction(self.p)
        self.assertEqual([(s['start']//24,s['end']//24) for s in self.p['shots']],[(0,4),(4,5),(5,7),(7,8),(8,11),(11,15),(15,16),(16,18)])
        self.assertEqual(self.p['shots'][2]['reference_ids'],['ref_cup'])
        self.assertTrue(self.p['shots'][3]['is_hold'])
        self.assertIn('Inside the cup',shot_spec(self.p,self.p['shots'][2])['reference_prompt'])
    def test_ambiguous_or_overlapping_direction_is_rejected(self):
        self.p['other_references'].append({'id':'ref_another'})
        with self.assertRaisesRegex(ValueError,'ambiguous'):plan_direction(self.p)
        self.p['direction']='(0-4) Front\n(3-6) Side'
        with self.assertRaisesRegex(ValueError,'overlapping'):plan_direction(self.p)
    def test_long_tail_is_bounded(self):
        self.p.update(total_frames=600*24,direction='(0-4) Front')
        plan_direction(self.p)
        self.assertLessEqual(max(s['end']-s['start'] for s in self.p['shots']),6*24)
        self.assertEqual(self.p['shots'][-1]['end'],600*24)
    def test_selected_reference_hash_and_migration(self):
        plan_direction(self.p);s=self.p['shots'][2];before=reference_key(self.p,s)
        self.p['other_references'][0]['notes']='Cup faces left'
        self.assertNotEqual(before,reference_key(self.p,s))
        self.p['assets']['scene']={'file':'old.png'};migrate(self.p);migrate(self.p)
        self.assertEqual(len(self.p['other_references']),2)
        with self.assertRaises(ValueError):bound_references(self.p,{'reference_ids':[{}]})
    def test_agent_produces_prompts_without_moving_timecodes(self):
        def fake(model,system,prompt,images=None):
            data=json.loads(prompt)
            if 'Describe reference evidence' in system:return {'description':'ceramic cup','limitations':'single angle'}
            if 'continuity supervisor' in system:return {'bible':'Red coat, white ceramic cup in right hand.', 'designs':[{'kind':'character','label':'Character','prompt':'Multi-view red coat character','reference_ids':[]},{'kind':'prop','label':'Cup','prompt':'Ceramic cup turnarounds','reference_ids':['ref_cup']}], 'assumptions':['Room geography invented.']}
            return {'shots':[dict(id=s['id'],camera='custom',camera_description=s['direction_text'],image_prompt='One cinematic opening frame',video_prompt='Preserve speech and perform requested move',state_in='Cup on table',state_out='Cup on table',reference_ids=[]) for s in data['shots']]}
        before=copy.deepcopy(self.p)
        with patch('infinite_director.intelligence.ollama',side_effect=fake):p=develop_scene(self.store,self.p,'fake')
        self.assertEqual(self.p,before)
        self.assertEqual(len(p['designs']),2);self.assertEqual(len(p['shots']),8)
        self.assertEqual(p['shots'][2]['reference_ids'],['ref_cup'])
        self.assertEqual(p['shots'][-1]['end'],432)
        self.assertIn('Red coat',shot_spec(p,p['shots'][0])['reference_prompt'])
        key=design_key(p,p['designs'][0]);p['bible']='Blue coat';self.assertNotEqual(key,design_key(p,p['designs'][0]))

    def test_sheet_and_shot_generation_are_cached_without_video(self):
        import threading
        from PIL import Image
        from infinite_director.engine import Engine, validate_template
        plan_direction(self.p)
        folder=self.store.folder(self.p['id']);Image.new('RGB',(32,32)).save(folder/'fixture.png')
        graph={'1':{'class_type':'IDShotInputs','inputs':{}},'2':{'class_type':'SaveImage','inputs':{'images':['1',2]}}}
        self.p['templates']['reference']=validate_template(graph,'reference')
        self.p['designs']=[dict(id='design_001',kind='character',label='Character',prompt='Turnaround sheet',seed=20,reference_ids=[])]
        self.store.write(self.p)
        class Client:
            calls=[]
            def control(inner,*args,**kwargs):return {"released":True}
            def request(inner,*args):return {'IDShotInputs':{},'SaveImage':{}}
            def execute(inner,graph,output,role,cancel,on_queued):
                inner.calls.append(role);return folder/'fixture.png'
        client=Client();engine=Engine(self.store,client)
        import time
        for count in (9,9):
            engine.render(self.p['id'],stage='references')
            for _ in range(200):
                if not engine.busy(self.p['id']):break
                time.sleep(.01)
            p=self.store.read(self.p['id']);self.assertEqual(p['jobs'][-1]['status'],'complete',p['jobs'][-1])
            self.assertEqual(len(client.calls),count)
            self.assertTrue(all(s.get('reference') for s in p['shots']))
            self.assertTrue(all(not s['candidates'] for s in p['shots']))
