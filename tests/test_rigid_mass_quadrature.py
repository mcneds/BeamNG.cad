import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_templates import rigid_mass_points

class RigidMassQuadratureTests(unittest.TestCase):
    def test_asymmetric_slender_rotated_body_preserves_all_moments(self):
        rotation,_=np.linalg.qr(np.array([[1.,2,3],[4,2,1],[2,3,1]]))
        for thickness in (.05,.003):
            covariance=rotation@np.diag([.15**2,.08**2,thickness**2])@rotation.T
            mass=4.73;center=np.array([.52,-1.7,.34]);inertia=mass*(np.trace(covariance)*np.eye(3)-covariance)
            points=center+np.array([[.2,.1,.01],[-.21,.08,0],[0,-.09,.008]])@rotation.T
            xyz,weights=rigid_mass_points((mass,center,inertia),points)
            self.assertEqual(len(xyz),len(points)+6)
            np.testing.assert_array_equal(xyz[:len(points)],points)
            self.assertGreater(min(weights),0)
            self.assertAlmostEqual(sum(weights),mass)
            np.testing.assert_allclose(weights@xyz/mass,center,atol=1e-13)
            offset=xyz-center
            actual=sum(w*(np.dot(v,v)*np.eye(3)-np.outer(v,v)) for w,v in zip(weights,offset))
            np.testing.assert_allclose(actual,inertia,atol=1e-12)

    def test_mirrored_and_permuted_hardpoints_preserve_mass_and_point_layout(self):
        covariance=np.array([[.02,.003,.002],[.003,.005,.001],[.002,.001,.01]])
        center=np.array([.7,.2,.3]);mass=5.
        inertia=mass*(np.trace(covariance)*np.eye(3)-covariance)
        points=center+np.array([[.2,.1,.01],[-.21,.08,0],[0,-.09,.008],[.1,0,.1]])
        xyz,weights=rigid_mass_points((mass,center,inertia),points)
        mirror=np.diag([-1.,1,1]);order=[2,0,3,1]
        other,other_weights=rigid_mass_points((mass,center@mirror,mirror@inertia@mirror),points[order]@mirror)
        np.testing.assert_allclose(other_weights[:4],weights[order],rtol=1e-7)
        reflected=xyz[4:]@mirror
        for point in other[4:]:self.assertLess(np.linalg.norm(reflected-point,axis=1).min(),1e-8)
        np.testing.assert_allclose(other_weights[4:],weights[4:],rtol=1e-7)

    def test_impossible_inertia_rejected(self):
        with self.assertRaisesRegex(ValueError,'positive volume'):
            rigid_mass_points((1.,np.zeros(3),np.diag([1.,1.,3.])),[[0.,0.,0.]])

if __name__=='__main__':unittest.main()
