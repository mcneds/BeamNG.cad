import sys,unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from drive_axes import plane_consensus,resolve


class DriveAxisTests(unittest.TestCase):
    def test_parallel_cvt_planes_rotate_with_cad_and_ignore_small_fasteners(self):
        q=Rotation.from_rotvec([.5,.2,-.3]).as_matrix()
        tensors=[(2.,q@np.diag([.02,.011,.0105])@q.T),(1.,q@np.diag([.04,.025,.0155])@q.T),(.01,np.diag([.004,.006,.003]))]
        axis,report=plane_consensus(tensors)
        self.assertGreater(abs(axis@q[:,0]),.999999)
        self.assertGreater(report['volume_coverage'],.99)

    def test_ambiguous_or_minor_flat_bodies_are_not_a_crank_axis(self):
        with self.assertRaises(ValueError):plane_consensus([(1.,np.diag([.02,.011,.0105])),(1.,np.diag([.011,.02,.0105]))])
        with self.assertRaises(ValueError):plane_consensus([(10.,np.eye(3)),(.01,np.diag([.02,.011,.0105])),(.01,np.diag([.02,.011,.0105]))])

    def test_explicit_axis_needs_all_coordinates_and_has_priority(self):
        axis,report=resolve({}, {},dict(engine_axis_x=0,engine_axis_y=2,engine_axis_z=0))
        np.testing.assert_array_equal(axis,[0,1,0]);self.assertEqual(report['method'],'declared')
        with self.assertRaises(ValueError):resolve({}, {},dict(engine_axis_x=1))


if __name__=='__main__':unittest.main()
