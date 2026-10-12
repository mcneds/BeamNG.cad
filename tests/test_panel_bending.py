import sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from panel_bending import hinges,screen
from rigid_bracing import gradient


class PlateHingeTests(unittest.TestCase):
    def test_two_triangles_have_the_expected_plate_rigidity_and_no_rigid_restraint(self):
        xyz=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0]],float);faces=[[0,1,2],[1,3,2]]
        result=hinges(xyz,faces,np.ones(4),100.)
        self.assertEqual(len(result),1);ids,options=result[0]
        self.assertAlmostEqual(options['spring'],300.)
        g=gradient(xyz[ids]);np.testing.assert_allclose(g.sum(axis=0),0,atol=1e-7)
        np.testing.assert_allclose(np.cross(xyz[ids],g).sum(axis=0),0,atol=1e-7)
        double=hinges(xyz,faces,np.ones(4),800.)
        self.assertAlmostEqual(double[0][1]['spring']/options['spring'],8.)
    def test_high_plate_stiffness_is_explicitly_projected_before_native_loading(self):
        xyz=np.array([[0,0,0],[.1,0,0],[0,.1,0],[.1,.1,0]],float)
        masses=np.ones(4)*.01;result=hinges(xyz,[[0,1,2],[1,3,2]],masses,1e5)
        _,_,report=screen(xyz,masses,[[0,1],[1,2],[2,3]],np.ones(3)*1e5,np.ones(3),result)
        self.assertLess(report['retention'],1);self.assertLessEqual(report['final_step_eigenvalue'],2.5)


if __name__=='__main__':unittest.main()
