import importlib.util
from pathlib import Path
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

spec=importlib.util.spec_from_file_location('attribution',Path(__file__).resolve().parents[1]/'tools/decompose-suspension-error.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class AttributionTests(unittest.TestCase):
    def fixture(self):
        return {k:np.array(v,float) for k,v in dict(lower_inner_front=[0,-.15,0],lower_inner_rear=[0,.15,0],
            upper_inner_front=[0,-.1,.3],upper_inner_rear=[0,.1,.3],lower_ball=[.4,0,0],upper_ball=[.4,0,.3],
            tie_outer=[.4,-.1,.2],tie_inner=[0,-.1,.2],hub=[.45,0,.12],hub_axis=[.55,0,.12]).items()}

    def test_unchanged_geometry_has_zero_attributed_error(self):
        p=self.fixture();report=module.reconstruct(p,p,p['hub'][2],0.)
        self.assertLess(max(abs(v) for v in report['contributions_deg'].values()),1e-7)
        split=module.reconstruct(p,p,p['hub'][2],0.,split_arms=True)
        self.assertEqual(set(split['contributions_deg']),{'mounts','lower_arm','upper_arm','tie','upright'})
        self.assertLess(max(abs(v) for v in split['contributions_deg'].values()),1e-7)

    def test_known_rigid_steer_is_attributed_to_tie_length_on_both_sides(self):
        for sign in (-1,1):
            p={k:v*np.array([sign,1,1]) for k,v in self.fixture().items()};actual={k:v.copy() for k,v in p.items()}
            rotation=Rotation.from_rotvec([0,0,np.radians(sign*5)])
            for key in ('lower_ball','upper_ball','tie_outer','hub','hub_axis'):
                actual[key]=p['lower_ball']+rotation.apply(p[key]-p['lower_ball'])
            result=module.reconstruct(p,actual,actual['hub'][2],0.)
            self.assertAlmostEqual(result['contributions_deg']['tie'],sign*5,places=5)
            for key in ('mounts','arms','upright'):self.assertAlmostEqual(result['contributions_deg'][key],0.,places=5)
            self.assertAlmostEqual(sum(result['contributions_deg'].values()),result['reconstructed_error_deg'],places=6)

if __name__=='__main__':unittest.main()
