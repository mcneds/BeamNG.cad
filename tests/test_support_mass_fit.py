import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from support_mass_fit import redistribute


class RedistributionTests(unittest.TestCase):
    def fixture(self):
        points=[[0.,0.,0.]]
        for radius in (1.,2.):
            for axis in range(3):
                for sign in (-1.,1.):
                    p=[0.,0.,0.];p[axis]=radius*sign;points.append(p)
        weights=[.5]+[1.]*12
        return SimpleNamespace(nodes={str(i):dict(position=p,options={'nodeWeight':w}) for i,(p,w) in enumerate(zip(points,weights))},
            mass_allocations={'body':dict(zip(map(str,range(13)),weights))},rigid_member_allocations={})

    def moments(self,g):
        p=np.array([v['position'] for v in g.nodes.values()]);w=np.array([v['options']['nodeWeight'] for v in g.nodes.values()])
        return sum(w),w@p,(p.T*w)@p

    def test_preserves_mass_com_full_inertia_and_positions(self):
        g=self.fixture();before=copy.deepcopy(g);report=redistribute(g,{'0':2.})
        self.assertGreater(report['moved_mass_kg'],1.)
        self.assertAlmostEqual(g.nodes['0']['options']['nodeWeight'],2.,places=6)
        for a,b in zip(self.moments(before),self.moments(g)):np.testing.assert_allclose(a,b,atol=1e-7)
        self.assertEqual([v['position'] for v in g.nodes.values()],[v['position'] for v in before.nodes.values()])
        self.assertTrue(all(v['options']['nodeWeight']>=.25-1e-8 for v in g.nodes.values()))

    def test_split_owner_is_frozen(self):
        g=self.fixture();g.rigid_member_allocations={'slider':{'owner':'body'}};before=copy.deepcopy(g.mass_allocations)
        result=redistribute(g,{'0':2.})
        self.assertEqual(g.mass_allocations,before)
        self.assertAlmostEqual(result['remaining_support_shortfall_kg'],1.5)

    def test_missing_ownership_fails_without_mutation(self):
        g=self.fixture();g.mass_allocations['body']['0']=.4;before=copy.deepcopy(g.mass_allocations)
        with self.assertRaisesRegex(ValueError,'ownership'):redistribute(g,{'0':2.})
        self.assertEqual(g.mass_allocations,before)

    def test_shared_node_ownership_not_double_counted(self):
        g=self.fixture();g.mass_allocations['other']={n:w*.4 for n,w in g.mass_allocations['body'].items()}
        g.mass_allocations['body']={n:w*.6 for n,w in g.mass_allocations['body'].items()}
        original=copy.deepcopy(g.mass_allocations);redistribute(g,{'0':2.})
        for o in original:
            p=np.array([g.nodes[n]['position'] for n in original[o]])
            old=np.array(list(original[o].values()));new=np.array(list(g.mass_allocations[o].values()))
            np.testing.assert_allclose([sum(old),*(old@p)],[sum(new),*(new@p)],atol=1e-7)
            np.testing.assert_allclose((p.T*old)@p,(p.T*new)@p,atol=1e-7)
        self.assertAlmostEqual(g.nodes['0']['options']['nodeWeight'],2.,places=6)


if __name__=='__main__':unittest.main()
