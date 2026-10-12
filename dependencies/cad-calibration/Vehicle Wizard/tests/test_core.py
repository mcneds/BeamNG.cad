import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from support import fixture
from vehicle_wizard.project import VehicleProject,circle_center,matrix,sha256
from vehicle_wizard.kinematics import Mechanism,inspect_all
from vehicle_wizard.build import build_vehicle,expanded,install_build
from frame_harness.vehicle import intake


class CoreTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.p=fixture(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_save_resume_and_attached_point_world_transform(self):
        p=self.p;key=p.owners()['engine_mesh'];p.set_point('attached',[.1,1.7,.5],key)
        p.move([key],[.2,0,0],[0,0,0]);np.testing.assert_allclose(p.point('attached'),[.3,1.7,.5])
        p.undo();np.testing.assert_allclose(p.point('attached'),[.1,1.7,.5]);p.redo()
        q=VehicleProject.load(p.path);np.testing.assert_allclose(q.point('attached'),[.3,1.7,.5]);self.assertFalse(q.data['corners']['FL']['confirmed'])
    def test_world_motion_with_rotated_intake(self):
        p=self.p;key=p.owners()['engine_mesh'];p.data['orientation']=matrix(rotation=[0,0,90]).tolist();p.set_point('attached',[0,1,0],key)
        p.move([key],[1,0,0],[0,0,0]);np.testing.assert_allclose(p.point('attached'),[1,1,0],atol=1e-10)
    def test_circle_center_and_reject_collinear(self):
        np.testing.assert_allclose(circle_center([[1,0,2],[0,1,2],[-1,0,2]]),[0,0,2])
        with self.assertRaises(ValueError):circle_center([[0,0,0],[1,0,0],[2,0,0]])
    def test_exclusive_ownership_and_preserved_placement(self):
        p=self.p;old=p.owners()['engine_mesh'];p.move([old],[.1,0,0],[0,0,0]);new=p.assign('New engine','engine',['engine_mesh'],mass=30)
        self.assertFalse(p.data['components'][old]['meshes']);self.assertEqual(p.owners()['engine_mesh'],new)
        self.assertAlmostEqual(p.data['components'][new]['transform'][0][3],.1)
    def test_regroup_differently_placed_meshes_preserves_world_geometry(self):
        p=self.p;key=p.owners()['engine_mesh'];p.move([key],[.2,0,0],[0,0,45]);p.set_point('mount',[.1,1.7,.4],key,mesh='engine_mesh')
        ids=['engine_mesh','wheel_FL'];before={m:p.object_transform(m).copy() for m in ids};point=p.point('mount').copy()
        p.assign('Assembly','fixed_accessory',ids,mass=36)
        for m in ids:np.testing.assert_allclose(p.object_transform(m),before[m],atol=1e-10)
        np.testing.assert_allclose(p.point('mount'),point,atol=1e-10)
        p.unassign(ids)
        for m in ids:np.testing.assert_allclose(p.object_transform(m),before[m],atol=1e-10)
    def test_kinematics_all_corners_and_mirror(self):
        checks=inspect_all(self.p)
        for check in checks.values():self.assertEqual(check['degrees_of_freedom'],1);self.assertGreater(check['motion_ratio'],.05)
        self.p.mirror_corner('FL','FR');self.assertFalse(self.p.data['corners']['FR']['confirmed'])
        self.assertAlmostEqual(Mechanism(self.p,'FL').inspect()['motion_ratio'],Mechanism(self.p,'FR').inspect()['motion_ratio'],places=5)
    def test_preview_carries_rigid_meshes_without_changing_project(self):
        p=self.p;before=copy.deepcopy(p.data);mechanism=Mechanism(p,'FL');x,pose=mechanism.solve(.03)
        delta=mechanism.component_transforms(x)['lower_arm'];point=p.corner_points('FL')['lower_ball']
        np.testing.assert_allclose(delta[:3,:3]@point+delta[:3,3],pose['lower_ball'],atol=1e-6)
        self.assertEqual(before,p.data)
    def test_missing_link_and_degenerate_geometry_rejected(self):
        p=self.p;p.data['corners']['RL']['links'].pop()
        with self.assertRaises(ValueError):Mechanism(p,'RL').inspect()
        self.assertTrue(any('locating links' in x for x in p.validate(True)))
    def test_build_preserves_source_graph_mass_and_has_no_fixture_pins(self):
        p=self.p;original=sha256(p.data['frame']);path=build_vehicle(p,lambda _:None);m,folder=intake(path)
        part=json.loads((folder/(m['model']+'.jbeam')).read_text())[m['model']];nodes={r[0]:(r,o) for r,o in expanded(part['nodes'])}
        source=json.loads(Path(p.data['frame']).read_text())['fixture']
        for row,_ in expanded(source['nodes']):np.testing.assert_allclose(nodes[row[0]][0][1:4],row[1:4])
        self.assertTrue(all(not opt.get('fixed') for _,opt in nodes.values()));self.assertEqual(original,sha256(p.data['frame']))
        self.assertEqual(len(part['pressureWheels'])-1,4);self.assertEqual(m['expected_dry_mass_kg'],sum(opt['nodeWeight'] for _,opt in nodes.values())+24)
        self.assertEqual(part['driveSelector']['defaultMode'],'rwd');self.assertTrue(m['allows_generated_wheel_graph'])
        archive=install_build(path,Path(self.temp.name)/'mods');self.assertTrue(archive.exists())
        # Intake catches edited outputs; it never silently tests a different build.
        with (folder/'base.pc').open('a') as f:f.write(' ')
        with self.assertRaises(ValueError):intake(path)
    def test_build_blocked_for_unconfirmed_geometry(self):
        self.p.data['corners']['FR']['confirmed']=False
        with self.assertRaisesRegex(ValueError,'FR: confirm'):build_vehicle(self.p)
    def test_two_endpoint_components_receive_volumetric_skin_binding(self):
        p=self.p;p.assign('Shock body','shock_body',['wheel_FL'],'FL',1)
        for c in p.data['corners'].values():c['confirmed']=True
        path=build_vehicle(p,lambda _:None);m,folder=intake(path)
        part=json.loads((folder/(m['model']+'.jbeam')).read_text())[m['model']]
        points=np.array([r[1:4] for r,o in expanded(part['nodes']) if 'FL_shock_body' in o['group']])
        self.assertGreaterEqual(len(points),4);self.assertEqual(np.linalg.matrix_rank(points-points[0]),3)
    def test_fingerprint_changes_on_source_frame_edit_but_not_view(self):
        p=self.p;before=p.fingerprint();p.data['view']['hidden']=['frame_mesh'];self.assertEqual(before,p.fingerprint())
        with Path(p.data['frame']).open('a') as f:f.write(' ')
        self.assertNotEqual(before,p.fingerprint())


if __name__=='__main__':unittest.main()
