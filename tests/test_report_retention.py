import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import write_json
from frame_harness.retention import apply_retention
from frame_harness.runner import saved_recording_failure


class RetentionTests(unittest.TestCase):
    def fixture(self,root):
        (root/'study').mkdir();(root/'study/index.html').write_text('report')
        run=root/'tests/run';attempt=run/'attempt-0';attempt.mkdir(parents=True)
        write_json(run/'telemetry_location.json',dict(directory='attempt-0'))
        write_json(run/'job-0.json',dict(id='run-0',expected_nodes=1,expected_beams=1,scenario=dict(duration=1,load_nodes=['n'])))
        write_json(attempt/'completion.json',dict(status='completed',job_id='run-0',trajectory_samples=2,physics_steps=1,simulated_seconds=1))
        for filename,rows in [('nodes.csv',2),('beams.csv',2),('loads.csv',2),('probes.csv',1)]:
            (attempt/filename).write_text('header\n'+'row\n'*rows)
        write_json(run/'metrics.json',dict(measured_mass_kg=1))
        record=dict(key='solidworks-assigned-flex',status='completed',path=str(run),metrics=dict(measured_mass_kg=1))
        write_json(run/'result.json',record)
        (run/'vehicle').mkdir();(run/'vehicle/mesh.dae').write_text('large duplicate mesh')
        (attempt/'final-side.png').write_bytes(b'image')
        (run/'report.html').write_text('large plot report')
        state=dict(status='completed',candidates={'solidworks-assigned':dict(offline_accepted=True)},runs=[record],acceptance={})
        return state,run

    def test_success_defaults_to_compact_and_checks_retained_evidence_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,run=self.fixture(root)
            result=apply_retention(root,state)
            self.assertFalse(result['full_report_saved']);self.assertGreater(result['freed_bytes'],0)
            self.assertFalse((run/'vehicle').exists());self.assertFalse((run/'attempt-0/nodes.csv').exists())
            self.assertFalse((run/'attempt-0/final-side.png').exists());self.assertFalse((root/'study/index.html').exists())
            self.assertIsNone(saved_recording_failure(run))
            write_json(run/'metrics.json',dict(measured_mass_kg=2))
            self.assertIn('changed',saved_recording_failure(run))

    def test_checkbox_and_failed_measurements_preserve_full_evidence(self):
        for keep,failure in [(True,False),(False,True)]:
            with self.subTest(keep=keep,failure=failure),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);state,run=self.fixture(root)
                if failure:state['runs'][0]['status']='failed'
                result=apply_retention(root,state,keep)
                self.assertTrue(result['full_report_saved']);self.assertTrue((run/'attempt-0/nodes.csv').exists())
                self.assertTrue((run/'vehicle/mesh.dae').exists());self.assertTrue((root/'study/index.html').exists())

    def test_review_images_remain_until_required_visual_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,run=self.fixture(root)
            state['runs'][0]['key']='mesh-cut-0.35'
            state['status']='completed_with_limitations'
            state['acceptance']={'solidworks-assigned':dict(reasons=['Rendered mesh review missing or stale'])}
            apply_retention(root,state)
            self.assertTrue((run/'attempt-0/final-side.png').exists())
            self.assertIsNone(saved_recording_failure(run))

    def test_truncated_recording_or_external_run_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,run=self.fixture(root)
            (run/'attempt-0/nodes.csv').write_text('header\n')
            with self.assertRaisesRegex(ValueError,'Invalid recording'):apply_retention(root,state)
            self.assertTrue((run/'vehicle/mesh.dae').exists())
            state['runs'][0]['path']=str(root/'elsewhere')
            with self.assertRaisesRegex(ValueError,'outside this generation'):apply_retention(root,state)

    def test_missing_recording_is_not_reused_as_a_completed_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state,run=self.fixture(root)
            (run/'attempt-0/completion.json').unlink()
            self.assertIn('incomplete',saved_recording_failure(run))
            (run/'telemetry_location.json').unlink()
            self.assertIn('Missing',saved_recording_failure(run))


if __name__=='__main__':unittest.main()
