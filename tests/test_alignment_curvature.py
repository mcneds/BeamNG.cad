import importlib.util,unittest
from pathlib import Path
import numpy as np
path=Path(__file__).resolve().parents[1]/'tools/audit-alignment-curvature.py'
spec=importlib.util.spec_from_file_location('curvature',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RollingGeometryTests(unittest.TestCase):
    def test_parallel_wheels_crab_without_yaw(self):
        centers=np.array([[.7,-1],[-.7,-1],[.7,1],[-.7,1]])
        for angle in (0,7,-7):
            (side,yaw),residual=module.rolling([angle]*4,centers)
            self.assertAlmostEqual(side,np.tan(np.radians(angle)))
            self.assertAlmostEqual(yaw,0)
            self.assertLess(residual,1e-14)

    def test_exact_ackermann_and_reflection(self):
        centers=np.array([[.7,-1],[-.7,-1],[.7,1],[-.7,1]])
        # Chosen rigid-body velocity gives each wheel's exact no-slip normal.
        side=.1;yaw=.1
        velocity=np.column_stack((side-yaw*centers[:,1],-1+yaw*centers[:,0]))
        toes=np.degrees(np.arctan2(velocity[:,0],-velocity[:,1]))
        solution,residual=module.rolling(toes,centers)
        np.testing.assert_allclose(solution,[side,yaw],atol=1e-14)
        reflected=centers*np.array([-1,1])
        mirror,error=module.rolling(-toes,reflected)
        np.testing.assert_allclose(mirror,-solution,atol=1e-14)
        self.assertLess(max(residual,error),1e-14)

if __name__=='__main__':unittest.main()
