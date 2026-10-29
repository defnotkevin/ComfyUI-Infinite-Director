import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from infinite_director.gpu import execute_control,unload_reasoner,DEFAULT_MODEL
from infinite_director.core import Store
from infinite_director.engine import Engine,ComfyClient,Cancelled
from infinite_director.intelligence import ollama_direct,reasoning_backend,ollama

class GPUTests(unittest.TestCase):
    def test_explicit_thinking_and_truncation(self):
        import io
        payload=[]
        def response(req,**kwargs):
            payload.append(json.loads(req.data));return io.BytesIO(b'{"message":{"content":"{\\"ok\\":true}"},"done_reason":"stop"}')
        with patch('urllib.request.urlopen',side_effect=response):
            self.assertEqual(ollama_direct(DEFAULT_MODEL,'system','prompt'),{'ok':True})
        self.assertTrue(payload[0]['think']);self.assertEqual(payload[0]['keep_alive'],0)
        self.assertEqual(payload[0]['options']['num_predict'],16384)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"message":{"content":"{}"},"done_reason":"length"}')):
            with self.assertRaisesRegex(ValueError,'budget'):ollama_direct(DEFAULT_MODEL,'x','y')
    def test_worker_cleanup_even_when_reasoning_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);p=store.create('GPU');folder=store.asset(p['id'],'contexts');folder.mkdir()
            (folder/'test.gpu.json').write_text(json.dumps({'action':'reason','model':DEFAULT_MODEL,'system':'x','prompt':'x'}))
            calls=[]
            with patch('infinite_director.gpu.release_comfy',side_effect=lambda:calls.append('comfy')),patch('infinite_director.gpu.unload_reasoner',side_effect=lambda m:calls.append('ollama')),patch('infinite_director.intelligence.ollama_direct',side_effect=ValueError('bad JSON')):
                with self.assertRaisesRegex(ValueError,'bad JSON'):execute_control(store,p['id'],'test')
            self.assertEqual(calls,['comfy','ollama','comfy'])
            self.assertFalse((folder/'test.result.json').exists())
    def test_unload_waits_for_residency_acknowledgement(self):
        replies=[{}, {'models':[{'name':DEFAULT_MODEL}]}, {'models':[]}]
        with patch('infinite_director.gpu.ollama_request',side_effect=replies) as request,patch('infinite_director.gpu.time.sleep'):
            unload_reasoner(DEFAULT_MODEL)
        self.assertEqual([c.args[0] for c in request.call_args_list],['/api/generate','/api/ps','/api/ps'])
        self.assertEqual(request.call_args_list[0].args[1]['keep_alive'],0)
    def test_control_cancellation_never_interrupts_another_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);p=store.create('GPU');client=ComfyClient('http://127.0.0.1:8188',temp,temp)
            cancel=threading.Event();calls=[]
            def request(path,data=None):
                calls.append((path,data));return {'prompt_id':'our-control'}
            with patch.object(client,'request',side_effect=request):
                with self.assertRaises(Cancelled):client.control(store,p['id'],{'action':'release'},cancel,lambda _:cancel.set())
            self.assertEqual(calls[-1],('/queue',{'delete':['our-control']}))
            self.assertFalse(any(p=='/interrupt' for p,_ in calls))
    def test_cross_project_gpu_jobs_do_not_overlap(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);a=store.create('A');b=store.create('B');engine=Engine(store,object())
            entered=threading.Event();finish=threading.Event();second=threading.Event()
            engine.start(a['id'],'test',lambda c,j:(entered.set(),finish.wait(3)))
            self.assertTrue(entered.wait(1))
            engine.start(b['id'],'test',lambda c,j:second.set())
            self.assertFalse(second.wait(.15));finish.set();self.assertTrue(second.wait(2))
            for _ in range(100):
                if not engine.busy(a['id']) and not engine.busy(b['id']):break
                time.sleep(.01)
