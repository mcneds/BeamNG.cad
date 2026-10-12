import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('routing',Path(__file__).resolve().parents[1]/'tools/analyze-force-routing.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class RoutingTests(unittest.TestCase):
    def test_truncated_or_shifted_recording_rejected(self):
        t=np.arange(20)*.0005;rows=np.column_stack([t,np.zeros((20,6))])
        self.assertEqual(r.validate_rows(rows,t,2,1).shape,(20,2,1,3))
        with self.assertRaisesRegex(ValueError,'Truncated'):r.validate_rows(rows[:-1],t,2,1)
        rows[5,0]+=.0005
        with self.assertRaisesRegex(ValueError,'timestamps'):r.validate_rows(rows,t,2,1)

    def test_wrong_force_sign_or_scale_rejected(self):
        expected=np.array([[100.,-50.,3.],[150.,20.,-2.]])
        self.assertEqual(r.check_force(expected,expected),0)
        for actual in (-expected,expected*1.01):
            with self.assertRaisesRegex(ValueError,'independently'):r.check_force(actual,expected)


if __name__=='__main__':unittest.main()
