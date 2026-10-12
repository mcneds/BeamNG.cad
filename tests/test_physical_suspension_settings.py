import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from suspension_loads import physical_settings


class PhysicalSettingsTests(unittest.TestCase):
    def test_declared_law_is_invariant_to_mass_based_estimates(self):
        values=dict(spring_n_m=10000.,damper_ns_m=1200.,spring_preload_n=800.)
        parameters={'suspension_physical_settings':{'FL':values}}
        for defaults in ((1000,200,300),(5000,600,700)):
            result=physical_settings(parameters,'FL',*defaults,{'initial_rate_n_m':10000.})
            self.assertEqual(result,(10000.,1200.,800.,'explicit_physical_settings'))
        self.assertEqual(physical_settings({},'FL',1000,200,300),(1000,200,300,'automatic_mass_based_estimate'))

    def test_invalid_partial_or_conflicting_declarations_fail(self):
        good=dict(spring_n_m=10000.,damper_ns_m=1200.,spring_preload_n=800.)
        for bad in ({'spring_n_m':10000.},good|{'extra':1},good|{'spring_n_m':0},good|{'damper_ns_m':-1},good|{'spring_preload_n':float('nan')},good|{'spring_n_m':True}):
            with self.assertRaises(ValueError):physical_settings({'suspension_physical_settings':{'FL':bad}},'FL',1,2,3)
        with self.assertRaisesRegex(ValueError,'conflicts'):
            physical_settings({'suspension_physical_settings':{'FL':good}},'FL',1,2,3,{'initial_rate_n_m':5000.})
        with self.assertRaisesRegex(ValueError,'corners'):
            physical_settings({'suspension_physical_settings':{'unknown':good}},'FL',1,2,3)


if __name__=='__main__':unittest.main()
