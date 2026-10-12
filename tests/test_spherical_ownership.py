"""A shared node's creation owner must not change the declared joint parent."""
import itertools
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_templates import Structure


class SphericalOwnershipTests(unittest.TestCase):
    def graph(self):
        positions={'a':[1.,0,0],'b':[0,1.,0],'c':[0,0,1.],'shaft':[0,0,0]}
        beams=[]
        return SimpleNamespace(groups={'upright':['a','b','c'],'arm':['a']},
            owners={'a':'arm','b':'upright','c':'upright','shaft':'shaft_part'},
            nodes={n:dict(options=dict(nodeWeight=2.)) for n in positions},
            point=lambda n:np.array(positions[n]),beam=lambda *args,**kwargs:beams.append(args),
            part={},joints=[],spherical_constraint_rows=[],connection_torsions=[],beams=beams)

    def test_shared_ball_owner_does_not_override_upright_parent(self):
        for supports in itertools.permutations('abc'):
            g=self.graph()
            Structure.spherical(g,'cv',supports,'shaft',parent_owner='upright')
            self.assertEqual(g.joints[0]['parent'],'upright')
            self.assertEqual(g.joints[0]['child'],'shaft_part')
            self.assertEqual(g.joints[0]['nodes'],[*supports,'shaft'])

    def test_invalid_support_owner_rejected_before_mutation(self):
        for parent,supports in [('arm',['a','b','c']),('missing',['a','b','c']),
                                ('upright',['a','a','b'])]:
            g=self.graph()
            with self.assertRaisesRegex(ValueError,'declared parent'):
                Structure.spherical(g,'cv',supports,'shaft',parent_owner=parent)
            self.assertEqual(g.beams,[])
            self.assertEqual(g.joints,[])


if __name__=='__main__':unittest.main()
