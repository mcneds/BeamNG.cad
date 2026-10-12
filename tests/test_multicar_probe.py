import importlib.util
from pathlib import Path
import tempfile
import unittest
import json

spec=importlib.util.spec_from_file_location('multi',Path(__file__).resolve().parents[1]/'tools/probe-drive-multicar.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MultiCarComparisonTests(unittest.TestCase):
    def test_polled_command_does_not_contain_large_job_payload(self):
        with tempfile.TemporaryDirectory() as d:
            session=module.MultiSession(module.probe.HarnessProject(userpath=Path(d)),'vehicle')
            session.control=Path(d)
            job={'id':'test-job','children':[{'manifest':{'large':'data'}}]}
            session.command(action='run',job=job)
            control=json.loads((Path(d)/'control.json').read_text())
            self.assertNotIn('job',control);self.assertEqual(control['job_id'],job['id'])
            self.assertEqual(json.loads((Path(d)/'multicar-job.json').read_text()),job)

    def test_requested_capture_files_are_required_not_discovered(self):
        self.assertEqual(module.recording_files({}),['vehicle.csv'])
        names=module.recording_files({'frequency_capture':{'loads':True,'velocities':True,'actuator_targets':True}})
        self.assertEqual(names,['vehicle.csv','frequency.csv','frequency_velocities.csv','frequency_loads.csv','frequency_targets.csv'])

    def compare(self,first,second):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a.csv',Path(d)/'b.csv';a.write_text(first);b.write_text(second)
            return module.compare_csv(a,b)

    def test_complete_equal_recordings_match(self):
        r=self.compare('t,speed\n0,0\n.05,1\n','t,speed\n0,0\n.05,1\n')
        self.assertTrue(r['identical']);self.assertTrue(r['within_tolerance']);self.assertEqual(r['samples'],2)

    def test_numeric_change_reported_as_non_equivalent(self):
        r=self.compare('t,speed\n0,0\n.05,1\n','t,speed\n0,0\n.05,1.01\n')
        self.assertFalse(r['within_tolerance']);self.assertAlmostEqual(r['maximum_absolute_differences']['speed'],.01)

    def test_incomplete_nonfinite_and_bad_clock_rejected(self):
        good='t,speed\n0,0\n.05,1\n'
        for bad in ['t,speed\n0,0\n','t,speed\n0,0\n.05,nan\n','t,speed\n0,0\n0,1\n']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.compare(good,bad)


if __name__=='__main__':unittest.main()
