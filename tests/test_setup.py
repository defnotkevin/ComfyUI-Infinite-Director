import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/setup_runpod.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class SetupTests(unittest.TestCase):
    def test_all_workflow_models_have_exact_installer_destinations(self):
        installed={Path(f).name for _,f,_ in installer.MODELS}
        requested=set()
        for path in (ROOT/'workflows').glob('*.api.json'):
            for node in json.loads(path.read_text()).values():
                for key,value in node['inputs'].items():
                    if key in ('unet_name','clip_name','vae_name','model_name') and isinstance(value,str):requested.add(value)
        self.assertEqual(requested,installed)
    def test_dry_run_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'does-not-exist'
            result=subprocess.run([sys.executable,str(ROOT/'scripts/setup_runpod.py'),'--all','--dry-run','--comfy-root',str(root)],capture_output=True,text=True,check=True)
            plan=json.loads(result.stdout);self.assertEqual(len(plan['models']),8)
            self.assertFalse(root.exists())
    def test_checksum_detects_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'model';file.write_bytes(b'abcd');checksum=installer.sha256(file)
            self.assertTrue(installer.matches(file,4,checksum))
            file.write_bytes(b'efgh');self.assertFalse(installer.matches(file,4,checksum))
