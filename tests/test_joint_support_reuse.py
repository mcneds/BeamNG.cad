import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'),
             str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness')]
from vehicle_templates import joint_supports


class JointSupportReuseTests(unittest.TestCase):
    def graph(self, points, preferred):
        return SimpleNamespace(groups={'body':list(points)},point=lambda n:np.array(points[n],float),
                               preferred_joint_supports={'body':preferred})

    def test_reuses_loaded_sites_without_moving_the_joint(self):
        points={'x':[1,0,0],'y':[0,1,0],'z':[0,0,1],
                'mesh_x':[.9,0,0],'mesh_y':[0,.9,0],'mesh_z':[0,0,.9]}
        for sign in (1,-1):
            graph=self.graph({n:np.array(p)*[sign,1,1]+[3,4,5] for n,p in points.items()},set('xyz'))
            self.assertEqual(set(joint_supports(graph,'body',np.array([3,4,5]))),set('xyz'))
            graph.preferred_joint_supports={}
            self.assertEqual(set(joint_supports(graph,'body',np.array([3,4,5]))),{'mesh_x','mesh_y','mesh_z'})

    def test_does_not_choose_weak_geometry_just_to_save_mass(self):
        points={'x':[1,0,0],'y':[0,1,0],'z':[0,0,1],
                'bad1':[1,.001,0],'bad2':[1,0,.001]}
        graph=self.graph(points,{'x','bad1','bad2'})
        selected=joint_supports(graph,'body',np.zeros(3))
        xyz=np.array([points[n] for n in selected]);distance=np.linalg.norm(xyz,axis=1)
        score=abs(np.linalg.det(xyz/distance[:,None]))/distance.mean()
        self.assertGreaterEqual(score,.5)
        self.assertNotEqual(set(selected),graph.preferred_joint_supports['body'])

    def test_generated_joint_locations_and_graph_size_are_preserved(self):
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        def run(reuse):
            def configure(spec,components,moments):
                spec['parameters'].update(reuse_loaded_joint_supports=reuse,
                    assembled_rigid_conditioning=True,loaded_node_mass_policy='reported_ballast')
            project,frame,spec,cad=fixture('ball_radius_toe',configure)
            with patch('components.read_geometry',side_effect=cad):return generate(project,frame,spec)[0]
        old,new=run(False),run(True)
        self.assertEqual(set(old.nodes),set(new.nodes))
        for n in old.nodes:self.assertEqual(old.nodes[n]['position'],new.nodes[n]['position'])
        before={j['id']:j for j in old.joints}
        for joint in new.joints:
            original=before[joint['id']]
            self.assertEqual(joint['kind'],original['kind'])
            if joint['kind']=='spherical':
                self.assertEqual(joint['nodes'][-1],original['nodes'][-1])
                self.assertEqual(joint['parent'],original['parent'])
                self.assertEqual(joint['child'],original['child'])
                self.assertTrue(set(joint['nodes'][:-1])<=set(new.groups[joint['parent']]))
            else:self.assertEqual(joint,original)
        self.assertLessEqual(new.numerical_mass['added_mass_kg'],old.numerical_mass['added_mass_kg']+1e-8)
        self.assertLessEqual(new.connection_budget['final_step_eigenvalue'],3.2+1e-6)


if __name__=='__main__':unittest.main()
