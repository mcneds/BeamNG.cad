import copy,hashlib,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from rigidity_mass_plan import apply,constraint_factor
from vehicle_revisions import canonical


class RigidityMassPlanTests(unittest.TestCase):
    def fixture(self):
        p={'nodes':[['id','posX','posY','posZ'],['a',0.,0.,0.,{'nodeWeight':2.}],['b',1.,0.,0.,{'nodeWeight':2.}],['c',0.,1.,0.,{'nodeWeight':2.}]],
           'beams':[['id1:','id2:'],['a','b',{'beamSpring':1000.,'beamDamp':0.}],['b','c',{'beamSpring':1000.,'beamDamp':0.}],['a','c',{'beamSpring':1000.,'beamDamp':0.}]]}
        m=dict(main_part='test',component_roles={'arm':'fl_upper_wishbone'},rigid_refits={'arm':{}},chassis_nodes=[],wheels={},
            nodes={r[0]:dict(position=r[1:4],mass_kg=2.) for r in p['nodes'][1:]},mass_allocations={'arm':dict(a=2.,b=2.,c=2.)},
            numerical_mass=dict(added_mass_kg=0.,added_by_component_kg={},nodes={},material_mass_equivalent=True),component_reports={'arm':{}},
            expected_dry_mass_kg=6.,connection_budget={},limitations=[])
        plan=dict(status='offline_plan_only',baseline_jbeam_sha256=hashlib.sha256(canonical({'test':p})).hexdigest(),factor=1.5,step_limit=3.2,
            changed_constraints=[dict(section='beams',index=i,key='beamSpring',before=1000.,after=1500.) for i in range(1,4)],
            nodes=[dict(name='a',before_kg=2.,after_kg=2.1)],total_added_kg=.1)
        return p,m,plan

    def test_positive_change_keeps_geometry_and_accounts_mass(self):
        p,m,plan=self.fixture();before=copy.deepcopy(p)
        def refresh(meta,delta):meta['expected_dry_mass_kg']=sum(n['mass_kg'] for n in meta['nodes'].values())
        with patch('rigidity_mass_plan.refresh_load_metadata',side_effect=refresh):apply(p,m,plan)
        self.assertAlmostEqual(m['expected_dry_mass_kg'],6.1);self.assertAlmostEqual(m['numerical_mass']['added_mass_kg'],.1)
        self.assertAlmostEqual(m['mass_allocations']['arm']['a'],2.1)
        for a,b in zip(before['nodes'][1:],p['nodes'][1:]):self.assertEqual(a[:4],b[:4])
        for row in p['beams'][1:]:self.assertEqual(row[-1],{'beamSpring':1500.,'beamDamp':0.})

    def test_stale_source_and_mass_cap_fail_without_mutation(self):
        for kind in ('stale','cap','coefficient'):
            p,m,plan=self.fixture();before=copy.deepcopy((p,m))
            if kind=='stale':plan['baseline_jbeam_sha256']='0'*64
            if kind=='coefficient':plan['changed_constraints'][0]['after']=500.
            with self.assertRaises(ValueError):apply(p,m,plan,added_limit=.01 if kind=='cap' else 30.)
            self.assertEqual((p,m),before)

    def test_physical_spring_is_never_selected(self):
        p,m,plan=self.fixture();p['cadConstraintGroups']={'spring':{'beams':[['a','b']]}}
        plan['baseline_jbeam_sha256']=hashlib.sha256(canonical({'test':p})).hexdigest()
        with self.assertRaisesRegex(ValueError,'physical spring'):apply(p,m,plan)

    def test_declared_budget_cannot_be_bypassed_by_larger_build_allowance(self):
        p,m,plan=self.fixture();before=copy.deepcopy((p,m));plan['added_budget_kg']=.05
        with self.assertRaisesRegex(ValueError,'declared budget'):apply(p,m,plan,added_limit=30.)
        self.assertEqual((p,m),before)

    def test_upper_factor_is_reconstructed_and_does_not_relax_spring_guard(self):
        p,m,plan=self.fixture();plan['upper_factor']=2.5
        for row in plan['changed_constraints']:row['after']=2500.
        original=copy.deepcopy((p,m,plan))
        def refresh(meta,delta):meta['expected_dry_mass_kg']=sum(n['mass_kg'] for n in meta['nodes'].values())
        with patch('rigidity_mass_plan.refresh_load_metadata',side_effect=refresh):apply(p,m,plan)
        self.assertTrue(all(row[-1]['beamSpring']==2500. for row in p['beams'][1:]))
        p,m,plan=copy.deepcopy(original);plan['changed_constraints'][0]['after']=2600.
        with self.assertRaisesRegex(ValueError,'coefficient mismatch'):apply(p,m,plan)
        p,m,plan=copy.deepcopy(original);p['cadConstraintGroups']={'spring':{'beams':[['a','b']]}}
        plan['baseline_jbeam_sha256']=hashlib.sha256(canonical({'test':p})).hexdigest()
        with self.assertRaisesRegex(ValueError,'physical spring'):apply(p,m,plan)

    def test_upper_region_does_not_include_lower_arm_or_cross_joint_edges(self):
        _,m,_=self.fixture();m['chassis_nodes']=['x','y','z'];m['frame_reference']={'mode':'rigid_reference'}
        m['wheels']={'FL':{'hardpoint_nodes':{'upper_inner_front':'x','upper_inner_rear':'y'}}}
        for ids,section,expected in [(['a','b'],'beams',2.5),(['x','z'],'beams',2.5),
                                     (['a','z'],'beams',1.5),(['lower','z'],'beams',1.5),(['x','z'],'hydros',1.5)]:
            self.assertEqual(constraint_factor(m,ids,section,1.5,2.5),expected)
        m['frame_reference']['mode']='calibrated'
        with self.assertRaisesRegex(ValueError,'numerical frame'):constraint_factor(m,['x','z'],'beams',1.5,2.5)

    def test_upright_factor_is_local_and_independent_of_upper_factor(self):
        _,m,_=self.fixture();m['component_roles']['carrier']='fr_upright'
        m['mass_allocations']['carrier']={'u':2.,'v':2.,'w':2.};m['rigid_refits']['carrier']={}
        for ids,section,expected in [(['u','v'],'beams',2.25),(['a','b'],'beams',3.),
                                    (['a','u'],'beams',1.5),(['u','v'],'hydros',1.5)]:
            self.assertEqual(constraint_factor(m,ids,section,1.5,3.,2.25),expected)
        del m['rigid_refits']['carrier']
        with self.assertRaisesRegex(ValueError,'numerical rigid fit'):constraint_factor(m,['u','v'],'beams',1.5,None,2.25)

    def test_upright_application_rechecks_coefficients_and_rejects_bad_factors(self):
        p,m,plan=self.fixture();m['component_roles']['arm']='fl_upright';plan['upright_factor']=2.25
        for row in plan['changed_constraints']:row['after']=2250.
        original=copy.deepcopy((p,m,plan))
        def refresh(meta,delta):meta['expected_dry_mass_kg']=sum(n['mass_kg'] for n in meta['nodes'].values())
        with patch('rigidity_mass_plan.refresh_load_metadata',side_effect=refresh):apply(p,m,plan)
        self.assertTrue(all(row[-1]['beamSpring']==2250. for row in p['beams'][1:]))
        for factor in [True,1.,3.1,float('nan')]:
            p,m,plan=copy.deepcopy(original);plan['upright_factor']=factor;before=copy.deepcopy((p,m))
            with self.assertRaisesRegex(ValueError,'upright factor'):apply(p,m,plan)
            self.assertEqual((p,m),before)
        p,m,plan=copy.deepcopy(original);plan['changed_constraints'][0]['after']=2200.
        with self.assertRaisesRegex(ValueError,'coefficient mismatch'):apply(p,m,plan)
        p,m,plan=copy.deepcopy(original);p['cadConstraintGroups']={'spring':{'beams':[['a','b']]}}
        plan['baseline_jbeam_sha256']=hashlib.sha256(canonical({'test':p})).hexdigest()
        with self.assertRaisesRegex(ValueError,'physical spring'):apply(p,m,plan)


if __name__=='__main__':unittest.main()
