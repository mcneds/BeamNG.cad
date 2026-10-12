import sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from motion_objective import residual_columns
from coupled_rigidity import compliance_objective


class MotionObjectiveTests(unittest.TestCase):
    def test_angle_residual_keeps_global_and_intended_travel_free(self):
        xyz=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],[.8,0,.4],[1.,0.,.4]])
        slopes=np.array([[12.,25.]])
        g=residual_columns(xyz,[0,1,2,3],[1,2,3,4],[[4,5]],[[.9,0,.4]],slopes)
        for direction in np.eye(3):
            np.testing.assert_allclose(np.tile(direction,(6,1)).ravel()@g,0,atol=2e-8)
            np.testing.assert_allclose(np.cross(direction,xyz).ravel()@g,0,atol=2e-8)
        travel=np.zeros_like(xyz);travel[4:,2]=1
        differential=np.array([0.,np.radians(25)*.2,np.radians(12)*.2])
        travel[4]-=differential/2;travel[5]+=differential/2
        np.testing.assert_allclose(travel.ravel()@g,0,atol=2e-8)
        # A lateral deflection of one axle endpoint must still count as toe.
        self.assertAlmostEqual(g[5*3+1,1],5.,places=7)

    def test_compliance_gradient_matches_finite_difference(self):
        rng=np.random.default_rng(42);b=rng.normal(size=(5,12));outputs=rng.normal(size=(5,2))
        outputs/=np.linalg.norm(outputs);x=np.linspace(.5,1.5,12)
        _,analytic=compliance_objective(x,b,outputs);finite=[]
        for i in range(len(x)):
            delta=np.zeros_like(x);delta[i]=1e-6
            finite.append((compliance_objective(x+delta,b,outputs)[0]-compliance_objective(x-delta,b,outputs)[0])/2e-6)
        np.testing.assert_allclose(analytic,finite,rtol=2e-5,atol=1e-6)


if __name__=='__main__':unittest.main()
