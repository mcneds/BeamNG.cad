import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('floor_audit',ROOT/'tools/audit-suspension-mass-floors.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MassFloorAuditTests(unittest.TestCase):
    def model(self):
        return dict(chassis_nodes=[],component_roles={'arm':'fl_upper_wishbone','carrier':'fl_upright'},
            mass_allocations={'arm':{'tip':3.},'carrier':{'tip':3.,'aux':2.}},
            nodes={'tip':{'mass_kg':6.},'aux':{'mass_kg':2.}},
            numerical_mass=dict(target_kg=2.,nodes={'tip':dict(added_mass_kg=5.,redistributed_cad_mass_kg=1.,target_kg=4.,reasons=['loaded'])},
                                spectral_mass_increments=[dict(name='aux',added_kg=1.)]))

    def run_audit(self,model):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'manifest.json';path.write_text(json.dumps(model))
            with patch.object(module,'motion_cost',return_value=({'tip':4.,'aux':1.},{})):
                return module.audit(path)

    def test_shared_node_counted_once_and_unlisted_ballast_removed(self):
        r=self.run_audit(self.model())
        self.assertEqual(len(r['nodes']),2)
        self.assertEqual(r['kinetic_mass_kg'],dict(simulated_mass_kg=26.,captured_mass_kg=5.,declared_floor_kg=17.,base_floor_only_kg=9.))
        self.assertFalse(r['qualified'])

    def test_inconsistent_physical_credit_rejected(self):
        m=self.model();m['numerical_mass']['nodes']['tip']['redistributed_cad_mass_kg']=2.
        with self.assertRaisesRegex(ValueError,'Inconsistent CAD'):self.run_audit(m)


if __name__=='__main__':unittest.main()
