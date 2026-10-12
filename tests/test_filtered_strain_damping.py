import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from filtered_strain_damping import apply


class StrainDampingTests(unittest.TestCase):
    def fixture(self):
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=2)] for n,p in zip('abcd',[(0,0,0),(1,0,0),(0,1,0),(0,0,1)])],
            beams=[['id1:','id2:'],dict(beamSpring=10000,beamDamp=0,beamStrength=30000),['a','b'],['a','c'],['b','c'],['c','d',dict(beamType='|BOUNDED',beamSpring=500,beamDamp=10)]],
            hydros=[['id1:','id2:'],['a','d',dict(beamSpring=1000,beamDamp=2)]],
            cadConstraintGroups={'coilover':{'beams':[['c','d']]}})
        manifest=dict(component_roles={'arm':'fl_lower_wishbone','frame':'frame'},mass_allocations={'arm':dict.fromkeys('abc',1),'frame':dict.fromkeys('abd',1)})
        return part,manifest

    def test_only_internal_damping_changes(self):
        p,m=self.fixture();before=copy.deepcopy(p);report=apply(p,m,.5)
        self.assertEqual(len(report['beams']),2)
        self.assertEqual(p['nodes'],before['nodes']);self.assertEqual(p['hydros'],before['hydros'])
        self.assertEqual(p['beams'][:3],before['beams'][:3]);self.assertEqual(p['beams'][-1],before['beams'][-1])
        self.assertEqual(len(p['beams']),len(before['beams']))
        self.assertEqual(p['cadConstraintGroups'],before['cadConstraintGroups'])
        for row in p['beams'][3:5]:self.assertEqual(row[-1],dict(beamDamp=100.,dampCutoffHz=25.))
        self.assertLessEqual(report['unfiltered_envelope']['final_step_eigenvalue'],3.2)

    def test_reject_spring_overlap_and_existing_filter(self):
        for alteration,message in [('spring','physical spring'),('filter','unfiltered baseline')]:
            p,m=self.fixture()
            if alteration=='spring':p['cadConstraintGroups']['bad']={'beams':[['a','c']]}
            else:p['beams'][3].append(dict(dampCutoffHz=25))
            before=copy.deepcopy(p)
            with self.assertRaisesRegex(ValueError,message):apply(p,m,.5)
            self.assertEqual(p,before)

    def test_budget_reduces_damping_without_softening_stiffness(self):
        p,m=self.fixture();p['beams'][1]['beamSpring']=2e6;before=copy.deepcopy(p)
        report=apply(p,m,2.)
        self.assertTrue(any(v['exported_damping_ns_m']<v['requested'] for v in report['beams']))
        self.assertEqual(p['beams'][1],before['beams'][1])
        self.assertLessEqual(report['unfiltered_envelope']['final_step_eigenvalue'],3.2)
        for row in p['beams'][3:5]:self.assertNotIn('beamSpring',row[-1])

    def test_bad_parameters_fail_before_mutation(self):
        for ratio,cutoff in [(0,25),(float('nan'),25),(.5,24),(.5,101)]:
            p,m=self.fixture();before=copy.deepcopy(p)
            with self.assertRaises(ValueError):apply(p,m,ratio,cutoff)
            self.assertEqual(p,before)


if __name__=='__main__':unittest.main()
