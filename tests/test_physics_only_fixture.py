import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('drive_probe',Path(__file__).resolve().parents[1]/'tools/probe-drive-execution.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class PhysicsOnlyFixtureTests(unittest.TestCase):
    def test_only_render_sections_removed_without_source_mutation(self):
        original={'car':{'nodes':[['id'],['a',0,0,0,{'nodeWeight':2}]],'beams':[['id1:','id2:']],
            'pressureWheels':[['name'],['FR',{'pressurePSI':12}]],'triangles':[['id1:','id2:','id3:']],
            'powertrain':[['type'],['engine']], 'flexbodies':[['mesh'],['body']], 'props':[['mesh'],['arm']]}}
        changed,removed=probe.strip_render_sections(original)
        self.assertIn('props',original['car']);self.assertNotIn('props',changed['car'])
        self.assertEqual(changed['car'],{k:v for k,v in original['car'].items() if k not in ('props','flexbodies')})
        self.assertEqual(removed['car']['flexbodies'],2)

    def test_mesh_removal_is_limited_to_owned_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vehicle=root/'vehicle';run=root/'run';vehicle.mkdir();run.mkdir()
            (root/'source.dae').write_text('preserve');(vehicle/'mesh.dae').write_text('staged')
            (vehicle/'car.jbeam').write_text(json.dumps({'car':{'nodes':[['id']], 'props':[['mesh']]}}))
            changed=[];report=probe.physics_only_fixture(vehicle,run,'car',changed)
            self.assertTrue((root/'source.dae').is_file());self.assertFalse((vehicle/'mesh.dae').exists())
            self.assertIn('/vehicles/car/mesh.dae',changed);self.assertEqual(len(report['removed_meshes']),1)
            self.assertEqual(json.loads((vehicle/'car.jbeam').read_bytes()),{'car':{'nodes':[['id']]}})

    def test_normal_staging_restores_full_render_assets(self):
        from frame_harness.assets import stage_vehicle
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';vehicle=root/'vehicle';run=root/'run'
            source.mkdir();vehicle.mkdir();run.mkdir()
            original={'car':{'nodes':[['id']], 'props':[['mesh'],['body']]}}
            (source/'car.jbeam').write_text(json.dumps(original));(source/'mesh.dae').write_text('mesh')
            stage_vehicle(source,vehicle,'car');probe.physics_only_fixture(vehicle,run,'car',[])
            changed,_=stage_vehicle(source,vehicle,'car')
            self.assertEqual((vehicle/'mesh.dae').read_bytes(),(source/'mesh.dae').read_bytes())
            self.assertEqual(json.loads((vehicle/'car.jbeam').read_bytes()),original)
            self.assertEqual(set(changed),{'/vehicles/car/car.jbeam','/vehicles/car/mesh.dae'})

if __name__=='__main__':unittest.main()
