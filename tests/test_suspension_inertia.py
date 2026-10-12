import sys,unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from suspension_inertia import rigid_kinetic_mass,nodal_kinetic_mass,rigid_kinetic_matrix,nodal_kinetic_matrix


class SuspensionInertiaTests(unittest.TestCase):
    def rod(self):
        # Uniform 2 kg, 0.6 m rod rotates about its end. q is tip travel.
        mass=2.;length=.6;center=np.array([0.,length/2,0.]);inertia=np.diag([mass*length**2/12,0,mass*length**2/12])
        derivative=np.zeros((4,4));derivative[1,2]=-1/length;derivative[2,1]=1/length
        return mass,center,inertia,np.eye(4),derivative

    def test_uniform_hinged_rod_and_exact_nodal_quadrature(self):
        args=self.rod();value=rigid_kinetic_mass(*args)
        self.assertAlmostEqual(value['kinetic_mass_kg'],2/3)
        nodes=np.array([[0.,.3-.3/np.sqrt(3),0.],[0.,.3+.3/np.sqrt(3),0.]])
        self.assertAlmostEqual(nodal_kinetic_mass(nodes,[1.,1.],args[-1]),value['kinetic_mass_kg'])
        self.assertAlmostEqual(nodal_kinetic_mass([[0.,.6,0.]],[2.],args[-1]),2.)

    def test_world_coordinates_do_not_change_energy(self):
        mass,center,inertia,t,d=self.rod();world=np.eye(4)
        world[:3,:3]=Rotation.from_rotvec([.4,-.2,.7]).as_matrix();world[:3,3]=[3.,-2.,1.]
        value=rigid_kinetic_mass(mass,(world@np.r_[center,1])[:3],world[:3,:3]@inertia@world[:3,:3].T,
            world@t@np.linalg.inv(world),world@d@np.linalg.inv(world))
        self.assertAlmostEqual(value['kinetic_mass_kg'],2/3)

    def test_translation_counts_mass_and_invalid_inertia_is_rejected(self):
        args=list(self.rod());args[-1]=np.zeros((4,4));args[-1][2,3]=1
        self.assertEqual(rigid_kinetic_mass(*args)['kinetic_mass_kg'],2.)
        args[2]=np.diag([1.,1.,3.])
        with self.assertRaisesRegex(ValueError,'Nonphysical'):rigid_kinetic_mass(*args)

    def test_coupled_translation_rotation_energy_and_coordinate_scaling(self):
        mass,center,inertia,t,rotation=self.rod();translation=np.zeros((4,4));translation[2,3]=1
        derivatives=[translation,rotation]
        matrix=rigid_kinetic_matrix(mass,center,inertia,t,derivatives)
        np.testing.assert_allclose(matrix,[[2,1],[1,2/3]],atol=1e-12)
        nodes=np.array([[0.,.3-.3/np.sqrt(3),0.],[0.,.3+.3/np.sqrt(3),0.]])
        np.testing.assert_allclose(nodal_kinetic_matrix(nodes,[1.,1.],derivatives),matrix,atol=1e-12)
        rates=np.array([.7,-.2]);combined=sum(q*d for q,d in zip(rates,derivatives))
        self.assertAlmostEqual(rates@matrix@rates,rigid_kinetic_mass(mass,center,inertia,t,combined)['kinetic_mass_kg'])
        scale=np.diag([1.,.03]);scaled=rigid_kinetic_matrix(mass,center,inertia,t,[translation,.03*rotation])
        np.testing.assert_allclose(scaled,scale@matrix@scale,atol=1e-12)
        with self.assertRaisesRegex(ValueError,'coordinate'):rigid_kinetic_matrix(mass,center,inertia,t,[])


if __name__=='__main__':unittest.main()
