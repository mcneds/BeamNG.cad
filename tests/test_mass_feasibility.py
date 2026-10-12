import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('mass_feasibility',Path(__file__).resolve().parents[1]/'tools/audit-mass-feasibility.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MassFeasibilityTests(unittest.TestCase):
    def test_shared_floor_is_counted_once(self):
        r=module.bound({'n':[0,0,0]},{'a':{'n':1.},'b':{'n':1.}},{'n':2.},10)
        self.assertAlmostEqual(r['minimum_added_kg'],0.)

    def test_low_mass_two_endpoint_component_has_unavoidable_ballast(self):
        r=module.bound({'a':[0,0,0],'b':[1,0,0]},{'shaft':{'a':.1,'b':.1}},{'a':2.,'b':2.},1)
        self.assertAlmostEqual(r['minimum_added_kg'],3.8)
        self.assertAlmostEqual(r['dual_lower_bound_kg'],3.8)

    def test_inertia_restriction_is_stricter_than_mass_and_com(self):
        points={'a':[-1,0,0],'b':[0,0,0],'c':[1,0,0]}
        allocation={'body':{'a':.5,'b':3.,'c':.5}}
        values=[module.bound(points,allocation,{'a':2.},order)['minimum_added_kg'] for order in (1,4,10)]
        self.assertAlmostEqual(values[0],0.)
        self.assertAlmostEqual(values[1],0.)
        self.assertAlmostEqual(values[2],1.5)

    def ledger(self):
        return dict(nodes={'a':{'mass_kg':3.},'b':{'mass_kg':2.}},
            mass_allocations={'one':{'a':1.,'b':.5},'two':{'a':2.,'b':1.5}},
            numerical_mass=dict(added_mass_kg=2.,added_by_component_kg={'one':.5,'two':1.5},
                nodes={'a':dict(added_mass_kg=1.,simulated_mass_kg=3.,redistributed_cad_mass_kg=2.,
                    added_by_component_kg={'one':.25,'two':.75})},
                spectral_mass_increments=[dict(name='a',before_kg=2.5,after_kg=3.,added_kg=.5),
                    dict(name='b',before_kg=1.,after_kg=2.,added_kg=1.)]),
            wheels={'FL':{'wheel_mass_kg':4.}},cad_dry_mass_kg=7.,expected_dry_mass_kg=9.)

    def test_recovers_loaded_and_unloaded_spectral_mass_without_double_count(self):
        m=self.ledger(); before=copy.deepcopy(m);a,extra,rings=module.recover(m)
        self.assertEqual(a,{'one':{'a':.75,'b':.25},'two':{'a':1.25,'b':.75}})
        self.assertEqual(extra,{'one':.5,'two':1.5}); self.assertEqual(rings,4.)
        self.assertEqual(m,before)

    def test_rejects_altered_ledger(self):
        for mutate in (lambda m:m['nodes']['b'].update(mass_kg=2.1),
            lambda m:m['numerical_mass']['added_by_component_kg'].update(one=.6),
            lambda m:m.update(cad_dry_mass_kg=8.)):
            m=self.ledger();mutate(m)
            with self.assertRaises(ValueError):module.recover(m)


if __name__=='__main__':unittest.main()
