import copy,json,sys,tempfile,unittest
from unittest.mock import Mock,patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness.component_tests import stage_components
from frame_harness.vehicle_diagnostics import balance_ballast


class VehicleDiagnosticTests(unittest.TestCase):
    def test_internal_contact_probe_resolves_defaults_and_preserves_surface_nodes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();vehicle=root/'owned';run=root/'run';run.mkdir()
            part=dict(nodes=[['id','posX','posY','posZ'],dict(staticCollision=True,collision=False),
                             ['internal',0,0,0],['surface',1,0,0,dict(collision=True)]],
                      pressureWheels=[['name'],['FL',dict(nodeWeight=1)]])
            path=source/'example.jbeam';path.write_text(json.dumps(dict(example=part)));before=path.read_bytes()
            stage_components(source,vehicle,'example',[],run,diagnostic='no_internal_static')
            after=json.loads((vehicle/path.name).read_text())['example']
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(after['nodes'][2][-1]['staticCollision'])
            self.assertEqual(after['nodes'][3],part['nodes'][3])
            self.assertEqual(after['pressureWheels'],part['pressureWheels'])

    def test_drop_keeps_assets_unchanged_and_cannot_qualify(self):
        from frame_harness import vehicle
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            manifest=dict(model='example',config='base.pc',spawn_z=.4)
            active=Mock(root=root/'owned',id='owned-session')
            active.execute.side_effect=lambda job,*args:dict(status='completed',job_id=job['id'])
            with patch.object(vehicle,'intake',return_value=(manifest,source)), \
                 patch.object(vehicle,'check_recording_space'), \
                 patch('frame_harness.vehicle_motion.reference',return_value={}), \
                 patch('frame_harness.component_tests.stage_components',return_value=([],[],0)) as stage, \
                 patch.object(vehicle,'analyze',return_value=dict(status='passed',qualification_status='qualified')), \
                 patch('frame_harness.vehicle_report.write_report'):
                result=vehicle.run_vehicle(root/'manifest.json','settle',project=Mock(),session=active,diagnostic='drop')
            job=active.execute.call_args.args[0]
            self.assertAlmostEqual(job['spawn_z'],3.4)
            self.assertEqual(job['fixture_fixed_nodes'],[])
            self.assertIsNone(stage.call_args.kwargs['diagnostic'])
            self.assertEqual(manifest['spawn_z'],.4)
            self.assertEqual(result['qualification_status'],'diagnostic_only')
            self.assertEqual(result['drop_height_m'],3.)
        with self.assertRaisesRegex(ValueError,'requires settling'):
            vehicle.run_vehicle('unused','acceleration',diagnostic='drop')

    def fixture(self):
        nodes={'left':dict(position=[-1,0,0],mass_kg=10),
               'right':dict(position=[1,0,0],mass_kg=10.2)}
        return dict(nodes=nodes,chassis_nodes=list(nodes),expected_dry_mass_kg=22.6,
                    wheels={'left':dict(wheel_mass_kg=1,nodes=dict(axis_in='left',axis_out='left')),
                            'right':dict(wheel_mass_kg=1.4,nodes=dict(axis_in='right',axis_out='right'))})

    def test_native_wheel_mass_is_counted_and_only_owned_copy_gets_counterweight(self):
        manifest=self.fixture();unchanged=copy.deepcopy(manifest)
        intervention=balance_ballast(manifest)
        self.assertAlmostEqual(intervention['added_mass_kg'],.6)
        self.assertFalse(intervention['qualification_allowed'])
        self.assertEqual(manifest,unchanged)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();vehicle=root/'owned/vehicles/example';run=root/'run';run.mkdir()
            (run/'build_manifest.json').write_text(json.dumps(manifest))
            part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*v['position'],dict(nodeWeight=v['mass_kg'])] for n,v in manifest['nodes'].items()])
            path=source/'example.jbeam';path.write_text(json.dumps(dict(example=part)));before=path.read_bytes()
            stage_components(source,vehicle,'example',[],run,diagnostic='balance_ballast')
            after=json.loads((vehicle/path.name).read_text())['example']['nodes']
            self.assertEqual(path.read_bytes(),before)
            self.assertAlmostEqual(after[1][-1]['nodeWeight'],10.6)
            self.assertEqual(after[2][-1]['nodeWeight'],10.2)
            self.assertTrue((run/'diagnostic-ballast.json').is_file())

    def test_unreconstructable_mass_or_excessive_intervention_is_rejected(self):
        manifest=self.fixture();manifest['expected_dry_mass_kg']+=1
        with self.assertRaisesRegex(ValueError,'reconstruct'):balance_ballast(manifest)
        manifest=self.fixture();manifest['nodes']['right']['mass_kg']+=10;manifest['expected_dry_mass_kg']+=10
        with self.assertRaisesRegex(ValueError,'five percent'):balance_ballast(manifest)

    def test_mass_matched_control_preserves_transverse_first_moment(self):
        manifest=self.fixture();balanced=balance_ballast(manifest);control=balance_ballast(manifest,symmetric=True)
        self.assertEqual(control['expected_total_mass_kg'],balanced['expected_total_mass_kg'])
        moment=sum(w['added_mass_kg']*manifest['nodes'][w['node']]['position'][0] for w in control['weights'])
        self.assertAlmostEqual(moment,0)
        self.assertGreater(control['expected_lateral_com_m'],0)


if __name__=='__main__':unittest.main()
