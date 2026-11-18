import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'beamng.cad/FramePipeline/preview_search_worker.py'
spec = importlib.util.spec_from_file_location('preview_search_worker', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class CandidateCheckTests(unittest.TestCase):
    def fixture(self, folder):
        frame = folder / 'snapshot.stl'
        frame.write_bytes(b'owned immutable fixture')
        job = folder / 'job.json'
        data = dict(frame=str(frame), blender='blender', cgal='cgal-python',
                    hull=dict(Width=3, Height=5, Length=4, ProxyDivisor=7,
                              ProxyOffsetRatio=100, Offset=.01, Weld=.1,
                              Symmetry=True, SymmetryBisectFlip=False,
                              SymmetryMergeDistance=.0001), ratios=[50, 100, 200])
        job.write_text(json.dumps(data), encoding='utf-8')
        return job, frame, data

    def test_offset_refinement_partial_failure_and_immutable_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job, frame, original = self.fixture(folder)
            ratios = []

            def run(command, check):
                self.assertTrue(check)
                self.assertIn('--disable-autoexec', command)
                candidate = json.loads(Path(command[-1]).read_text())
                ratios.append(candidate['hull']['ProxyOffsetRatio'])
                for name in original['hull']:
                    if name != 'ProxyOffsetRatio':
                        self.assertEqual(candidate['hull'][name], original['hull'][name])
                report = json.loads((folder / 'check-results.json').read_text())
                self.assertEqual(len(report['results']), len(ratios)-1)
                if ratios[-1] == 100:
                    raise subprocess.CalledProcessError(2, command)
                Path(candidate['off']).write_text('OFF\n4 4 0\n')

            report = worker.check(job, run)
            self.assertEqual(ratios, [50, 100, 200])
            self.assertEqual([r['success'] for r in report['results']], [True, False, True])
            self.assertEqual(frame.read_bytes(), b'owned immutable fixture')
            self.assertEqual(json.loads(job.read_text()), original)

    def test_missing_output_is_a_candidate_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            job, _, _ = self.fixture(Path(directory))
            report = worker.check(job, lambda *args, **kwargs: None)
            self.assertTrue(all(not r['success'] for r in report['results']))

    def test_cancelled_batch_keeps_previously_completed_ratios(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job, _, _ = self.fixture(folder)

            def run(command, **kwargs):
                candidate = json.loads(Path(command[-1]).read_text())
                if candidate['hull']['ProxyOffsetRatio'] == 100:
                    raise KeyboardInterrupt()
                Path(candidate['off']).write_text('OFF\n4 4 0\n')

            with self.assertRaises(KeyboardInterrupt):
                worker.check(job, run)
            results = json.loads((folder / 'check-results.json').read_text())['results']
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]['success'])

    def test_changed_snapshot_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            job, frame, _ = self.fixture(Path(directory))

            def run(command, **kwargs):
                candidate = json.loads(Path(command[-1]).read_text())
                Path(candidate['off']).write_text('OFF\n4 4 0\n')
                frame.write_bytes(b'changed')

            self.assertTrue(all(not r['success'] for r in worker.check(job, run)['results']))


if __name__ == '__main__':
    unittest.main()
