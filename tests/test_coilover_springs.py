import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from coilover_springs import rates,crossover_beam


class CoiloverSpringTests(unittest.TestCase):
    def settings(self):return dict(Mode='dual_rate',MainRateNPerM=30000,TenderRateNPerM=15000,CrossoverCompressionM=.01)
    def test_series_rate_and_crossover_are_independent_of_preload(self):
        law=rates(self.settings(),.45,.08);beam=crossover_beam(law)
        self.assertAlmostEqual(law['initial_rate_n_m'],10000);self.assertEqual(law['final_rate_n_m'],30000)
        self.assertEqual(beam['beamType'],'|SUPPORT');self.assertEqual(beam['beamSpring'],20000)
        self.assertAlmostEqual(beam['beamPrecompression']*.45,.44)
        self.assertEqual(beam['beamDamp'],0)
    def test_disabled_legacy_and_invalid_settings(self):
        self.assertIsNone(rates(None,.45,.08));self.assertIsNone(rates(dict(Mode='auto'),.45,.08))
        for key,value in [('Mode','unknown'),('MainRateNPerM',float('nan')),('TenderRateNPerM',0),('CrossoverCompressionM',.09)]:
            settings=self.settings();settings[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):rates(settings,.45,.08)
    def test_actual_generator_uses_one_extra_passive_beam_without_added_nodes_or_mass(self):
        import components as c
        from test_vehicle_template_graph import fixture
        from vehicle_templates import generate
        project,frame,spec,cad=fixture('primary')
        with patch.object(c,'read_geometry',side_effect=cad):
            baseline=generate(project,frame,spec)
            changed=copy.deepcopy(project);comp=next(v for v in changed['Components'] if v['MvpRole']=='fl_spring_damper');comp['CoiloverSpring']=self.settings()
            dual=generate(changed,frame,spec)
        self.assertEqual(baseline[0].nodes,dual[0].nodes)
        self.assertEqual(len(dual[1]['beams']),len(baseline[1]['beams'])+1)
        self.assertAlmostEqual(dual[2]['FL']['spring_n_m'],10000)
        self.assertEqual(dual[2]['FL']['coilover_spring']['final_rate_n_m'],30000)
        for corner in ('FR','RL','RR'):self.assertEqual(baseline[2][corner],dual[2][corner])
    def test_physical_setting_invalidates_project_fingerprint(self):
        import components
        project=dict(Components=[dict(Id='s')]);before=components.fingerprint(project)
        project['Components'][0]['CoiloverSpring']=self.settings()
        self.assertNotEqual(components.fingerprint(project),before)


if __name__=='__main__':unittest.main()
