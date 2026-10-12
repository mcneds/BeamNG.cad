"""Steering stiffness changes only the existing steering restraint."""
import copy
import unittest
from unittest.mock import patch
from test_vehicle_template_graph import fixture
from vehicle_templates import generate


class SteeringStiffnessTests(unittest.TestCase):
    def test_requested_stiffness_keeps_graph_and_spring_laws(self):
        project,frame,spec,cad=fixture('primary')
        generated=[]
        for stiffness in (2500000,10000000):
            candidate=copy.deepcopy(spec)
            candidate['parameters']['steering_link_spring_n_m']=stiffness
            with patch('components.read_geometry',side_effect=cad):
                graph,part,*_=generate(project,copy.deepcopy(frame),candidate)
            generated.append((graph,part))
            self.assertLessEqual(graph.connection_budget['final_step_eigenvalue'],3.2+1e-6)
        before,after=(g[1] for g in generated)
        self.assertEqual(before['nodes'],after['nodes'])
        for section in ('beams','hydros'):
            self.assertEqual([r[:2] for r in before[section] if isinstance(r,list)],
                             [r[:2] for r in after[section] if isinstance(r,list)])
        springs=lambda p:[r for r in p['beams'][1:] if isinstance(r,list) and r[-1].get('beamType') in ('|BOUNDED','|SUPPORT')]
        self.assertEqual(springs(before),springs(after))
        for a,b in zip(before['hydros'][1:],after['hydros'][1:]):
            self.assertGreater(b[-1]['beamSpring'],a[-1]['beamSpring'])
            self.assertLessEqual(b[-1]['beamSpring'],10000000)
            for key in ('factor','beamPrecompression','inputSource','beamDeform','beamStrength'):
                self.assertEqual(a[-1][key],b[-1][key])


if __name__=='__main__':unittest.main()
