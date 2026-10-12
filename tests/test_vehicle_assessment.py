import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_assessment import assess


class VehicleAssessmentTests(unittest.TestCase):
    def test_drift_failure_does_not_mean_mechanism_failure_or_dynamics_pass(self):
        result=dict(status='failed',checks=dict(no_broken_beams=True,FL_toe_error_deg=True,straight_lateral_drift=False))
        dimensions=assess(result,['FL_toe_error_deg','straight_lateral_drift'],validated=True,expected_motion=True)['dimensions']
        self.assertEqual(dimensions['kinematics']['status'],'screen_passed')
        self.assertEqual(dimensions['handling']['status'],'screen_failed')
        self.assertEqual(dimensions['physical_dynamics']['status'],'not_assessed')
        self.assertEqual(result['status'],'failed')

    def test_unknown_failures_and_missing_motion_are_not_dropped(self):
        result=dict(checks={'new_contract':False})
        dims=assess(result,validated=True,expected_motion=True)['dimensions']
        self.assertEqual(dims['implementation']['status'],'screen_failed')
        self.assertEqual(dims['kinematics']['status'],'screen_failed')

    def test_invalid_recording_cannot_pass_even_if_checks_are_green(self):
        dims=assess(dict(checks=dict(no_broken_beams=True,FL_toe_error_deg=True)),['FL_toe_error_deg'])['dimensions']
        self.assertTrue(all(v['status']=='not_assessed' for v in dims.values()))


if __name__=='__main__':unittest.main()
