import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('drive_probe',Path(__file__).resolve().parents[1]/'tools/probe-drive-execution.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class ProbeCompletionTests(unittest.TestCase):
    def test_incomplete_or_changed_recording_cannot_succeed(self):
        good=dict(completion={'status':'completed'},sources_unchanged=True,qualification_status='not_qualified')
        self.assertTrue(probe.recording_succeeded(good))
        for bad in ({},dict(good,completion={}),dict(good,completion={'status':'failed'}),
                    dict(good,sources_unchanged=False),dict(good,error='KeyboardInterrupt'),
                    dict(good,resource_abort='Low RAM')):
            with self.subTest(bad=bad):self.assertFalse(probe.recording_succeeded(bad))


if __name__=='__main__':unittest.main()
