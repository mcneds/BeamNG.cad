import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness import component_tests as module


class ComponentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_rejected_sample_survives_failed_recording(self):
        failure=dict(time=11.9,rejected_nodes=[dict(node='panel_n2',component='panel',displacement_m=100.1)],
                     applied_force_n=0,natural_release_complete=True)
        result=module.analyze(self.root,{},'mount_load_release',dict(status='failed',
            reason='Component telemetry travel limit: panel / panel_n2',telemetry_failure=failure))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['recording_status'],'failed')
        self.assertEqual(result['telemetry_failure'],failure)
        self.assertIn('travel limit',result['reason'])

    def test_mount_site_diagnostic_cannot_silently_change_other_scenarios(self):
        with self.assertRaisesRegex(ValueError,'requires force release'):
            module.run_components(self.root/'manifest.json','component_load',None,mount_load_application='mount_sites')
        with self.assertRaisesRegex(ValueError,'Unknown mount load'):
            module.run_components(self.root/'manifest.json','mount_load_release',None,mount_load_application='typo')

    def test_completion_does_not_accept_short_or_nonfinite_measurements(self):
        for value in (2,float('nan')):
            with (self.root/'component.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','relative_speed','internal_broken'])
                for i in range(20):writer.writerow([i*value/19,0,0])
            result=module.analyze(self.root,{},'component_settle',{'status':'completed','samples':20})
            self.assertEqual(result['status'],'failed')
            self.assertIn('Invalid telemetry',result['reason'])

    def test_release_requires_current_guard_evidence_but_not_bounded_rigid_translation(self):
        manifest=dict(expected_dry_mass_kg=6,nodes={'n':{}},mounts=[dict(id='bolt',group='bolt',edges=[['a','n']])])
        module.write_json(self.root/'compiled.json',dict(node_count=1,mass_kg=6))
        module.write_json(self.root/'mount_events.json',dict(job_id='j',events=dict(natural=[dict(time=6,applied_force_n=100,mounts={'bolt':dict(broken=1)})])))
        completion=dict(status='completed',job_id='j',samples=701,travel_guard='detached_translation_removed_v1')
        def evaluate(guarded):
            with (self.root/'component.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','relative_speed','internal_broken','maximum_component_displacement','maximum_guarded_displacement'])
                for i in range(701):writer.writerow([i*.02,20,0,i*.2,guarded])
            with patch.object(module,'usable_capture',return_value=True):return module.analyze(self.root,manifest,'mount_load_release',completion)
        result=evaluate(2)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['metrics']['final_displacement_m'],140)
        self.assertFalse(evaluate(101)['checks']['release_travel_guard'])
        completion.pop('travel_guard')
        self.assertFalse(evaluate(2)['checks']['release_travel_guard'])

    def test_compact_success_keeps_images_and_hashed_measurements(self):
        for name in ('component.csv','beamng.log','job.json','build_manifest.json','motion_diagnostics.json',
                     'startup_powertrain.json','release_diagnostics.json','recorder_completion.json','motion_comparison.json','result.json','final.png'):
            (self.root/name).write_bytes(b'evidence')
        module.compact_success(self.root)
        self.assertFalse((self.root/'component.csv').exists())
        self.assertFalse((self.root/'motion_diagnostics.json').exists())
        self.assertFalse((self.root/'startup_powertrain.json').exists())
        self.assertFalse((self.root/'release_diagnostics.json').exists())
        self.assertTrue((self.root/'motion_comparison.json').exists())
        self.assertTrue((self.root/'final.png').exists())
        record=json.loads((self.root/'compact-evidence.json').read_text())
        self.assertIn('result.json',record['retained_sha256'])
        self.assertIn('component.csv',record['discarded_sha256'])
        module.compact_success(self.root)
        again=json.loads((self.root/'compact-evidence.json').read_text())
        self.assertEqual(record['discarded_sha256'],again['discarded_sha256'])

    def test_optional_compaction_keeps_locked_log_without_losing_evidence(self):
        log=self.root/'session.log';log.write_bytes(b'locked log')
        raw=self.root/'component.csv';raw.write_bytes(b'raw')
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==log:raise PermissionError('Windows sharing violation')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):module.compact_success(self.root)
        record=json.loads((self.root/'compact-evidence.json').read_text())
        self.assertTrue(log.exists());self.assertFalse(raw.exists())
        self.assertEqual(record['retained_locked'],['session.log'])
        self.assertIn('session.log',record['retained_sha256'])
        self.assertNotIn('session.log',record['discarded_sha256'])

    def test_fixed_only_mounts_skip_release_and_require_three_repeats(self):
        manifest=self.root/'manifest.json';manifest.write_text('{}')
        with patch.object(module,'intake',return_value=({'mounts':[{'group':''}]},self.root)), \
             patch.object(module,'DriveSession',return_value=MagicMock()), \
             patch.object(module,'compact_success') as compact, \
             patch.object(module,'run_components',side_effect=lambda p,s,se:{'status':'passed','recording_status':'completed','scenario':s,'directory':str(self.root)}) as run:
            result=module.verify(manifest,self.root,self.root,3)
            self.assertEqual(run.call_count,6)
            self.assertEqual(result['qualification_status'],'mounting_verified')
            self.assertEqual(compact.call_count,6)
            self.assertTrue(all(r['scenario']!='mount_release' for r in result['results']))

    def test_compact_vehicle_report_keeps_plot_without_dead_diagnostic_links(self):
        import hashlib
        from frame_harness.vehicle_report import write_report
        result=dict(scenario='settle',status='passed',metrics={},checks={})
        (self.root/'result.json').write_text(json.dumps(result))
        (self.root/'vehicle.csv').write_text('t,speed\n')
        (self.root/'beamng.log').write_text('diagnostics')
        (self.root/'telemetry.png').write_bytes(b'recorded plot')
        write_report(self.root,result)
        module.compact_success(self.root)
        report=(self.root/'report.html').read_text(encoding='utf-8')
        self.assertNotIn('href="vehicle.csv"',report)
        self.assertNotIn('href="beamng.log"',report)
        self.assertIn('src="telemetry.png"',report)
        record=json.loads((self.root/'compact-evidence.json').read_text())
        self.assertEqual(record['retained_sha256']['report.html'],hashlib.sha256((self.root/'report.html').read_bytes()).hexdigest())

    def test_failed_measurement_retains_diagnostics_and_stops_batch(self):
        manifest=self.root/'manifest.json';manifest.write_text('{}')
        with patch.object(module,'intake',return_value=({'mounts':[{'group':'bolt'}]},self.root)), \
             patch.object(module,'DriveSession',return_value=MagicMock()), \
             patch.object(module,'compact_success') as compact, \
             patch.object(module,'run_components',return_value={'status':'failed','recording_status':'completed','directory':str(self.root)}) as run:
            result=module.verify(manifest,self.root,self.root,3)
            self.assertEqual(run.call_count,1)
            self.assertEqual(result['qualification_status'],'not_qualified')
            self.assertTrue(result['full_report_saved'])
            compact.assert_not_called()
    def test_staging_changes_only_final_fixture_and_keeps_visual_assets_untouched(self):
        source=self.root/'source';source.mkdir();vehicle=self.root/'vehicle'
        part={'nodes':[['id','posX','posY','posZ'],['n',0,0,0,{'nodeWeight':1}]],'beams':[['id1:','id2:']]}
        module.write_json(source/'frame.jbeam',{'frame':part});(source/'mesh.dae').write_bytes(b'mesh');(source/'main.materials.json').write_text('{}')
        _,changed,_=module.stage_components(source,vehicle,'fixture',[],self.root)
        self.assertEqual(len(changed),3);times={p.name:p.stat().st_mtime_ns for p in vehicle.iterdir()}
        _,changed,_=module.stage_components(source,vehicle,'fixture',['n'],self.root)
        self.assertEqual(changed,['/vehicles/fixture/frame.jbeam'])
        self.assertTrue(json.loads((vehicle/'frame.jbeam').read_text())['frame']['nodes'][1][-1]['fixed'])
        self.assertEqual((vehicle/'mesh.dae').stat().st_mtime_ns,times['mesh.dae'])
        self.assertEqual((vehicle/'main.materials.json').stat().st_mtime_ns,times['main.materials.json'])
        _,changed,written=module.stage_components(source,vehicle,'fixture',['n'],self.root)
        self.assertEqual((changed,written),([],0))
        module.stage_components(source,vehicle,'fixture',[],self.root)
        self.assertNotIn('fixed',json.loads((vehicle/'frame.jbeam').read_text())['frame']['nodes'][1][-1])
        self.assertNotIn('fixed',json.loads((source/'frame.jbeam').read_text())['frame']['nodes'][1][-1])

    def test_rack_sweep_rejects_missing_measurements_and_axis_drift(self):
        import math
        count=801;travel=.01
        manifest=dict(nodes={'n':{}},expected_dry_mass_kg=6.,steering_contract=dict(half_travel_m=travel))
        with (self.root/'component.csv').open('w',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['t','relative_speed','broken','internal_broken','maximum_component_displacement'])
            for i in range(count):writer.writerow([i*.02,.001,0,0,0])
        module.write_json(self.root/'compiled.json',dict(node_count=1,mass_kg=6.))
        module.write_json(self.root/'rack_compiled.json',dict(job_id='j',rails=3,slidenodes=3))
        from PIL import Image
        image=Image.new('RGB',(64,64))
        image.putdata([(220,120,40) if (x//8+y//8)%2 else (25,40,80)
                       for y in range(64) for x in range(64)])
        for label in ('first_mount','release','final'):
            image.save(self.root/(label+'.png'),compress_level=0)
        completion=dict(status='completed',job_id='j',samples=count)
        self.assertEqual(module.analyze(self.root,manifest,'rack_sweep',completion)['status'],'failed')
        samples=[dict(t=i*.02,target_m=travel*math.sin(i*.02),shift_m=travel*math.sin(i*.02),error_m=.0001,housing_error_m=0) for i in range(count)]
        module.write_json(self.root/'rack_motion.json',dict(job_id='j',samples=samples))
        self.assertEqual(module.analyze(self.root,manifest,'rack_sweep',completion)['status'],'passed')
        valid_capture=(self.root/'final.png').read_bytes()
        (self.root/'final.png').write_bytes(b'capture'*200)
        result=module.analyze(self.root,manifest,'rack_sweep',completion)
        self.assertFalse(result['checks']['capture_final']);self.assertEqual(result['status'],'failed')
        (self.root/'final.png').write_bytes(valid_capture)
        samples[400]['error_m']=.005
        module.write_json(self.root/'rack_motion.json',dict(job_id='j',samples=samples))
        result=module.analyze(self.root,manifest,'rack_sweep',completion)
        self.assertFalse(result['checks']['rack_tracks_actuator']);self.assertEqual(result['status'],'failed')

    def test_mounts_only_does_not_overwrite_full_vehicle_driving_qualification(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
        import component_worker as worker
        manifest=self.root/'manifest.json';module.write_json(manifest,dict(capabilities=['vehicle','mounts']))
        receipt=dict(qualification_status='vehicle_verified',recording_status='completed')
        result=dict(status='passed',recording_status='completed',qualification_status='mounting_verified')
        module.write_json(self.root/'component-verification.json',result)
        with patch.object(sys,'argv',['worker','verify','--mounts-only','--manifest',str(manifest),'--game',str(self.root),'--profile',str(self.root)]), \
             patch.object(worker,'completed_build',return_value=(receipt,None)),patch.object(module,'verify',return_value=result):
            worker.main()
        saved=json.loads((self.root/'static_frame_build.json').read_text())
        self.assertEqual(saved['qualification_status'],'vehicle_verified')
        self.assertEqual(saved['mounting_qualification_status'],'mounting_verified')


if __name__=='__main__':unittest.main()
