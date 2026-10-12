import copy,importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('native_appearance',Path(__file__).resolve().parents[1]/'tools/test-synthetic-appearance.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class NativeAppearanceComparisonTests(unittest.TestCase):
    def test_physical_change_cannot_hide_behind_visual_revision(self):
        original=dict(actual_nodes={'n':dict(mass_kg=2.,position=[0.,0.,0.],collision=True)},
            beams=[dict(a=0,b=1,spring=1000.,damp=10.,rest=.1,length=.1001)],torsionbars=[],
            device_graph={},tire_physics={},mass_kg=2.,node_count=1,fixed_nodes=0)
        changed=copy.deepcopy(original);changed['beams'][0]['length']=.1002
        module.compare(module.compiled_physics(original),module.compiled_physics(changed))
        for mutate in (lambda r:r['actual_nodes']['n'].update(mass_kg=2.1),
                       lambda r:r['actual_nodes']['n'].update(collision=False),
                       lambda r:r['beams'][0].update(spring=1100.),
                       lambda r:r['beams'][0].update(rest=.101),
                       lambda r:r['actual_nodes'].pop('n')):
            changed=copy.deepcopy(original);mutate(changed)
            with self.assertRaises(ValueError):module.compare(module.compiled_physics(original),module.compiled_physics(changed))


if __name__=='__main__':unittest.main()
