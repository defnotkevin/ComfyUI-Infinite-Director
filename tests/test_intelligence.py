import copy
import unittest
from unittest.mock import patch
from infinite_director.intelligence import enrich, local_url
from infinite_director.core import plan

class IntelligenceTests(unittest.TestCase):
    def test_loopback_only(self):
        for value in ('http://example.com','file:///etc/passwd','http://127.0.0.1.evil.com','http://user:pass@localhost'):
            with self.assertRaises(ValueError):local_url(value)
        self.assertEqual(local_url('http://localhost:11434/'),'http://localhost:11434')
    def test_planner_cannot_mutate_timing(self):
        p={'id':'test','fps':24,'total_frames':480,'direction':'A cup shot','bible':'Green shirt','assets':{},'templates':{}}
        plan(p)
        original=[(s['start'],s['end']) for s in p['shots']]
        def fake(model,system,prompt):
            import json
            shots=json.loads(prompt)['shots']
            return {'shots':[dict(s,camera='wide',purpose='Establish',action='Speak',state_in='Seated',state_out='Seated',notes='',start=10000) for s in shots]}
        with patch('infinite_director.intelligence.ollama',fake):enrich(p,'local')
        self.assertEqual(original,[(s['start'],s['end']) for s in p['shots']])
        self.assertEqual(p['planner'],'ollama:local')
    def test_incomplete_model_response_fails(self):
        p={'id':'test','fps':24,'total_frames':480,'direction':'x','bible':'','assets':{},'templates':{}}
        plan(p)
        with patch('infinite_director.intelligence.ollama',return_value={'shots':[]}),self.assertRaises(ValueError):enrich(p,'local')

if __name__=='__main__':unittest.main()
