import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('prune',Path(__file__).resolve().parents[1]/'tools/prune-historical-recordings.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class HistoricalCleanupTests(unittest.TestCase):
    def test_old_payload_only_preserves_results_captures_inputs_and_current_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'tests/20261004T120000-old';old.mkdir(parents=True)
            new=root/'tests/20261007T120000-current';new.mkdir(parents=True)
            source=root/'source';source.mkdir();(source/'original.dae').write_text('required')
            for run in (old,new):
                (run/'vehicle').mkdir();(run/'vehicle/mesh.dae').write_text('duplicate')
                (run/'vehicle.csv').write_text('raw');(run/'result.json').write_text('{"status":"failed"}')
                (run/'final.png').write_text('image')
            result=module.prune([root/'tests'],'20261006',root/'audit.json',True)
            self.assertEqual(result['runs'],1);self.assertFalse((old/'vehicle.csv').exists())
            self.assertFalse((old/'vehicle').exists());self.assertTrue((old/'final.png').exists())
            self.assertEqual(json.loads((old/'result.json').read_text())['status'],'failed')
            self.assertTrue((new/'vehicle.csv').exists());self.assertTrue((source/'original.dae').exists())


if __name__=='__main__':unittest.main()
