import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from monotone_rigidity import apply


class MonotoneRigidityTests(unittest.TestCase):
    def fixture(self):
        p=dict(nodes=[['id','posX','posY','posZ']]+[[n,*v,dict(nodeWeight=2.)] for n,v in zip('abcde',[(0,0,0),(1,0,0),(0,1,0),(0,0,1),(1,1,1)])],
            beams=[['id1:','id2:']]+[[a,b,dict(beamSpring=5e6,beamDamp=0.,beamStrength=1e30,beamDeform=1e30)] for a,b in [('a','b'),('b','c'),('a','c')]]+
                [['c','d',dict(beamType='|BOUNDED',beamSpring=1000.,beamDamp=1.)]],
            hydros=[['id1:','id2:'],['c','e',dict(inputSource='steering_input',beamSpring=1000.,beamDamp=1.,inRate=2.,outRate=2.,factor=.04)]],
            cadConstraintGroups={'coilover':{'beams':[['c','d']]}})
        m=dict(component_roles={'arm':'fl_lower_wishbone'},mass_allocations={'arm':dict.fromkeys('abc',1.)},rigid_refits={'arm':{}},
            frame_reference={'mode':'rigid_reference'},chassis_nodes=list('abd'),connection_budget={},
            wheels={c:{'hardpoint_nodes':{'tie_inner':'c','tie_outer':'e'}} for c in ('FL','FR')})
        return p,m

    def test_increment_cap_cannot_weaken_or_change_physics(self):
        p,m=self.fixture();before=copy.deepcopy(p);r=apply(p,m,3,3.2,'members')
        self.assertLessEqual(r['screen']['final_step_eigenvalue'],3.2)
        self.assertTrue(any(v['after']<3*v['before'] for v in r['constraints']))
        for v in r['constraints']:
            self.assertGreaterEqual(v['after'],v['before'])
            p[v['section']][v['index']][-1][v['key']]=v['before']
        self.assertEqual(p,before)

    def test_front_increment_keeps_steering_targets_and_damping(self):
        p,m=self.fixture();before=copy.deepcopy(p);r=apply(p,m,1.2)
        self.assertTrue(any(v['section']=='hydros' for v in r['constraints']))
        self.assertEqual({k:v for k,v in p['hydros'][1][-1].items() if k!='beamSpring'},
                         {k:v for k,v in before['hydros'][1][-1].items() if k!='beamSpring'})
        self.assertEqual(p['beams'][-1],before['beams'][-1])

    def test_physical_spring_overlap_is_rejected_before_mutation(self):
        p,m=self.fixture();p['cadConstraintGroups']['bad']={'beams':[['a','c']]};before=copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError,'physical spring'):apply(p,m,selection='members')
        self.assertEqual(p,before)

    def test_material_frame_and_repeat_revision_rejected(self):
        p,m=self.fixture();m['frame_reference']['mode']='calibrated'
        with self.assertRaisesRegex(ValueError,'numerical rigid frame'):apply(p,m)
        p,m=self.fixture();apply(p,m,selection='members')
        with self.assertRaisesRegex(ValueError,'without a monotone'):apply(p,m,selection='members')


if __name__=='__main__':unittest.main()
