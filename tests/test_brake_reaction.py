import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from brake_reaction import choose,apply


class BrakeReactionTests(unittest.TestCase):
    def nodes(self):
        return {n:dict(position=p,options={'nodeWeight':2.}) for n,p in {'a':[0,0,0],'b':[1,0,0],'joint':[0,.99,0],'aux':[0,1,0]}.items()}

    def test_preference_requires_similar_inertia_and_existing_mass(self):
        nodes=self.nodes();before=copy.deepcopy(nodes)
        name,r=choose(nodes,list(nodes),['a','b'],{'joint'},.95)
        self.assertEqual(name,'joint');self.assertGreater(r['retained_inertia_fraction'],.95)
        self.assertEqual(choose(nodes,list(nodes),['a','b'],{'joint'},.999)[0],'aux')
        self.assertEqual(nodes,before)
        nodes['joint']['options']['nodeWeight']=.1
        self.assertEqual(choose(nodes,list(nodes),['a','b'],{'joint'},.01)[0],'aux')

    def test_unconditioned_new_force_site_is_rejected(self):
        nodes=self.nodes();nodes['aux']['options']['nodeWeight']=.1;nodes['joint']['options']['nodeWeight']=.1
        with self.assertRaisesRegex(ValueError,'support mass'):choose(nodes,list(nodes),['a','b'],{'joint'})

    def test_routing_changes_only_reaction_reference(self):
        nodes=self.nodes();p={'nodes':[['id','posX','posY','posZ']]+[[n,*v['position'],v['options']] for n,v in nodes.items()],
            'pressureWheels':[['name','nodeArm:'],['FL','aux']]}
        m={'wheels':{'FL':dict(brake_reaction_node='aux',hardpoint_nodes={'joint':'joint'},tire_contract={'axle_nodes':['a','b']},reaction_nodes={'nodeArm':'aux'})},
           'component_roles':{'owner':'fl_upright'},'mass_allocations':{'owner':{n:2 for n in nodes}}}
        before=copy.deepcopy(p);apply(p,m,['FL'])
        self.assertEqual(p['nodes'],before['nodes']);self.assertEqual(p['pressureWheels'][1],['FL','joint'])
        self.assertEqual(m['wheels']['FL']['reaction_nodes']['nodeArm'],'joint')


if __name__=='__main__':unittest.main()
