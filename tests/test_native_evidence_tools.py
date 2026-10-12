import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class NativeEvidenceToolTests(unittest.TestCase):
    def test_failed_appearance_baseline_withdraws_previous_acceptance(self):
        spec=importlib.util.spec_from_file_location('paired_native_tool',ROOT/'tools/test-synthetic-appearance.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        import verification_receipts
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);baseline=root/'baseline/manifest.json';appearance=root/'appearance/manifest.json'
            for p in (baseline,appearance):p.parent.mkdir();p.write_text('{}')
            snapshots=[({},dict(appearance_sha256='old'),{},dict(sha256='same')),
                       ({},dict(appearance_sha256='new'),{},dict(sha256='same'))]
            record=dict(status='succeeded',generation_status='succeeded',qualification_status='template_acceptance_passed')
            failed=dict(status='failed',recording_status='completed',scenario='settle',directory=str(root/'run'))
            evidence=root/'pair.json'
            with patch.object(sys,'argv',['paired',str(baseline),str(appearance),str(evidence)]), \
                 patch.object(module,'load_baseline',side_effect=snapshots),patch.object(module,'DriveSession'), \
                 patch.object(module,'run_vehicle',return_value=failed), \
                 patch.object(verification_receipts,'completed_build',return_value=(record,root/'mod.zip')):
                self.assertEqual(module.main(),1)
            saved=json.loads((baseline.parent/'static_frame_build.json').read_text())
            self.assertEqual(saved['qualification_status'],'failed')
            self.assertEqual(saved['generation_status'],'succeeded')
            self.assertEqual(json.loads(evidence.read_text())['status'],'failed')
            self.assertFalse((appearance.parent/'static_frame_build.json').exists())


if __name__=='__main__':unittest.main()
