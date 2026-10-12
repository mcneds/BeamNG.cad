import copy
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from wheel_visuals import render


class WheelVisualTests(unittest.TestCase):
    def fixture(self):
        # An oblique axle and translated geometry prevent a hidden world-X assumption.
        axis=np.array([1.,2.,3.]);axis/=np.linalg.norm(axis)
        u=np.cross(axis,[0.,0.,1.]);u/=np.linalg.norm(u);v=np.cross(axis,u)
        center=np.array([3.,-2.,1.])
        part=dict(nodes=[['id','posX','posY','posZ'],['a',*(center-.1*axis)],['b',*(center+.1*axis)]],
                  pressureWheels=[['name','hubGroup','group','node1:','node2:'],
                                  ['RL','rim_RL','tire_RL','a','b',dict(radius=.3,hubRadius=.13)]])
        def body(name,low,high):
            return dict(Id=name),np.array([[center+low*u,center+high*u,center+high*v]])
        return part,body

    def test_metal_follows_rim_and_rubber_follows_tire_without_physics_changes(self):
        part,body=self.fixture();before=copy.deepcopy(part)
        meshes=[body('hub',.01,.09),body('rim',.07,.15),body('tire',.14,.3)]
        rows,report=render(part,'RL',meshes,['h','r','t'])
        self.assertEqual([r[1] for r in rows],[['rim_RL'],['rim_RL'],['tire_RL']])
        self.assertEqual(part,before)
        self.assertAlmostEqual(report['bodies']['tire']['radial_range_m'][1],.3)

    def test_mixed_or_ambiguous_body_requires_explicit_role(self):
        part,body=self.fixture()
        for mesh in (body('mixed',.01,.3),body('unclear',.15,.2)):
            with self.assertRaisesRegex(ValueError,'Ambiguous'):render(part,'RL',[mesh],['x'])
            rows,_=render(part,'RL',[mesh],['x'],{mesh[0]['Id']:'rim'})
            self.assertEqual(rows[0][1],['rim_RL'])

    def test_stale_or_invalid_overrides_rejected(self):
        part,body=self.fixture()
        for override in ({'missing':'rim'},{'hub':'rigid'}):
            with self.assertRaises(ValueError):render(part,'RL',[body('hub',.01,.09)],['h'],override)


if __name__=='__main__':unittest.main()
