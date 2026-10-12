import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('suspension_diagnostic', ROOT/'tools/diagnose-straightline-suspension.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FixedReference:
    def __init__(self, manifest):
        self.points = manifest['template_definition']['hardpoints']

    def solve(self, corner, travel, extension):
        hub = np.array(self.points[corner]['hub'])+np.array([0., 0., travel])
        return dict(hub=hub, hub_axis=hub+np.array([1., 0., 0.]))


class SuspensionDiagnosticTests(unittest.TestCase):
    def fixture(self, root):
        positions = [[-1, -1, 0], [1, -1, 0], [-1, 1, 0], [1, 1, .2]]
        points = {c: dict(hub=[x, y, .5], hub_axis=[x+1, y, .5])
                  for c, x, y in [('FL', -1, 1), ('FR', 1, 1), ('RL', -1, -1), ('RR', 1, -1)]}
        chassis = ['c'+str(i) for i in range(4)]
        manifest = dict(chassis_nodes=chassis, nodes={n: dict(position=p, mass_kg=i+1)
            for i, (n, p) in enumerate(zip(chassis, positions))}, wheels={c: {} for c in points},
            template_definition=dict(hardpoints=points))
        rotation = Rotation.from_euler('xyz', [.2, -.3, .7]).as_matrix()
        records = []
        for i in range(1, 33):
            translation = np.array([i, i*.2, .7])
            wheels = {}
            for corner, p in points.items():
                # A deliberate half-degree wheel error must survive chassis registration.
                axis = np.array([np.cos(np.radians(.5)), np.sin(np.radians(.5)), 0.])
                if corner.endswith('R'):
                    axis *= -1
                wheels[corner] = dict(axis=(axis@rotation).tolist(),
                    center=((np.array(p['hub'])+[0, 0, .01])@rotation+translation).tolist())
            records.append(dict(t=i*.25, steering_applied=0, steering_source='cadHarness',
                steering_filter='FILTER_AI', wheels=wheels,
                reference_positions={n: (np.array(p)@rotation+translation).tolist()
                                     for n, p in zip(chassis, positions)}))
        (root/'build_manifest.json').write_text(json.dumps(manifest))
        (root/'completion.json').write_text('{"status":"completed"}')
        (root/'job.json').write_text('{"scenario":"stock_straightline_diagnostic","duration":8}')
        self.write_motion(root, records)
        return records

    def write_motion(self, root, records):
        (root/'motion.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n')

    def test_rigid_chassis_motion_and_opposed_axis_order_do_not_hide_wheel_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with patch.object(module, 'Predictor', FixedReference):
                result = module.diagnose(root, 5.)
            self.assertFalse(result['qualified'])
            for corner in result['means'].values():
                self.assertAlmostEqual(corner['toe_error_deg'], .5, places=9)
                self.assertAlmostEqual(corner['travel_m'], .01, places=9)
                self.assertLess(corner['hub_path_error_m'], 1e-12)

    def test_nonzero_or_assisted_steering_cannot_supply_centred_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = self.fixture(root)
            records[-1]['steering_applied'] = .01
            self.write_motion(root, records)
            with patch.object(module, 'Predictor', FixedReference), self.assertRaisesRegex(ValueError, 'steering'):
                module.diagnose(root, 5.)

    def test_truncated_or_missing_wheel_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = self.fixture(root)
            self.write_motion(root, records[:-3])
            with self.assertRaisesRegex(ValueError, 'telemetry'):
                module.diagnose(root, 5.)
            del records[-1]['wheels']['FR']
            self.write_motion(root, records)
            with patch.object(module, 'Predictor', FixedReference), self.assertRaisesRegex(ValueError, 'Missing wheel'):
                module.diagnose(root, 5.)


if __name__ == '__main__':
    unittest.main()
