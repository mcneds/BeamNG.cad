import sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from angular_beams import tangent,force,validate_references


class AngularBeamTests(unittest.TestCase):
    def test_force_derivative_and_rigid_motion_invariance(self):
        p=np.array([[-.1,0.,0.],[0.,.4,0.],[.1,0.,0.]]);k=tangent(p,10000);h=1e-7;numeric=np.zeros((9,9))
        for i in range(9):
            plus=p.copy();minus=p.copy();plus.flat[i]+=h;minus.flat[i]-=h
            numeric[:,i]=-(force(plus,p,10000)-force(minus,p,10000)).ravel()/(2*h)
        np.testing.assert_allclose(k,numeric,atol=1e-5,rtol=1e-6)
        for axis in np.eye(3):
            np.testing.assert_allclose(k@np.tile(axis,3),0,atol=1e-10)
            np.testing.assert_allclose(k@np.cross(axis,p).ravel(),0,atol=1e-10)
        np.testing.assert_allclose(force(p*1.001,p,10000),0,atol=1e-10)
        self.assertGreater(np.linalg.norm(k-k.T),1.)  # SPD screening is invalid.

    def test_unique_normal_parents_and_optional_normal_child(self):
        part={'beams':[['id1:','id2:'],['a','c',{}],['b','c',{}],['a','b',{}],['a','b',{'beamType':'|LBEAM','id3:':'c'}]]}
        self.assertEqual(validate_references(part),[('a','b','c')])
        part['beams'].append(['a','c',{'beamType':'|LBEAM','id3:':'b'}])
        with self.assertRaisesRegex(ValueError,'unique normal'):validate_references(part)

    def test_unsupported_parameters_and_degeneracy_rejected(self):
        part={'beams':[['id1:','id2:'],['a','c',{}],['b','c',{}],['a','b',{'beamType':'|LBEAM','id3:':'c','beamDamp':2}]]}
        with self.assertRaisesRegex(ValueError,'undamped'):validate_references(part)
        with self.assertRaisesRegex(ValueError,'Collinear'):tangent([[0,0,0],[1,0,0],[2,0,0]],1.)


if __name__=='__main__':unittest.main()
