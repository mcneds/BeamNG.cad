import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness.frequency_registration import fits
from frame_harness.vehicle_motion import rigid_fit


class RegistrationTests(unittest.TestCase):
    def test_statistics_match_full_fit_with_deformation_and_large_translation(self):
        rng=np.random.default_rng(42)
        original=rng.normal(size=(95,3));weights=rng.uniform(.2,8,95);weights/=weights.sum()
        center=weights@original
        current=original@np.array([[0,-1,0],[1,0,0],[0,0,1]])+rng.normal(scale=.002,size=(95,3))+[10000,20000,3000]
        h=((original-center)*weights[:,None]).T@(current-current[0])
        stats=np.r_[weights@current,h.ravel()][None,:]
        rotation,translation=fits(original,weights,stats)
        expected_r,expected_t=rigid_fit(original,current,weights)
        np.testing.assert_allclose(rotation[0],expected_r,atol=1e-12)
        np.testing.assert_allclose(translation[0],expected_t,atol=1e-10)

    def test_rejects_collapsed_or_nonfinite_statistics(self):
        original=np.eye(3)
        for stats in (np.zeros((1,12)),np.full((1,12),np.nan)):
            with self.assertRaises(ValueError):fits(original,np.ones(3),stats)


if __name__=='__main__':unittest.main()
