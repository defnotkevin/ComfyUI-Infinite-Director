import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from PIL import Image
from infinite_director.core import Store,plan,reference_key,render_key,digest
from infinite_director.direction import migrate,design_key
from infinite_director.canvas import create_inputs,save_design,save_reference
from infinite_director.providers import codex_reason,response_schema
ROOT=Path(__file__).resolve().parents[1]

class CanvasTests(unittest.TestCase):
    def test_canvas_graph_connections_and_node_contracts(self):
        # Import nodes without starting a ComfyUI server or requiring CUDA.
        package=types.ModuleType('canvas_test_package');package.__path__=[str(ROOT)];sys.modules[package.__name__]=package
        nodes=importlib.import_module(package.__name__+'.canvas_nodes').NODE_CLASS_MAPPINGS
        for path in sorted((ROOT/'workflows').glob('0[456]-canvas*.json')):
            if '.api.' in path.name:continue
            graph=json.loads(path.read_text());by_id={n['id']:n for n in graph['nodes']}
            for n in graph['nodes']:
                if n['type'] in nodes:
                    cls=nodes[n['type']];self.assertEqual([o['type'] for o in n['outputs']],list(cls.RETURN_TYPES))
                    required=cls.INPUT_TYPES()['required'];self.assertTrue(set(required)<=set(i['name'] for i in n['inputs']))
            for lid,src,slot,dst,inp,typ in graph['links']:
                self.assertEqual(by_id[src]['outputs'][slot]['type'],typ)
                self.assertEqual(by_id[dst]['inputs'][inp]['type'],typ)
                self.assertEqual(by_id[dst]['inputs'][inp]['link'],lid)
    def test_silent_scene_and_stale_sheet_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);p=create_inputs(store,'Silent','Front','Red coat',24,2)
            self.assertTrue(p['assets']['source']['silent']);self.assertEqual(p['total_frames'],48)
            plan(p);p['designs']=[dict(id='design_001',kind='character',label='Character',prompt='Red coat sheet',seed=1,reference_ids=[])]
            store.write(p);task={'project_id':p['id'],'id':'design_001','key':design_key(p,p['designs'][0]),'graph_hash':'test'}
            with patch('infinite_director.canvas.image_save',side_effect=lambda i,path:Image.new('RGB',(8,8)).save(path)):
                save_design(store,task,None)
                p=store.read(p['id']);self.assertTrue(store.asset(p['id'],p['designs'][0]['file']).exists())
                shot=p['shots'][0];ref={'project_id':p['id'],'id':shot['id'],'key':reference_key(p,shot),'graph_hash':'test'}
                save_reference(store,ref,None)
                store.update(p['id'],lambda p:p.update(bible='Blue coat'))
                with self.assertRaisesRegex(ValueError,'changed'):save_design(store,task,None)
                with self.assertRaisesRegex(ValueError,'changed'):save_reference(store,ref,None)
    def test_codex_uses_readonly_structured_output_and_stdin(self):
        commands=[]
        def run(args,**kwargs):
            commands.append((args,kwargs));Path(args[args.index('--output-last-message')+1]).write_text('{"description":"Cup","limitations":"One view"}')
            return types.SimpleNamespace(returncode=0,stderr='')
        with patch('infinite_director.providers.shutil.which',return_value='/usr/bin/codex'),patch('infinite_director.providers.subprocess.run',side_effect=run):
            result=codex_reason('','Describe reference evidence','User direction')
        args,kwargs=commands[0];self.assertEqual(result['description'],'Cup')
        self.assertIn('read-only',args);self.assertIn('--output-schema',args);self.assertNotIn('--model',args)
        self.assertEqual(args[-1],'-');self.assertIn('User direction',kwargs['input'])
        self.assertFalse(kwargs.get('shell',False))
    def test_codex_schema_requires_full_shot_contract(self):
        props=response_schema('shot planner')['properties']['shots']['items']['properties']
        self.assertTrue({'image_prompt','video_prompt','state_in','state_out','reference_ids'}<=set(props))
