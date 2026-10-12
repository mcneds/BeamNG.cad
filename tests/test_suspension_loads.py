import sys
import unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from suspension_loads import corner_masses,effective_moving_mass


class SuspensionLoadTests(unittest.TestCase):
    def test_corner_reactions_balance_offset_mass_and_reflect_with_geometry(self):
        hubs=np.array([[.75,0,0],[-.75,0,0],[.75,1.9,0],[-.75,1.9,0]])
        center=np.array([.07,1.05,.4]);mass=280.
        loads=corner_masses(hubs,mass,center)
        self.assertTrue(np.all(loads>0));self.assertAlmostEqual(sum(loads),mass)
        np.testing.assert_allclose(loads@hubs[:,:2],mass*center[:2],atol=1e-10)
        mirror=np.array([-1,1,1]);other=corner_masses(hubs*mirror,mass,center*mirror)
        np.testing.assert_allclose(loads,other,atol=1e-10)
        self.assertGreater(loads[0],loads[1]);self.assertGreater(loads[2],loads[0])
        np.testing.assert_allclose(corner_masses(hubs,mass,[0,.95,.4]),np.full(4,70.))
        with self.assertRaises(ValueError):corner_masses(hubs,mass,[3,.95,.4])

    def test_hinged_arm_gravity_uses_com_motion_not_its_entire_mass(self):
        # 0.6 m trailing arm, 8 kg uniformly distributed. Raising its end by h
        # raises its COM by h/2, so gravity contributes 4 kg at the wheel.
        length=.6;step=1e-5;angle=np.arcsin(step/length)
        transforms=[]
        for sign in (-1,1):
            matrix=np.eye(4);matrix[:3,:3]=Rotation.from_rotvec([sign*angle,0,0]).as_matrix();transforms.append(matrix)
        derivative=(transforms[1]-transforms[0])/(2*step)
        allocations={'arm':{'shared_pivot':4.,'tip':4.},'damper':{'top':1.,'bottom':1.}}
        positions={'shared_pivot':[0,0,0],'tip':[0,length,0]}
        result=effective_moving_mass(allocations,positions,{'arm':derivative},{'damper':{'top':0.,'bottom':.75}})
        self.assertAlmostEqual(result,4.75,places=8)


if __name__=='__main__':unittest.main()
