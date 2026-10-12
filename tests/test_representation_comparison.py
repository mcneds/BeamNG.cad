import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('study',Path(__file__).resolve().parents[1]/'tools/report-motion-inertia-study.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RepresentationComparisonTests(unittest.TestCase):
    def test_node_changes_require_explicit_validated_representation_proof(self):
        old={'scenario':'reverse','frequency_capture':{'nodes':['hardpoint','carrier_mass_0'],'start_s':4.,'duration_s':4.}}
        new=copy.deepcopy(old);new['frequency_capture']['nodes']=['hardpoint','shaft_outer']
        with self.assertRaises(ValueError):module.recording_controls(old,new)
        proof={'removed_quadrature_nodes':['carrier_mass_0'],'shared_joints':[{'node':'shaft_outer'}]}
        module.recording_controls(old,new,proof)
        new['frequency_capture']['nodes'].remove('hardpoint')
        with self.assertRaisesRegex(ValueError,'Unrelated'):module.recording_controls(old,new,proof)

    def test_recording_window_must_still_match(self):
        old={'scenario':'reverse','frequency_capture':{'nodes':['hardpoint'],'start_s':4.,'duration_s':4.}}
        new=copy.deepcopy(old);new['frequency_capture']['start_s']=3.
        with self.assertRaisesRegex(ValueError,'cadence'):module.recording_controls(old,new,{'removed_quadrature_nodes':[],'shared_joints':[]})


if __name__=='__main__':unittest.main()
