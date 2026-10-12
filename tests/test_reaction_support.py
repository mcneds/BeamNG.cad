import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from reaction_support import allocate


class ReactionSupportTests(unittest.TestCase):
    def fixture(self):
        mass=14.13;center=np.array([0.,1.9,.34])
        covariance=np.diag(np.array([.15,.12,.1])**2/12)
        inertia=mass*(np.trace(covariance)*np.eye(3)-covariance)
        points=center+np.vstack((np.eye(3),-np.eye(3)))*np.sqrt(3*np.diag(covariance))
        return (mass,center,inertia),points,np.full(6,mass/6)

    def test_preserves_all_moments_and_old_positions_with_loaded_nodes(self):
        moments,points,current=self.fixture()
        kept,added,weights,report=allocate(moments,points,current,[False]*6)
        xyz=np.vstack((points,added));mass=np.r_[kept,weights];center=moments[1]
        self.assertGreaterEqual(min(weights[:3]),2)
        self.assertTrue(np.all(mass>0));self.assertAlmostEqual(sum(mass),moments[0])
        np.testing.assert_allclose(mass@xyz/sum(mass),center,atol=1e-12)
        delta=xyz-center
        tensor=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,delta))
        np.testing.assert_allclose(tensor,moments[2],atol=1e-12)
        self.assertTrue(report['experimental'])

    def test_retained_mount_mass_and_rotated_asymmetric_moments(self):
        moments,points,current=self.fixture();rotation,_=np.linalg.qr(np.array([[1.,2,3],[4,2,1],[2,3,1]]))
        mass,center,tensor=moments
        transformed=(mass,center@rotation,rotation.T@tensor@rotation)
        kept,_,weights,report=allocate(transformed,points@rotation,current,[True,False,False,False,False,False],axis=np.array([1,0,0])@rotation)
        self.assertEqual(kept[0],current[0]);self.assertGreaterEqual(min(weights[:3]),2)
        self.assertLess(report['inertia_error_relative'],1e-10)

    def test_rejects_impossible_floor_instead_of_adding_ballast(self):
        moments,points,current=self.fixture()
        with self.assertRaisesRegex(ValueError,'requested minimum'):
            allocate(moments,points,current,[False]*6,minimum=5)


if __name__=='__main__':unittest.main()
