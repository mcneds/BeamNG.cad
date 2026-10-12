import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import numpy as np
from frame_harness.cad import Body,extract_member,volume_properties
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.build import write_json
from frame_harness.report import graphics_velocity_check


class CurvedSectionTests(unittest.TestCase):
    def body(self):
        data=json.loads((Path(__file__).parent/'fixtures/bent-tube-combine11.json').read_text())
        return Body(data['name'],np.array(data['vertices']),np.array(data['faces']))

    def test_bent_tube_dimensions_bore_volume_and_transform_invariance(self):
        body=self.body();baseline=extract_member(body)
        # Independent nominal 1 inch OD x .065 inch wall section.
        outer=.0254/2;inner=outer-.065*.0254
        self.assertAlmostEqual(baseline['area_m2']/(np.pi*(outer**2-inner**2)),1,delta=.02)
        self.assertAlmostEqual(baseline['J_m4']/(np.pi/2*(outer**4-inner**4)),1,delta=.02)
        self.assertLess(baseline['section_volume_discrepancy'],.01)
        self.assertGreater(len(baseline['path']),2)
        rotation=np.array([[0,0,1],[1,0,0],[0,1,0]])
        for scale in (.5,2):
            transformed=Body('changed',body.vertices@rotation*scale+[1,2,3],body.faces)
            result=extract_member(transformed)
            self.assertAlmostEqual(result['area_m2']/baseline['area_m2'],scale**2,delta=.001)
            self.assertAlmostEqual(result['J_m4']/baseline['J_m4'],scale**4,delta=.02)
            self.assertLess(result['section_volume_discrepancy'],.01)

    def test_nonuniform_tube_is_not_accepted_as_uniform(self):
        body=self.body();body.vertices[:,0]*=2
        with self.assertRaises(ValueError):extract_member(body)


class SessionTests(unittest.TestCase):
    def test_recording_transfer_moves_only_owned_files_and_preflights_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=HarnessProject(userpath=root/'profile',runs=root/'tests')
            with DriveSession(project,'vehicle') as session:
                output=session.control/'results/job';output.mkdir(parents=True)
                target=project.runs/'run';target.mkdir(parents=True)
                (output/'telemetry.csv').write_text('evidence')
                (output/'completion.json').write_text('completed')
                (target/'completion.json').write_text('existing')
                with self.assertRaisesRegex(ValueError,'already exists'):session.archive_recording(output,target)
                self.assertTrue((output/'telemetry.csv').exists())
                self.assertEqual((target/'completion.json').read_text(),'existing')
                (target/'completion.json').unlink()
                session.archive_recording(output,target)
                self.assertFalse(output.exists())
                self.assertEqual((target/'telemetry.csv').read_text(),'evidence')

    def test_recording_transfer_rejects_foreign_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=HarnessProject(userpath=root/'profile',runs=root/'tests')
            with DriveSession(project,'vehicle') as session:
                output=root/'foreign';output.mkdir();(output/'keep').write_text('keep')
                target=project.runs/'run';target.mkdir(parents=True)
                with self.assertRaisesRegex(ValueError,'owned results'):session.archive_recording(output,target)
                self.assertTrue((output/'keep').exists())
                output=session.control/'results/job';output.mkdir(parents=True)
                (output/'keep').write_text('keep')
                with self.assertRaisesRegex(ValueError,'configured runs'):session.archive_recording(output,root/'foreign')
                self.assertTrue((output/'keep').exists())

    def test_failed_recorder_retains_its_measurements_with_matching_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);session=DriveSession(HarnessProject());session.control=root;session.launch={}
            session.process=Mock();session.process.poll.return_value=None
            record=dict(job_id='current',session_id=session.id,status='failed',reason='Physics instability',samples=23,final_node_positions={'a':[1,2,3]})
            write_json(root/'status.json',dict(session_id=session.id,job_id='current',state='failed',reason='Physics instability'))
            write_json(root/'completion.json',record)
            with patch.object(session,'start'),patch.object(session,'command'):
                self.assertEqual(session.execute({'id':'current','duration':30},root,root),record)
                write_json(root/'completion.json',record|dict(session_id='foreign'))
                with self.assertRaises(RuntimeError):session.execute({'id':'current','duration':30},root,root)

    def test_command_retries_transient_windows_sharing_violation_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            session=DriveSession(HarnessProject());session.control=Path(folder)
            write_json(session.control/'control.json',dict(action='old'))
            import os
            original=os.replace;attempts=[]
            def replace(source,target):
                if target.name!='control.json':return original(source,target)
                attempts.append(1)
                if len(attempts)==1:
                    self.assertEqual(json.loads(target.read_text()),dict(action='old'))
                    error=PermissionError('reader holds file');error.winerror=32;raise error
                original(source,target)
            with patch('frame_harness.session.os.replace',side_effect=replace),patch('frame_harness.session.time.sleep'):
                session.command(action='retire')
            self.assertEqual(len(attempts),2)
            self.assertEqual(json.loads((session.control/'control.json').read_text()),dict(session_id=session.id,action='retire'))

    def test_persistent_command_lock_is_bounded_and_owned_process_is_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            session=DriveSession(HarnessProject());session.control=Path(folder)
            error=PermissionError('locked');error.winerror=5
            with patch('frame_harness.session.write_json',side_effect=lambda p,d:p.write_text(json.dumps(d))),patch('frame_harness.session.os.replace',side_effect=error),patch('frame_harness.session.time.monotonic',side_effect=[0,4]):
                with self.assertRaises(PermissionError):session.command(action='retire')
            process=Mock();process.poll.return_value=None;session.process=process
            with patch.object(session,'command',side_effect=error):session.close_process()
            process.terminate.assert_called_once();process.wait.assert_called_once_with(5)
            self.assertIsNone(session.process)

    def test_command_retry_remains_cancellable(self):
        with tempfile.TemporaryDirectory() as folder:
            session=DriveSession(HarnessProject());session.control=Path(folder)
            error=PermissionError('locked');error.winerror=32
            with patch('frame_harness.session.write_json',side_effect=lambda p,d:p.write_text(json.dumps(d))),patch('frame_harness.session.os.replace',side_effect=error),patch.object(session,'check_cancel',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):session.command(action='run')

    def test_nonowned_profile_rejected_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'user-file').write_text('keep')
            with self.assertRaises(ValueError):
                with DriveSession(HarnessProject(userpath=root)):pass
            self.assertEqual([p.name for p in root.iterdir()],['user-file'])

    def test_exception_closes_only_owned_process_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            project=HarnessProject(userpath=Path(folder)/'profile')
            process=Mock();process.poll.return_value=None
            with self.assertRaisesRegex(RuntimeError,'test'):
                with DriveSession(project) as session:
                    session.process=process
                    raise RuntimeError('test')
            process.wait.assert_called_once_with(5)
            self.assertIsNone(session.lock)
            command=json.loads((session.control/'control.json').read_text())
            self.assertEqual(command,dict(session_id=session.id,action='quit'))

    def test_retirement_ignores_foreign_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            project=HarnessProject(userpath=Path(folder)/'profile')
            with DriveSession(project) as session:
                process=Mock();process.poll.return_value=None;session.process=process
                write_json(session.control/'status.json',dict(session_id='old',state='ready'))
                with patch('frame_harness.session.time.monotonic',side_effect=[0,0,31,31]),patch('frame_harness.session.time.sleep'):
                    with self.assertRaisesRegex(RuntimeError,'did not retire'):session.retire()
                process.wait.assert_called_once()


class MeasurementTests(unittest.TestCase):
    def test_free_fixture_checks_relative_motion_despite_origin_readback_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pt=np.arange(.0005,4.001,.0005);t=np.arange(.02,4,.02)
            response=dict(t=pt,velocity=1+np.where((pt>=1)&(pt<3),.2,0.),initial=np.zeros((1,3)),
                          pattern=np.array([[1,0,0]]),data=np.array([[[0,7]]]))
            anchor=np.column_stack([np.ones(len(pt)),np.zeros((len(pt),2))])
            np.savetxt(root/'probes.csv',anchor,delimiter=',',header='avx,avy,avz',comments='')
            drift=np.sin(t)*.03+t
            motion=np.clip(t-.02-1,0,2)*.2
            gfx=np.column_stack([t,np.full(len(t),7),drift+motion,np.zeros((len(t),2)),drift,np.zeros((len(t),2))])
            np.savetxt(root/'gfx.csv',gfx,delimiter=',',header='t,cid,x,y,z,ax,ay,az',comments='')
            meta=dict(moving_measurement_anchor='a',nodes=[dict(name='a',initial=[0,0,0])])
            check=graphics_velocity_check(root,meta,response,dict(load_nodes=['p'],duration=4,settle_s=1),4)
            self.assertTrue(check['position_velocity_consistent'])
            response['velocity']=-response['velocity']
            self.assertFalse(graphics_velocity_check(root,meta,response,dict(load_nodes=['p'],duration=4,settle_s=1),4)['position_velocity_consistent'])

    def test_cadence_lag_and_initial_offset_pass_but_wrong_motion_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pt=np.arange(.0005,4.001,.0005)
            velocity=np.where((pt>=1)&(pt<3),.2,0.)
            response=dict(t=pt,velocity=velocity,initial=np.zeros((1,3)),pattern=np.array([[1,0,0]]),data=np.array([[[0,7]]]))
            t=np.arange(.02,4,.02);position=np.clip(t-.02-1,0,2)*.2
            scenario=dict(load_nodes=['p'],duration=4,settle_s=1)
            for scale,expected in [(1,True),(-1,False),(2,False)]:
                data=np.column_stack([t,np.full(len(t),7),position*scale+.00006,np.zeros((len(t),2))])
                np.savetxt(root/'gfx.csv',data,delimiter=',',header='t,cid,x,y,z',comments='')
                check=graphics_velocity_check(root,{},response,scenario,3)
                self.assertEqual(check['position_velocity_consistent'],expected)
            np.savetxt(root/'gfx.csv',data[:10],delimiter=',',header='t,cid,x,y,z',comments='')
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                graphics_velocity_check(root,{},response,scenario,3)

if __name__=='__main__':unittest.main()
