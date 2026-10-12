import importlib.util,unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
spec=importlib.util.spec_from_file_location('corner_modes',Path(__file__).resolve().parents[1]/'tools/analyze-corner-compliance-modes.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class WheelCondensationTests(unittest.TestCase):
    def test_strain_energy_excludes_rigid_motion_and_partitions_deformation(self):
        part={'beams':[['id1:','id2:'],{'beamSpring':100.},['a','b'],['b','c',{'beamSpring':200.}]]}
        nodes={n:{'position':p} for n,p in zip(('a','b','c'),([0.,0,0],[1.,0,0],[1.,1.,0]))}
        value,terms=module.strain_energy(part,nodes,{'a':np.array([2.,3,4]),'b':np.array([2.,3,4]),'c':np.array([2.,3,4])})
        self.assertEqual(value,0);self.assertEqual(terms,[])
        value,terms=module.strain_energy(part,nodes,{'b':np.array([.1,0,0]),'c':np.array([.1,.2,0])})
        self.assertAlmostEqual(value,9.);self.assertAlmostEqual(sum(r['fraction'] for r in terms),1.)

    def test_translation_transverse_rotation_and_no_axial_spin(self):
        axle=np.array([[-.1,0,0],[.1,0,0]])
        points=np.array([[0,.3,0],[0,-.3,0],[0,0,.3],[0,0,-.3]])
        m=module.wheel_mass_matrix(axle,points,np.ones(4))
        v=np.tile([1.,2.,3.],2);self.assertAlmostEqual(v@m@v,4*14)
        omega=np.array([0.,0.,1.]);rates=np.cross(omega,axle).ravel()
        self.assertAlmostEqual(rates@m@rates,.18)
        # Axial separation does not deform the condensed rigid wheel.
        rates=np.array([-1.,0,0,1.,0,0]);self.assertAlmostEqual(rates@m@rates,0.)
        np.testing.assert_allclose(m,m.T,atol=1e-12)
        self.assertGreater(np.linalg.eigvalsh(m).min(),-1e-10)

    def test_world_transform_and_invalid_axle(self):
        axle=np.array([[-.1,0,0],[.1,0,0]]);points=np.array([[0,.2,0],[0,-.2,0]])
        weights=np.array([2.,3.]);rates=np.array([[.4,.7,-.2],[.2,.1,.3]])
        base=module.wheel_mass_matrix(axle,points,weights)
        r=Rotation.from_rotvec([.3,-.2,.8]).as_matrix();t=np.array([3.,-2.,5.])
        changed=module.wheel_mass_matrix(axle@r.T+t,points@r.T+t,weights);v=(rates@r.T).ravel()
        self.assertAlmostEqual(v@changed@v,rates.ravel()@base@rates.ravel())
        with self.assertRaisesRegex(ValueError,'Degenerate'):module.wheel_mass_matrix(np.zeros((2,3)),points,weights)


if __name__=='__main__':unittest.main()
