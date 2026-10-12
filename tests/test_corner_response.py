import importlib.util,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
analysis=load('analyze-corner-response.py');probe=load('probe-corner-response.py')

class CornerResponseTests(unittest.TestCase):
    def test_angle_wrap_does_not_create_false_large_response(self):
        answer=analysis.residual(np.deg2rad([-179.9,179.9]),np.deg2rad([179.9,-179.9]))
        np.testing.assert_allclose(np.rad2deg(answer),[.2,-.2],atol=1e-12)

    def test_amplitude_comparison_detects_phase_error(self):
        t=np.arange(2000)/2000;y=np.sin(2*np.pi*15*t)
        self.assertAlmostEqual(analysis.linearity(y,y/2)['relative_rms_difference'],0)
        self.assertGreater(analysis.linearity(y,np.cos(2*np.pi*15*t)/2)['relative_rms_difference'],1)
        with self.assertRaises(ValueError):analysis.linearity(np.zeros(3),np.zeros(3))

    def test_production_checks_remain_and_changed_hook_is_rejected(self):
        source=(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text(encoding='utf-8')
        changed=probe.instrument(source)
        for check in ('Compiled beam/properties differ','Compiled fixture pins differ','Compiled angular brace differs','Missing wheel'):
            self.assertIn(check,changed)
        self.assertIn('shiftToGearIndex(0)',changed)
        self.assertNotIn('electrics.setIgnitionLevel(3)',changed)
        with self.assertRaisesRegex(ValueError,'hook changed'):probe.instrument(source.replace('electrics.setIgnitionLevel(3)','electrics.setIgnitionLevel(2)'))

if __name__=='__main__':unittest.main()
