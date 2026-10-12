import sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from ballast_optimization import minimize


class BallastOptimizationTests(unittest.TestCase):
    def test_independent_exact_lower_bound(self):
        result=minimize(np.diag([2.]*3+[1.]*3),[1.,1.],[.5,.5],[2.,2.],[1.,1.])
        np.testing.assert_allclose(result['masses'],[.625,.5],atol=1e-7)
        self.assertLess(result['optimality_gap'],1e-7)

    def test_coupled_reallocation_preserves_budget(self):
        a=np.kron([[1.,-1.],[-1.,1.]],np.eye(3))
        r=minimize(a,[1.,1.],[.4,.4],[2.,2.],[10.,1.],iterations=80)
        self.assertLess(r['objective'],11.)
        self.assertLess(r['masses'][0],1.)
        self.assertLessEqual(sum(r['masses']),2.+1e-7)
        self.assertLessEqual(r['final_step_eigenvalue'],3.2+1e-7)

    def test_rejects_unsafe_reference_or_bounds(self):
        with self.assertRaises(ValueError):minimize(np.eye(6)*4,[1.,1.],[.5,.5],[2.,2.],[1.,1.])
        with self.assertRaises(ValueError):minimize(np.eye(6),[1.,1.],[0.,.5],[2.,2.],[1.,1.])

    def test_explicit_screen_limit_keeps_default_stricter(self):
        operator=np.eye(6)*3.5
        with self.assertRaisesRegex(ValueError,'Reference'):
            minimize(operator,[1.,1.],[.5,.5],[2.,2.],[1.,1.])
        result=minimize(operator,[1.,1.],[.5,.5],[2.,2.],[1.,1.],limit=3.6)
        np.testing.assert_allclose(result['masses'],[3.5/3.6]*2,atol=1e-7)
        self.assertLessEqual(result['final_step_eigenvalue'],3.6+1e-7)


if __name__=='__main__':unittest.main()
