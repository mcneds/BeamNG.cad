import unittest
import numpy as np
from frame_harness.skin import partition_surface


class SurfacePartitionTests(unittest.TestCase):
    def test_long_triangle_is_clipped_at_exact_shared_boundary(self):
        source=np.array([[[-2.,0,0],[2,0,0],[0,2,0]]])
        regions=dict(partition_surface(source,np.array([[-1.,0,0],[1.,0,0]])))
        self.assertEqual(set(regions),{0,1})
        self.assertTrue(np.all(regions[0][:,:,0]<=1e-10))
        self.assertTrue(np.all(regions[1][:,:,0]>=-1e-10))
        area=lambda faces:np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1).sum()/2
        self.assertAlmostEqual(sum(area(faces) for faces in regions.values()),area(source))
        np.testing.assert_allclose(sorted(regions[0].reshape(-1,3).tolist()),sorted([[-2,0,0],[0,0,0],[0,2,0]]))

    def test_coplanar_boundary_has_single_owner_and_one_region_preserves_surface(self):
        source=np.array([[[0.,0,0],[0,1,0],[0,0,1]]])
        regions=list(partition_surface(source,np.array([[-1.,0,0],[1.,0,0]])))
        self.assertEqual(len(regions),1);self.assertEqual(regions[0][0],0)
        np.testing.assert_allclose(regions[0][1],source)
        regions=list(partition_surface(source,np.array([[0.,0,0]])))
        np.testing.assert_allclose(regions[0][1],source)
