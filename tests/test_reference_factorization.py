import sys,unittest
from pathlib import Path
from unittest.mock import patch
import scipy.linalg
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness.reference import build_frame,solve_frame
from frame_harness.models import TestScenario

class ReferenceFactorizationTests(unittest.TestCase):
    def test_loads_reuse_operator_without_reusing_response(self):
        points={'a':[0,0,0],'b':[1,0,0],'c':[0,1,0],'d':[1,1,0]}
        sections={a+b:dict(a=points[a],b=points[b],radius_m=.02,area_m2=.0002,Iy_m4=4e-8,Iz_m4=4e-8,J_m4=8e-8)
                  for a,b in [('a','b'),('a','c'),('b','d'),('c','d')]}
        frame=build_frame(sections)
        def scenario(scale):return TestScenario('test',1,0,['a','b','c'],['d'],1,load_vectors={'d':[0,0,-scale]})
        with patch('scipy.linalg.cho_factor',wraps=scipy.linalg.cho_factor) as factor:
            first=solve_frame(frame,points,scenario(1),460e6)
            second=solve_frame(frame,points,scenario(2),460e6)
            self.assertEqual(factor.call_count,1)
            self.assertAlmostEqual(second['compliance_m_n']/first['compliance_m_n'],4)
            self.assertAlmostEqual(second['first_yield_force_n']/first['first_yield_force_n'],.5)
            frame.pop('_constraint_solutions')
            fresh=solve_frame(frame,points,scenario(2),460e6)
            self.assertEqual(second,fresh)
            self.assertEqual(factor.call_count,2)

if __name__=='__main__':unittest.main()
