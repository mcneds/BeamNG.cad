"""Check that drift comparisons distinguish initial heading from ongoing curvature."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('stock_straightline',
    Path(__file__).resolve().parents[1]/'tools/compare-stock-straightline.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StraightlineTests(unittest.TestCase):
    def test_rack_capture_uses_native_hydro_endpoints_and_rejects_missing_nodes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            manifest=dict(chassis_nodes=['chassis'],steering_contract=dict(
                housing_nodes=['housing'],rail_nodes={'rail':['rail_a','rail_b']},
                actuator_nodes=['actuator','housing']))
            names=['chassis','housing','rail_a','rail_b','FL_tie_inner','FR_tie_inner']
            positions={name:[0,0,0] for name in names}
            (root/'compiled.json').write_text(json.dumps(dict(nodes=[dict(id=1,name='actuator'),dict(id=2,name='housing'),dict(id=3)])))
            row=dict(t=18,steering_applied=0,reference_positions=positions,
                hydros=[dict(a=1,b=2,a_world=[1,2,3],b_world=[0,0,0])])
            (root/'motion.jsonl').write_text(json.dumps(row)+'\n')
            result=module.rack_motion(root,manifest)
            self.assertEqual(result['samples'][0]['reference_positions']['actuator'],[1,2,3])
            self.assertFalse(result['qualified'])
            row['hydros']=[]
            (root/'motion.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'Incomplete rack'):module.rack_motion(root,manifest)

    def fixture(self,root,heading=.01,curvature=0,count=500):
        rows=[]
        for i in range(1,count+1):
            t=i*.05;s=max(0,t-4)*10
            lateral=curvature*s*s
            rows.append(dict(t=t,speed=10,forward_distance=s*math.cos(heading)-lateral*math.sin(heading),
                lateral_distance=s*math.sin(heading)+lateral*math.cos(heading),
                heading_rad=heading+math.atan(2*curvature*s),steering_applied=0,broken=0))
        with (root/'straight.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        (root/'completion.json').write_text(json.dumps(dict(status='completed',physics_dt_min=.0005,physics_dt_max=.0005)))

    def test_initial_heading_does_not_become_curvature(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            report=module.analyze(root)
            self.assertGreater(report['raw_peak_lateral_m'],2)
            self.assertLess(report['settled_peak_lateral_m'],1e-12)
            self.assertAlmostEqual(report['distance_windows']['50']['t'],9)

    def test_nonlinear_drift_is_retained_at_matching_distance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root,curvature=.001)
            report=module.analyze(root)
            self.assertAlmostEqual(report['distance_windows']['50']['settled_lateral_m'],2.5)
            self.assertGreater(report['final_heading_change_deg'],20)

    def test_failed_recording_cannot_supply_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'completion.json').write_text('{"status":"failed"}')
            with self.assertRaises(ValueError):module.analyze(root)

    def test_cruise_uses_fixed_window_and_verifies_speed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root,count=900)
            (root/'job.json').write_text('{"target_speed":10}')
            cruise=module.analyze(root)['cruise']
            self.assertEqual(cruise['start_t'],18)
            self.assertTrue(cruise['speed_within_5_percent'])
            self.assertAlmostEqual(cruise['windows']['100']['lateral'],0)
            (root/'job.json').write_text('{"target_speed":12}')
            self.assertFalse(module.analyze(root)['cruise']['speed_within_5_percent'])


if __name__=='__main__':unittest.main()
