import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_conditioning import refit_joint_constraints


class JointRefitTests(unittest.TestCase):
    def test_final_mass_scales_same_constraint_without_adding_springs(self):
        xyz=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]]
        nodes={n:dict(position=p,options=dict(nodeWeight=2.)) for n,p in zip('abcd',xyz)}
        g=SimpleNamespace(nodes=nodes,spherical_constraint_rows=[['a','b','c','d',dict(spring=1,damp=1,strength=123)]],
            steering_constraints=[['a','d',dict(beamSpring=1,beamDamp=50,factor=.01)]],steering_link_frequency_hz=400)
        g.point=lambda n:g.nodes[n]['position']
        refit_joint_constraints(g);before=copy.deepcopy(g)
        for node in g.nodes.values():node['options']['nodeWeight']*=3
        refit_joint_constraints(g)
        self.assertEqual(len(g.spherical_constraint_rows),1)
        self.assertEqual(set(g.spherical_constraint_rows[0][:4]),set('abcd'))
        for key in ('spring','damp'):
            self.assertAlmostEqual(g.spherical_constraint_rows[0][-1][key],3*before.spherical_constraint_rows[0][-1][key])
        self.assertEqual(g.spherical_constraint_rows[0][-1]['strength'],123)
        self.assertEqual(g.steering_constraints[0][-1]['factor'],.01)
        self.assertEqual(g.steering_constraints[0][-1]['beamDamp'],50)
        self.assertAlmostEqual(g.steering_constraints[0][-1]['beamSpring'],3*before.steering_constraints[0][-1]['beamSpring'])
        self.assertEqual([n['position'] for n in g.nodes.values()],xyz)

if __name__=='__main__':unittest.main()
