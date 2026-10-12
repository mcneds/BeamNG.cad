import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.verification import quick_plan, screen_result, run_quick
from frame_harness.assets import BatchAssets, stage_vehicle
from frame_harness.build import write_json
from frame_harness.models import HarnessProject, RunResult
from frame_harness.report import load_csv, telemetry_cache


class VerificationTests(unittest.TestCase):
    def report(self):
        return dict(offline_accepted=True,mass=dict(target_mass_kg=10),responses={
            name:dict(reference=dict(compliance_m_n=.001)) for name in ('flex','torsion')})

    def result(self, test, folder):
        return RunResult(test.name,str(folder/test.name),'completed',test.name,'steel',metrics=dict(
            spring_relative_error=0,measured_mass_kg=10,broken_beams=0,max_rest_length_change_m=0,
            mesh_load_valid=True,render_controller_valid=True,final_shape_rms_m=0,tail_world_speed_rms_m_s=0,
            held_deflection_m=.1,hold_settled=True,position_velocity_consistent=True,applied_force_consistent=True))

    def test_quick_schedule_and_screening_reject_missing_or_bad_measurements(self):
        plan=quick_plan({})
        self.assertEqual([s.name for s in plan],['spring','idle','flex','torsion'])
        self.assertEqual(sum(s.duration for s in plan),55)
        self.assertTrue(all(not s.capture and not s.expected_damage for s in plan))
        from dataclasses import asdict
        row=asdict(self.result(plan[2],Path('unused')))
        self.assertEqual(screen_result(row,self.report()),[])
        for field,value in [('measured_mass_kg',11),('held_deflection_m',.2),('position_velocity_consistent',False),('broken_beams',1)]:
            changed=copy.deepcopy(row);changed['metrics'][field]=value
            self.assertTrue(screen_result(changed,self.report()),field)

    def test_quick_is_separate_resumable_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=HarnessProject(game=root,runs=root/'tests')
            project.executable.parent.mkdir(parents=True);project.executable.write_bytes(b'game-version')
            artifact=root/'steel/calibration.json';write_json(artifact,{})
            state=dict(config={},identity={'source':'one'},candidates={'steel':self.report()},runs=[{'key':'full-existing'}],status='offline_complete')
            before=copy.deepcopy(state)
            with patch('frame_harness.verification.load_artifact'),patch('frame_harness.verification.DriveSession'), \
                 patch('frame_harness.verification.saved_recording_failure',return_value=None), \
                 patch('frame_harness.verification.run_test',side_effect=lambda p,s,*a,**k:self.result(s,root)) as run:
                result=run_quick(project,root,state,'steel')
                self.assertEqual(result['status'],'quick_passed');self.assertEqual(run.call_count,4)
                self.assertEqual(result['qualification_status'],'not_qualified');self.assertEqual(state,before)
                run_quick(project,root,state,'steel');self.assertEqual(run.call_count,4)
                project.executable.write_bytes(b'new-game-version')
                with self.assertRaisesRegex(ValueError,'inputs changed'):run_quick(project,root,state,'steel')
            (root/'quick-verification.json').unlink()
            with patch('frame_harness.verification.load_artifact'),patch('frame_harness.verification.DriveSession'), \
                 patch('frame_harness.verification.run_test',return_value=RunResult('bad','unused','failed','spring','instrument',failure_reason='crash')) as run:
                result=run_quick(project,root,state,'steel')
                self.assertEqual(result['status'],'quick_failed');self.assertEqual(run.call_count,1)

    def test_unchanged_assets_are_not_rewritten_and_changed_fixture_is_staged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();target=root/'target'
            (source/'mesh.dae').write_bytes(b'geometry');write_json(source/'base.pc',{'model':'mochi'})
            (source/'mochi.jbeam').write_bytes(b'fixture1')
            changed,size=stage_vehicle(source,target)
            self.assertEqual(len(changed),3);self.assertGreater(size,0)
            stamp=(target/'mesh.dae').stat().st_mtime_ns
            self.assertEqual(stage_vehicle(source,target),([],0))
            (source/'mochi.jbeam').write_bytes(b'fixture2')
            self.assertEqual(stage_vehicle(source,target)[0],['/vehicles/fh_mochi/mochi.jbeam'])
            self.assertEqual((target/'mesh.dae').stat().st_mtime_ns,stamp)
            (source/'mesh.dae').unlink();stage_vehicle(source,target)
            self.assertFalse((target/'mesh.dae').exists())

    def test_shared_inputs_are_hashed_and_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'mesh.dae';source.write_bytes(b'CAD')
            cache=BatchAssets(root);first,digest=cache.capture(source)
            second,_=cache.capture(source);self.assertEqual(first,second)
            first.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):cache.capture(source)

    def test_csv_is_parsed_once_for_multiple_consumers(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.csv';path.write_text('t,x,y\n0,1,2\n1,3,4\n')
            original=np.loadtxt
            with patch('frame_harness.report.np.loadtxt',wraps=original) as read,telemetry_cache():
                np.testing.assert_equal(load_csv(path,('x',)),[[1],[3]])
                np.testing.assert_equal(load_csv(path,('y','t')),[[2,0],[4,1]])
                self.assertEqual(read.call_count,1)

    def test_failed_optional_render_preserves_validated_measurements(self):
        from frame_harness.retention import apply_retention
        with tempfile.TemporaryDirectory() as folder:
            job=Path(folder);run=job/'tests'/'failed';run.mkdir(parents=True)
            original={'position_velocity_consistent':False,'performance':{'total_seconds':3}}
            write_json(run/'metrics.json',original)
            state=dict(status='completed_with_limitations',candidates={},runs=[dict(path=str(run),status='invalid_measurement',key='flex')])
            def partial_report(path):
                write_json(path/'metrics.json',{'partial':True})
                raise RuntimeError('plot backend failed')
            with patch('frame_harness.report.create_report',side_effect=partial_report):
                result=apply_retention(job,state)
            self.assertTrue(result['full_report_saved'])
            self.assertEqual(json.loads((run/'metrics.json').read_text()),original)
            self.assertIn('plot backend failed',(run/'report-error.log').read_text())


if __name__=='__main__':unittest.main()
