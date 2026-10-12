import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ComparisonTests(unittest.TestCase):
    def test_different_control_cadences_cannot_be_labelled_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,deterministic in [('baseline',False),('candidate',True)]:
                folder=root/name;folder.mkdir()
                for filename,data in [('frequency_analysis.json',{'qualification_status':'diagnostic_only'}),
                    ('job.json',{'scenario':'reverse','frequency_capture':{}}),
                    ('probe.json',{'mode':'null','deterministic':deterministic})]:
                    (folder/filename).write_text(json.dumps(data))
            script=Path(__file__).resolve().parents[1]/'tools/compare-suspension-frequency.py'
            result=subprocess.run([sys.executable,str(script),str(root/'baseline'),str(root/'candidate'),'--output',str(root/'result')],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Mismatched execution/control timing',result.stderr)
            self.assertFalse((root/'result.png').exists())


if __name__=='__main__':unittest.main()
