import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import components
from vehicle_templates import wheel_options,wheel_support_mass


class WheelSupportMassTests(unittest.TestCase):
    def test_rim_tuning_preserves_wheel_mass_geometry_and_tire_properties(self):
        baseline=wheel_options(17.4,True,{},280.)
        candidate=wheel_options(17.4,True,{'rim_stiffness_scale':.95},280.)
        changed={key for key in baseline if baseline[key]!=candidate[key]}
        self.assertEqual(changed,{'hubTreadBeamSpring','hubPeripheryBeamSpring','hubSideBeamSpring','hubReinfBeamSpring'})
        for scale in (0,-1,1.01,float('nan')):
            with self.assertRaises(ValueError):wheel_options(17.4,True,{'rim_stiffness_scale':scale},280.)

    def test_actual_ring_quadrature_preserves_mass_center_and_inertia(self):
        def moments(options,added):
            positions=[];masses=[]
            for radius,width,mass in ((options['hubRadius'],options['hubWidth'],options['hubNodeWeight']),
                                      (options['radius'],options['tireWidth'],options['nodeWeight'])):
                for side in (-1,1):
                    for theta in np.arange(options['numRays'])*2*np.pi/options['numRays']:
                        positions.append([side*width/2,radius*np.cos(theta),radius*np.sin(theta)]);masses.append(mass)
            positions.extend([[-.075,0,0],[.075,0,0]]);masses.extend([added,added])
            xyz=np.array(positions);mass=np.array(masses)
            inertia=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,xyz))
            return mass.sum(),mass@xyz/mass.sum(),inertia
        for parameters in ({},{'rim_width_m':.168}):
            with self.subTest(parameters=parameters):
                original=wheel_options(17.4,True,parameters,280.)
                changed,added,report=wheel_support_mass(original,[.8,.85],.075)
                self.assertEqual(min(.8+added,.85+added),2.)
                first=moments(original,0);second=moments(changed,added)
                for a,b in zip(first,second):np.testing.assert_allclose(a,b,atol=1e-12)
                self.assertEqual(changed['radius'],original['radius']);self.assertEqual(changed['tireWidth'],original['tireWidth'])
                self.assertAlmostEqual(report['generated_mass_kg']+2*added,17.4)
                if parameters:self.assertGreater(changed['hubWidth'],changed['tireWidth'])

    def test_light_wheel_cannot_invent_ballast_and_heavy_supports_are_unchanged(self):
        with self.assertRaisesRegex(ValueError,'cannot support'):
            wheel_support_mass(wheel_options(2.,True,{},100.),[.2,.2],.075)
        options=wheel_options(17.4,True,{},280.)
        changed,added,_=wheel_support_mass(options,[2.5,2.7],.075)
        self.assertEqual(added,0)
        for name in ('nodeWeight','hubNodeWeight','hubWidth'):self.assertAlmostEqual(changed[name],options[name])


if __name__=='__main__':unittest.main()
