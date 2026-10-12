import csv,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle import analyze


def fixture_capture(path):
    from PIL import Image, ImageDraw
    image=Image.new('RGB',(128,128),'gray')
    ImageDraw.Draw(image).rectangle((20,20,100,100),fill='blue')
    image.save(path,compress_level=0)


class VehicleMeasurementTests(unittest.TestCase):
    def test_rigid_accessory_uses_native_prop_load_evidence(self):
        from frame_harness.vehicle import rendered_meshes_loaded
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=dict(component_meshes={'tabs':['tab_mesh']})
            for job,loaded,expected in [('current',True,True),('current',False,False),('current',None,False),('old',True,False)]:
                (root/'render_meshes.json').write_text(json.dumps(dict(job_id=job,success=True,vertices={},props={'tab_mesh':loaded})))
                self.assertEqual(rendered_meshes_loaded(root,manifest,dict(job_id='current')),expected)

    def test_coilover_props_need_native_load_evidence_not_flexbody_counts(self):
        from frame_harness.vehicle import rendered_meshes_loaded
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=dict(component_meshes={'shock':['housing','shaft','spring']},coilover_render={'shock':dict(meshes=dict(housing=['housing'],shaft=['shaft'],spring=['spring']))})
            evidence=dict(job_id='current',success=True,vertices={'spring':30},props={'housing':True,'shaft':True})
            for present,expected in [(True,True),(False,False),(None,False)]:
                evidence['props']['shaft']=present
                (root/'render_meshes.json').write_text(json.dumps(evidence))
                self.assertEqual(rendered_meshes_loaded(root,manifest,dict(job_id='current')),expected)

    def test_missing_or_stale_rendered_component_is_rejected(self):
        from frame_harness.vehicle import rendered_meshes_loaded
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=dict(component_meshes={'tie':['tie_mesh'],'body':['body_mesh']})
            completion=dict(job_id='current')
            for job,count,expected in [('current',30,True),('current',0,False),('previous',30,False),('current',None,False)]:
                evidence=dict(job_id=job,success=True,vertices={'tie_mesh':count,'body_mesh':100})
                (root/'render_meshes.json').write_text(json.dumps(evidence))
                self.assertEqual(rendered_meshes_loaded(root,manifest,completion),expected)

    def test_parking_lock_compilation_must_match_recoil_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            manifest=dict(expected_dry_mass_kg=10,device_contract={'parking_lock':dict(spring_nm_rad=4.,damping_nm_s_rad=.003)})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for damp,status in [(.003,'passed'),(.24,'failed'),(None,'failed'),(float('nan'),'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,device_graph={'gearbox':dict(parkLockSpring=4.,parkLockDamp=damp)})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],status)

    def test_wrong_or_missing_native_inertia_order_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=['frontOutputGear','rearDifferential']
            manifest=dict(expected_dry_mass_kg=10,device_contract={'devices':{'rearCarrierTakeoff':{'inertiaChildren':expected}}})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for actual,status in [(expected,'passed'),(expected[::-1],'failed'),([],'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,device_graph={'rearCarrierTakeoff':{'inertiaChildren':actual}})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],status)

    def test_loaded_wheel_axle_mass_is_measured_in_the_compiled_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            manifest=dict(expected_dry_mass_kg=10,wheels={'FL':dict(nodes=dict(axis_in='a',axis_out='b'),mass_allocation=dict(minimum_support_node_kg=2.))})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for value,status in [(2.,'passed'),(.8,'failed'),(None,'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,actual_nodes={'a':dict(mass_kg=value),'b':dict(mass_kg=2.)})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],status)

    def test_all_loaded_support_floors_are_checked_independently_of_total_mass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            manifest=dict(expected_dry_mass_kg=10,numerical_mass=dict(nodes={
                'joint':dict(target_kg=2.),'reaction':dict(target_kg=3.)}))
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for value,expected in [(3.,True),(3.-5e-7,True),(2.,False),(None,False),
                                   (float('nan'),False),(float('inf'),False),(True,False)]:
                with self.subTest(value=value):
                    (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,actual_nodes={
                        'joint':dict(mass_kg=2.),'reaction':dict(mass_kg=value)})))
                    result=analyze(root,manifest,'settle',dict(status='completed',samples=31))
                    self.assertEqual(result['checks']['loaded_node_mass_floors_compiled'],expected)
                    self.assertEqual(result['status'],'passed' if expected else 'failed')
                    self.assertEqual(set(result['metrics']['loaded_node_mass_floor_failures']),set() if expected else {'reaction'})
                    json.dumps(result,allow_nan=False)
            (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,actual_nodes={})))
            result=analyze(root,manifest,'settle',dict(status='completed',samples=31))
            self.assertFalse(result['checks']['loaded_node_mass_floors_compiled'])

    def test_frame_contact_policy_must_preserve_external_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=dict(self_collision=False,collision=True,static_collision=True)
            manifest=dict(expected_dry_mass_kg=10,collision_policy=dict(frame_nodes={'f':expected}))
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for actual,status in [(expected,'passed'),(expected|{'collision':False},'failed'),
                                  (expected|{'self_collision':True},'failed'),({},'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,actual_nodes={'f':actual})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],status)

    def test_wrong_or_missing_engine_reaction_axis_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=['axis1','axis2','arm']
            manifest=dict(expected_dry_mass_kg=10,device_contract={'devices':{'mainEngine':{'torqueReactionNodes':expected}}})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                w=csv.writer(stream);w.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):w.writerow([i,0,0,0,1])
            for actual,status in [(expected,'passed'),(expected[::-1],'failed'),([],'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,device_graph={'mainEngine':{'torqueReactionNodes':actual}})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],status)

    def test_opposite_wheel_oscillation_cannot_pass_using_absolute_mean_speed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);corners=['FL','FR','RL','RR']
            manifest=dict(expected_dry_mass_kg=10,expected_wheel_names=corners,
                          device_contract=dict(driven_wheels=corners,front_rear_speed_ratio=1))
            fixture_capture(root/'final.png');(root/'compiled.json').write_text(json.dumps(dict(mass_kg=10)))
            for oscillating,status in [(False,'passed'),(True,'failed')]:
                with (root/'vehicle.csv').open('w',newline='') as stream:
                    w=csv.writer(stream);w.writerow(['t','speed','relative_node_speed','broken','cvt_ratio']+['av_'+c for c in corners])
                    for i in range(181):w.writerow([i/10,0,0,0,1+i/1000]+[10*(-1 if oscillating and i%2 else 1)]*4)
                result=analyze(root,manifest,'supported',dict(status='completed',samples=181,fixture_minimum_clearance_m=1))
                self.assertTrue(result['checks']['geared_axle_ratio']);self.assertEqual(result['status'],status)

    def test_unbound_drive_reaction_cannot_pass_on_speed_or_mass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);reaction=dict(nodeArm='brake',torqueCoupling='housing_axis',torqueArm='housing_arm',torqueArm2='housing_axis2')
            manifest=dict(expected_dry_mass_kg=10,wheels={'RL':{'reaction_nodes':reaction}})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                w=csv.writer(stream);w.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):w.writerow([i,0,0,0,1])
            for actual,expected in [(reaction,'passed'),({},'failed'),(reaction|{'torqueArm':'wrong'},'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,tire_physics={'RL':{'reaction_nodes':actual}})))
                self.assertEqual(analyze(root,manifest,'settle',dict(status='completed',samples=31))['status'],expected)

    def test_suspended_test_requires_measured_tire_ground_clearance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=dict(expected_dry_mass_kg=10,expected_wheel_names=[])
            fixture_capture(root/'final.png')
            (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10)))
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(25):writer.writerow([i,0,0,0,1])
            for clearance,expected in [(None,'failed'),(0,'failed'),(.249,'failed'),(float('nan'),'failed'),(.25,'passed'),(1.9,'passed')]:
                completion=dict(status='completed',samples=25,fixture_minimum_clearance_m=clearance)
                self.assertEqual(analyze(root,manifest,'articulation',completion)['status'],expected)

    def test_speed_success_without_required_motion_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            manifest=dict(expected_dry_mass_kg=10,template_definition={'version':1})
            fixture_capture(root/'final.png')
            (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10)))
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','forward_speed','relative_node_speed','broken','up_z'])
                for i in range(51):writer.writerow([i/2,10,10,0,0,1])
            result=analyze(root,manifest,'acceleration',dict(status='completed',samples=51,job_id='current'))
            self.assertTrue(result['checks']['20kmh_within_20s'])
            self.assertFalse(result['checks']['motion_reference_complete'])
            self.assertEqual(result['status'],'failed')

    def test_stale_motion_recording_cannot_be_used_for_current_job(self):
        from frame_harness.vehicle_motion import analyze_motion
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'motion_diagnostics.json').write_text(json.dumps(dict(job_id='previous')))
            with self.assertRaisesRegex(ValueError,'identity differs'):
                analyze_motion(root,{},'acceleration',25,'current')

    def test_failed_last_recording_is_not_reported_as_complete_by_worker(self):
        sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
        import component_worker
        import verification_receipts
        result=dict(status='failed',completed_runs=24,required_runs=24,recording_status='incomplete')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=root/'manifest.json';manifest.write_text(json.dumps(dict(capabilities=['vehicle'])))
            result.update(manifest_sha256=verification_receipts.digest(manifest),verifier_unchanged=True)
            (root/'tests').mkdir();(root/'tests/acceptance.json').write_text(json.dumps(result))
            argv=['component_worker.py','verify','--manifest',str(manifest),'--game',str(root),'--profile',str(root/'owned')]
            with patch.object(sys,'argv',argv),patch.object(component_worker,'completed_build',return_value=({},root/'package.zip')), \
                 patch.object(verification_receipts,'completed_build',return_value=({},root/'package.zip')),patch('frame_harness.vehicle.run_acceptance',return_value=result):
                with self.assertRaisesRegex(ValueError,'Vehicle acceptance failed'):component_worker.main()
            receipt=json.loads((root/'static_frame_build.json').read_text())
            self.assertEqual(receipt['recording_status'],'incomplete')
            self.assertEqual(receipt['qualification_status'],'failed')

    def test_finished_recording_cannot_hide_a_failed_controller_or_unsettled_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest={'expected_dry_mass_kg':10,'required_controllers':{'cadSkin':{'region_count':4}}}
            fixture_capture(root/'final.png')
            for controllers,speed,expected in [({'cadSkin':{'region_count':4}},0,'passed'),({},0,'failed'),({'cadSkin':{'region_count':4}},.3,'failed')]:
                (root/'compiled.json').write_text(json.dumps({'mass_kg':10,'controllers':controllers}))
                with (root/'vehicle.csv').open('w',newline='') as stream:
                    w=csv.writer(stream);w.writerow(['t','speed','relative_node_speed','broken','up_z'])
                    for i in range(31):w.writerow([i,0,speed,0,1])
                result=analyze(root,manifest,'settle',{'status':'completed','samples':31})
                self.assertEqual(result['status'],expected)
                self.assertEqual(analyze(root,manifest,'settle',{'status':'completed','samples':32})['status'],'failed')

    def test_missing_pressure_tire_collision_cannot_pass_as_a_wheel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            contract=dict(wheel_section='pressureWheels',tread_nodes=32,hub_nodes=32,axle_nodes=['outer','inner'],wheel_direction=-1,reinforcement_l_beams=32)
            manifest=dict(expected_dry_mass_kg=10,wheels={'FL':{'tire_contract':contract}})
            fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                w=csv.writer(stream);w.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):w.writerow([i,0,0,0,1])
            tire=contract|dict(collision_nodes=32,self_collision_nodes=0,pressure_group='pressure_FL',pressure_pa=180000)
            for change,expected in [({},'passed'),({'wheel_section':'rotators'},'failed'),({'collision_nodes':0},'failed'),({'pressure_pa':0},'failed'),({'tread_nodes':0},'failed'),
                                    ({'axle_nodes':['inner','outer']},'failed'),({'axle_nodes':None},'failed'),({'wheel_direction':1},'failed'),
                                    ({'reinforcement_l_beams':0},'failed'),({'reinforcement_l_beams':None},'failed')]:
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,tire_physics={'FL':tire|change})))
                result=analyze(root,manifest,'settle',{'status':'completed','samples':31})
                self.assertEqual(result['status'],expected)

    def test_diagnostic_intervention_never_qualifies_even_with_passing_motion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fixture_capture(root/'final.png')
            with (root/'vehicle.csv').open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['t','speed','relative_node_speed','broken','up_z'])
                for i in range(31):writer.writerow([i,0,0,0,1])
            for marker in ('compiled.json','job.json'):
                (root/'compiled.json').write_text(json.dumps(dict(mass_kg=10,**({'diagnostic':'no_aero'} if marker=='compiled.json' else {}))))
                (root/'job.json').write_text(json.dumps({'diagnostic':'no_aero'} if marker=='job.json' else {}))
                result=analyze(root,{'expected_dry_mass_kg':10},'settle',{'status':'completed','samples':31})
                self.assertEqual(result['status'],'failed');self.assertEqual(result['qualification_status'],'not_qualified')
                self.assertFalse(result['checks']['qualification_without_diagnostic_intervention'])


if __name__=='__main__':unittest.main()
