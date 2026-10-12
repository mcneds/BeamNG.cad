import importlib.util
from pathlib import Path
import csv
import json
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('clutch_diagnostic',Path(__file__).resolve().parents[1]/'tools/diagnose-clutch-hunting.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ClutchDiagnosticTests(unittest.TestCase):
    def fixture(self,run):
        for name,value in {
            'completion.json':dict(status='completed',job_id='test',physics_dt_min=.0005,physics_dt_max=.0005),
            'job.json':dict(id='test',duration=21,target_speed=10),
            'compiled.json':dict(job_id='test',devices={'clutch':dict(type='centrifugalClutch')}),
        }.items():
            (run/name).write_text(json.dumps(value))
        (run/'straight.csv').write_text('sealed diagnostic source')
        data=[dict(physics_t=i*.01,gfx_t=i*.01,speed=10,clutch_input_av=100,
            clutch_output_av=90,clutch_angle=20,clutch_torque=-2,clutch_ratio=1,
            throttle=1,clutch_spring=.7,clutch_damp=.001,cvt_ratio=1) for i in range(1,2101)]
        with (run/'powertrain.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=data[0]);w.writeheader();w.writerows(data)
        return data

    def test_full_engagement_does_not_hide_slip_and_reverse_torque(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.fixture(run);result,_=module.summarize(run)
            self.assertEqual(result['fully_engaged_fraction'],1)
            self.assertEqual(result['slip_rms_rad_s'],10)
            self.assertEqual(result['negative_torque_full_throttle_fraction'],1)
            self.assertTrue(result['speed_within_5_percent'])
            self.assertFalse(result['qualified'])

    def test_identity_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.fixture(run)
            (run/'completion.json').write_text(json.dumps(dict(status='completed',job_id='stale')))
            with self.assertRaisesRegex(ValueError,'identity'):module.summarize(run)

    def test_telemetry_gap_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.fixture(run)
            lines=(run/'powertrain.csv').read_text().splitlines()
            (run/'powertrain.csv').write_text('\n'.join(lines[:100]+lines[120:])+'\n')
            with self.assertRaisesRegex(ValueError,'incomplete'):module.summarize(run)

    def test_wrong_physics_step_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.fixture(run)
            value=json.loads((run/'completion.json').read_text());value['physics_dt_max']=.001
            (run/'completion.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'timestep'):module.summarize(run)

    def test_nonfinite_slip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.fixture(run)
            value=(run/'powertrain.csv').read_text().replace(',100,',',nan,',1)
            (run/'powertrain.csv').write_text(value)
            with self.assertRaisesRegex(ValueError,'nonfinite'):module.summarize(run)

    def test_adaptive_budget_rejects_energy_and_ratio_errors(self):
        # Independent synthetic telemetry: the recorded spring must follow the
        # current gearing, and a stiffness update must not create energy.
        import math
        for violation in (None, 'energy', 'spring', 'step'):
            with self.subTest(violation=violation), tempfile.TemporaryDirectory() as d:
                run=Path(d);data=self.fixture(run)
                budget=dict(engine_inertia_kg_m2=.1,effective_inertia_kg_m2=.001,
                    maximum_gearing=24,frequency_limit_hz=120,rear_reduction=8,
                    step_eigenvalue=.6)
                job=json.loads((run/'job.json').read_text());job['adaptive_clutch']=budget
                (run/'job.json').write_text(json.dumps(job))
                inverse_output=(1000-10)/24**2
                spring=(2*math.pi*120)**2/(2*(10+8**2*inverse_output))
                for row in data:
                    row.update(clutch_spring=spring,compliance_eigenvalue=.6,
                        energy_before_adjustment=1,energy_after_adjustment=1)
                if violation=='energy':data[-1]['energy_after_adjustment']=1.01
                if violation=='spring':data[-1]['clutch_spring']*=1.01
                if violation=='step':data[-1]['compliance_eigenvalue']=.61
                with (run/'powertrain.csv').open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=data[0]);writer.writeheader();writer.writerows(data)
                if violation:
                    with self.assertRaisesRegex(ValueError,'Adaptive compliance'):module.summarize(run)
                else:
                    result,_=module.summarize(run)
                    self.assertEqual(result['adaptive_compliance']['maximum_energy_increase_j'],0)


if __name__=='__main__':unittest.main()
