import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from fixed_strain_damping import apply


class FixedDampingTests(unittest.TestCase):
    def fixture(self):
        p=dict(nodes=[['id','posX','posY','posZ']]+[[n,*v,dict(nodeWeight=2.)] for n,v in zip('abcd',[(0,0,0),(1,0,0),(0,1,0),(0,0,1)])],
            beams=[['id1:','id2:'],['a','c',dict(beamSpring=10000.,beamDamp=10000.,beamDeform=1e30,beamStrength=1e30)],
                ['b','c',dict(beamSpring=10000.,beamDamp=1.,beamDeform=10000.,beamStrength=20000.)],
                ['c','d',dict(beamType='|BOUNDED',beamSpring=1000.,beamDamp=10.,beamDeform=1e30,beamStrength=1e30)]],
            hydros=[['id1:','id2:'],['a','d',dict(beamSpring=100.,beamDamp=2.)]])
        return p,dict(fixed_attachment_contract={'part':dict(nodes=['c'],parents=list('abd'))})

    def test_only_unbreakable_fixed_damping_is_reduced(self):
        p,m=self.fixture();before=copy.deepcopy(p);r=apply(p,m)
        self.assertEqual(r['eligible_constraints'],1)
        self.assertLess(p['beams'][1][-1]['beamDamp'],before['beams'][1][-1]['beamDamp'])
        p['beams'][1][-1]['beamDamp']=before['beams'][1][-1]['beamDamp']
        self.assertEqual(p,before)
        self.assertLessEqual(r['screen']['final_step_eigenvalue'],3.1)

    def test_infeasible_fixed_stiffness_leaves_input_unchanged(self):
        p,m=self.fixture();p['beams'][1][-1]['beamSpring']=1e9;before=copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError,'exceed'):apply(p,m)
        self.assertEqual(p,before)

    def test_missing_contract_and_invalid_limit_fail_closed(self):
        p,m=self.fixture()
        with self.assertRaisesRegex(ValueError,'No eligible'):apply(p,{})
        with self.assertRaisesRegex(ValueError,'limit'):apply(p,m,3.2)


if __name__=='__main__':unittest.main()
