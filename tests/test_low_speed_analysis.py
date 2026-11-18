import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('low_speed',Path(__file__).resolve().parents[1]/'tools/analyze-low-speed.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)

class LowSpeedAnalysisTests(unittest.TestCase):
    def test_physics_sampling_resolves_frequency_that_graphics_would_alias(self):
        t=np.arange(16000)/2000
        x=4*np.sin(2*np.pi*31*t)+.2*np.sin(2*np.pi*9*t)
        result=analysis.summary(t,x)
        self.assertAlmostEqual(result['peaks_hz'][0],31.)
        self.assertAlmostEqual(result['rms_ac'],np.sqrt((16+.04)/2),places=8)
        self.assertGreater(result['bands_rms']['15-50Hz'],result['bands_rms']['5-15Hz']*10)
        self.assertAlmostEqual(analysis.summary(t[::100],x[::100])['peaks_hz'][0],9.)

    def test_rejects_truncated_nonfinite_and_irregular_signals(self):
        t=np.arange(1000)/2000;x=np.sin(t)
        for bad_t,bad_x in ((t[:50],x[:50]),(t,x[:-1]),(t,np.full(len(t),np.nan)),(t[::-1],x),(np.delete(t,100),np.delete(x,100))):
            with self.assertRaises(ValueError):analysis.summary(bad_t,bad_x)

if __name__=='__main__':unittest.main()
