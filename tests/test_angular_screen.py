import sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_screen import matrices,discrete_spectrum,symmetric_step_operator
from scipy.sparse import csr_matrix
from frame_harness.build import node_table


class AngularScreenTests(unittest.TestCase):
    def test_known_scalar_stability(self):
        self.assertTrue(discrete_spectrum([[3e6]],[[200]],.0005)['passed'])
        self.assertFalse(discrete_spectrum([[17e6]],[[0]],.0005)['passed'])
        self.assertFalse(discrete_spectrum([[-1e4]],[[0]],.0005)['passed'])

    def test_symmetric_budget_rejects_nonreciprocal_force(self):
        k=csr_matrix([[10.,2.],[2.,20.]]);c=csr_matrix((2,2))
        np.testing.assert_allclose(symmetric_step_operator(k,c).toarray(),k.toarray()*.0005**2)
        with self.assertRaisesRegex(ValueError,'Nonsymmetric'):
            symmetric_step_operator(csr_matrix([[10.,1.],[2.,20.]]),c)

    def test_mass_normalized_force_matrix(self):
        p={'nodes':[['id','posX','posY','posZ'],['a',0,0,0,{'nodeWeight':2}],['b',1,0,0,{'nodeWeight':8}]],
           'beams':[['id1:','id2:'],['a','b',{'beamSpring':100,'beamDamp':10}]]}
        k,c=matrices(p,node_table(p));expected=np.array([[50,-25],[-25,12.5]])
        np.testing.assert_allclose(k.toarray()[np.ix_([0,3],[0,3])],expected)
        np.testing.assert_allclose(c.toarray(),k.toarray()*.1)
        self.assertTrue(discrete_spectrum(k,c)['passed'])


if __name__=='__main__':unittest.main()
