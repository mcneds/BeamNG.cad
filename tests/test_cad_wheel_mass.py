import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from vehicle_templates import cad_wheel_support_mass,wheel_options,wheel_axis_points,cad_tire_budget


class CadWheelMassTests(unittest.TestCase):
    def test_small_ring_budget_preserves_mass_dimensions_and_pressure(self):
        source=wheel_options(5,False,{},180)
        source.update(hubNodeWeight=.009,nodeWeight=.125)
        result,report=cad_tire_budget(source)
        for key in ('hubNodeWeight','nodeWeight','hubWidth','tireWidth','radius','hubRadius','pressurePSI','brakeTorque'):
            self.assertEqual(source[key],result[key])
        self.assertEqual(source['wheelReinfBeamDamp'],140)
        self.assertLess(result['wheelReinfBeamDamp'],1)
        self.assertGreater(result['wheelSideBeamSpring'],0)
        self.assertLess(report['hub_scale'],1)

    def test_reconstruct_mass_and_tensor_with_loaded_axles(self):
        axis=np.array([1.,2.,3.]);axis/=np.linalg.norm(axis)
        spin=.348;lateral=.0302;mass=9.06
        inertia=(spin/2+lateral)*np.eye(3)+(spin/2-lateral)*np.outer(axis,axis)
        options=wheel_options(mass,True,dict(rim_radius_m=.127,tire_radius_m=.286,tire_width_m=.183),180)
        result,added,report=cad_wheel_support_mass(options,[.01,.06],.045,(mass,np.zeros(3),inertia),axis)
        count=2*result['numRays'];hub=count*result['hubNodeWeight'];tread=count*result['nodeWeight']
        self.assertAlmostEqual(hub+tread+2*added,mass)
        self.assertAlmostEqual(hub*result['hubRadius']**2+tread*result['radius']**2,spin)
        self.assertAlmostEqual(hub*(result['hubWidth']/2)**2+tread*(result['tireWidth']/2)**2+2*added*.045**2,lateral)
        self.assertGreaterEqual(.01+added,2)
        self.assertLess(report['inertia_axisymmetry_relative_error'],1e-12)

    def test_infeasible_mass_rejected(self):
        with self.assertRaisesRegex(ValueError,'cannot supply'):
            cad_wheel_support_mass(wheel_options(5,True,{},150),[.01,.01],.045,
                (5,np.zeros(3),np.diag([.3,.17,.17])),[1,0,0])

    def test_offset_datum_keeps_native_axis(self):
        points=dict(hub=np.array([.6,.1,0]),hub_axis=np.array([.62,.1,0]))
        a,b=wheel_axis_points(points,np.array([.686,.101,0]),.045)
        np.testing.assert_allclose((a+b)/2,[.686,.1,0])
        self.assertAlmostEqual(np.linalg.norm(b-a),.09)

if __name__=='__main__':unittest.main()
