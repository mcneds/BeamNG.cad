import copy,importlib.util,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('spring_revision',ROOT/'tools/apply-spring-specification.py')
revision=importlib.util.module_from_spec(spec);spec.loader.exec_module(revision)
from suspension_loads import physical_settings

class SpringSpecificationTests(unittest.TestCase):
    def test_conversion_and_series_rate(self):
        self.assertAlmostEqual(revision.effective_rate(dict(model='single',rates_lbf_per_in=[80])),14010.14681971811)
        self.assertAlmostEqual(revision.effective_rate(dict(model='series_unknown_crossover',rates_lbf_per_in=[285,110]))/revision.LBF_PER_IN_TO_N_PER_M,79.36708860759494)
        for rate in (0,-1,float('nan')):
            with self.assertRaises(ValueError):revision.effective_rate(dict(model='single',rates_lbf_per_in=[rate]))

    def test_revision_preserves_preload_damping_geometry_and_roundtrips_generation_inputs(self):
        spring=dict(beamType='|BOUNDED',beamSpring=10000,beamDamp=0,beamPrecompression=1.2)
        damper=dict(beamType='|BOUNDED',beamSpring=0,beamDamp=1500,shortBoundRange=.04)
        part=dict(nodes=[['id','x','y','z'],['a',0,0,0],['b',0,0,.5]],beams=[['id1:','id2:'],['a','b',spring],['a','b',damper],['a','b',dict(beamType='|SUPPORT',beamSpring=20000)]])
        wheel=dict(nodes=dict(shock_top='a',shock_bottom='b'),ride_reference=dict(reference_shock_length_m=.5,captured_shock_length_m=.48),spring_preload_n=1000,damper_ns_m=1500,spring_n_m=10000,coilover_spring={'mode':'dual_rate'})
        m=dict(wheels={'FR':wheel},template_definition={'parameters':{}},explicit_beams=3,limitations=[])
        p={'Components':[dict(Id='s',MvpRole='fr_spring_damper',CoiloverSpring={'Mode':'dual_rate'})]}
        original=copy.deepcopy((part,m,p));specification=dict(source='unit fixture',corners={'FR':dict(model='single',rates_lbf_per_in=[80])})
        part2,m2,p2=revision.revise(part,m,p,specification)
        self.assertEqual((part,m,p),original);self.assertEqual(part2['nodes'],part['nodes']);self.assertEqual(part2['beams'][2],part['beams'][2]);self.assertEqual(m2['explicit_beams'],2)
        w=m2['wheels']['FR'];rest=part2['beams'][1][-1]['beamPrecompression']*.48
        self.assertAlmostEqual((rest-.5)*w['spring_n_m'],1000)
        self.assertEqual(physical_settings(m2['template_definition']['parameters'],'FR',1,2,3)[:3],(w['spring_n_m'],1500,1000))
        self.assertEqual(p2['Components'][0]['CoiloverSpring']['Mode'],'auto')

if __name__=='__main__':unittest.main()
