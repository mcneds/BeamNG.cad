import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_arms import additions,apply,staged


class AngularArmTests(unittest.TestCase):
    def fixture(self):
        p={'nodes':[['id','posX','posY','posZ']],'beams':[['id1:','id2:']]}
        m=dict(wheels={},component_roles={},rigid_refits={},mass_allocations={},explicit_beams=12)
        for corner in ('FL','FR'):
            hp={};m['wheels'][corner]={'hardpoint_nodes':hp}
            for arm in ('upper','lower'):
                owner=corner+'_'+arm;ids=[owner+'_'+k for k in ('front','ball','rear')]
                hp.update({arm+'_'+k:n for k,n in zip(('inner_front','ball','inner_rear'),ids)})
                m['component_roles'][owner]=corner.lower()+'_'+arm+'_wishbone';m['rigid_refits'][owner]={};m['mass_allocations'][owner]={n:2 for n in ids}
                for n,pos in zip(ids,[[0,0,0],[0,1,0],[1,0,0]]):p['nodes'].append([n,*pos,{'nodeWeight':2}])
                for a,b in ((0,1),(1,2),(0,2)):p['beams'].append([ids[a],ids[b],{'beamSpring':1000,'beamDamp':0}])
        return p,m

    def test_exactly_one_internal_child_per_arm(self):
        p,m=self.fixture();new=additions(p,m,.1)
        self.assertEqual(len(new),4);self.assertEqual(len(p['beams']),13)
        self.assertTrue(all(r[-1]['beamSpring']==100 for r in new))
        del m['mass_allocations']['FL_upper']['FL_upper_front']
        with self.assertRaisesRegex(ValueError,'escapes'):additions(p,m,.1)

    def test_failed_screen_does_not_mutate_physics_or_manifest(self):
        p,m=self.fixture();before=copy.deepcopy((p,m))
        with patch('angular_arms.discrete_spectrum',return_value={'passed':False,'spectral_radius':1.02}):
            with self.assertRaisesRegex(ValueError,'unstable'):apply(p,m,.1)
        self.assertEqual((p,m),before)

    def test_replace_upper_preserves_nodes_count_and_other_members(self):
        p,m=self.fixture();before=copy.deepcopy((p,m))
        shadow,new=staged(p,m,.3,'replace','upper')
        self.assertEqual((p,m),before)
        self.assertEqual(shadow['nodes'],p['nodes'])
        self.assertEqual(len(shadow['beams']),len(p['beams']))
        changed=[(a,b) for a,b in zip(p['beams'],shadow['beams']) if a!=b]
        self.assertEqual(len(changed),2)
        self.assertTrue(all('_upper_' in row[0] for row in new))
        for old,replacement in changed:
            self.assertEqual(old[:2],replacement[:2])
            self.assertEqual(replacement[-1]['beamType'],'|LBEAM')
            self.assertEqual(replacement[-1]['beamSpring'],300)
        with patch('angular_arms.discrete_spectrum',return_value={'passed':True,'spectral_radius':1.}):
            apply(p,m,.3,'replace','upper')
        self.assertEqual(m['explicit_beams'],12)
        self.assertEqual(p,shadow)


if __name__=='__main__':unittest.main()
