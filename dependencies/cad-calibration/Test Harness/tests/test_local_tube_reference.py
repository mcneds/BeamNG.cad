import json
from pathlib import Path
import unittest

import numpy as np
from scipy.spatial.transform import Rotation
from frame_harness.cad import Body,extract_member,volume_properties
from frame_harness.reference import build_frame,closest_segments
from frame_harness.calibration import fit_masses


class LocalTubeReferenceTests(unittest.TestCase):
    def test_segment_distances_match_independent_bounded_solver(self):
        from scipy.optimize import lsq_linear
        rng=np.random.default_rng(237)
        cases=[rng.normal(size=(4,3)) for _ in range(100)]
        cases.extend([np.array([[0.,0,0],[1,0,0],[.2,1,0],[.8,1,0]]),
                      np.array([[0.,0,0],[0,0,0],[1,1,0],[1,-1,0]])])
        for a,b,c,d in cases:
            fractions,x,y=closest_segments(a,b,c,d)
            expected=lsq_linear(np.column_stack((b-a,c-d)),c-a,bounds=(0,1),tol=1e-12)
            self.assertAlmostEqual(np.linalg.norm(x-y),np.linalg.norm(expected.fun),places=7)
            self.assertTrue(np.all((fractions>=0)&(fractions<=1)))

    def test_exact_moment_fit_does_not_starve_frame_nodes(self):
        data=json.loads((Path(__file__).parent/'fixtures/current-frame-mass-moments.json').read_text())
        points=np.array(data['positions']);center=np.array(data['center']);inertia=np.array(data['inertia'])
        masses,report=fit_masses(points,data['mass_kg'],center,inertia)
        self.assertTrue(report['accepted'])
        self.assertAlmostEqual(masses.sum(),data['mass_kg'],places=9)
        self.assertLess(report['center_error_m'],1e-8)
        self.assertLess(report['inertia_relative_error'],1e-8)
        self.assertGreater(masses.min(),.3)
        # The physical moments and stable allocation must not depend on node order.
        reordered,again=fit_masses(points[::-1],data['mass_kg'],center,inertia)
        self.assertAlmostEqual(reordered.min(),masses.min(),places=8)
        self.assertLess(again['inertia_relative_error'],1e-8)

    def body(self,name):
        data=json.loads((Path(__file__).parent/'fixtures'/('tube-'+name+'.json')).read_text())
        return Body(data['name'],np.array(data['vertices']),np.array(data['faces']))

    def test_coped_bends_and_u_tubes_cover_full_material(self):
        for name in ('combine1','combine14','combine15','combine16'):
            with self.subTest(body=name):
                body=self.body(name);reference=extract_member(body)
                self.assertLess(reference['section_volume_discrepancy'],.01)
                segments=reference['segments']
                volume=sum(np.linalg.norm(np.array(s['b'])-s['a'])*s['area_m2'] for s in segments)
                self.assertAlmostEqual(volume/volume_properties(body)['volume_m3'],1,delta=.01)
                path=np.array(reference['path'])
                self.assertGreater(np.linalg.norm(np.diff(path,axis=0),axis=1).sum(),np.linalg.norm(path[-1]-path[0])*1.1)
                self.assertTrue(all(s['area_m2']>0 and s['J_m4']>0 for s in segments))
                if name=='combine1':
                    areas=[s['area_m2'] for s in segments]
                    self.assertGreater(max(areas)/min(areas),1.1)

    def test_rotated_scaled_u_tube_uses_current_geometry(self):
        body=self.body('combine14');original=extract_member(body)
        rotation=Rotation.from_rotvec([.4,-.7,.2]).as_matrix()
        for scale in (.5,1.7):
            changed=Body('different frame',body.vertices@rotation.T*scale+[1,2,-3],body.faces)
            actual=extract_member(changed)
            self.assertAlmostEqual(actual['area_m2']/original['area_m2'],scale**2,delta=.01*scale**2)
            self.assertAlmostEqual(actual['J_m4']/original['J_m4'],scale**4,delta=.02*scale**4)
            self.assertLess(actual['section_volume_discrepancy'],.01)

    def test_reference_keeps_local_sections_and_continuity_without_self_welding(self):
        section=dict(a=[0,0,0],b=[1,1,0],area_m2=.01,Iy_m4=1e-5,Iz_m4=1e-5,J_m4=2e-5,radius_m=.1,
                     segments=[dict(a=[0,0,0],b=[1,0,0],area_m2=.01),dict(a=[1,0,0],b=[1,.05,0],area_m2=.02),
                               dict(a=[1,.05,0],b=[0,.05,0],area_m2=.03)])
        frame=build_frame({'combined':section})
        self.assertEqual(len(frame['positions']),4)
        self.assertEqual(len(frame['elements']),3)
        self.assertEqual([e['section']['area_m2'] for e in frame['elements']],[.01,.02,.03])
        values=np.linalg.eigvalsh(frame['matrix'])
        self.assertEqual(np.count_nonzero(values>values[-1]*1e-10),len(values)-6)


if __name__=='__main__':unittest.main()
