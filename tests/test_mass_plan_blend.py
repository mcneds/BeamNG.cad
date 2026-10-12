import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('blend',Path(__file__).resolve().parents[1]/'tools/blend-rigidity-mass-plans.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MassPlanBlendTests(unittest.TestCase):
    def fixture(self):
        return dict(status='offline_plan_only',baseline_receipt='receipt',baseline_jbeam_sha256='abc',changed_constraints=[dict(before=1,after=2)],factor=2,selection='front',step_limit=3.2,maximum_mass_factor=4,nodes=[dict(name='a',before_kg=2,after_kg=4)])

    def test_union_uses_baseline_mass_for_node_missing_from_one_parent(self):
        a=self.fixture();b=copy.deepcopy(a);b['nodes']=[dict(name='b',before_kg=3,after_kg=7)]
        result=module.blend(a,b,.25);m={r['name']:r['after_kg'] for r in result['nodes']}
        self.assertEqual(m,dict(a=3.5,b=4.));self.assertEqual(result['total_added_kg'],2.5)

    def test_different_stiffness_or_reference_and_invalid_fraction_fail(self):
        a=self.fixture();b=copy.deepcopy(a);b['changed_constraints'][0]['after']=3
        with self.assertRaises(ValueError):module.blend(a,b,.5)
        for fraction in (0,1,float('nan')):
            with self.assertRaises(ValueError):module.blend(a,a,fraction)

    def test_budget_repair_does_not_allow_unstable_parent(self):
        a=self.fixture();b=copy.deepcopy(a)
        b.update(status='not_converged_no_candidate',final_step_eigenvalue=3.19,added_budget_kg=1.,total_added_kg=2.)
        with self.assertRaises(ValueError):module.blend(a,b,.5)
        self.assertEqual(module.blend(a,b,.5,allow_budget_repair=True)['status'],'offline_plan_only')
        b['final_step_eigenvalue']=3.21
        with self.assertRaises(ValueError):module.blend(a,b,.5,allow_budget_repair=True)

    def test_regional_factor_is_preserved_and_must_match(self):
        a=self.fixture();a['upper_factor']=2.5;b=copy.deepcopy(a)
        self.assertEqual(module.blend(a,b,.5)['upper_factor'],2.5)
        b['upper_factor']=2.75
        with self.assertRaisesRegex(ValueError,'upper-arm'):module.blend(a,b,.5)


if __name__=='__main__':unittest.main()
