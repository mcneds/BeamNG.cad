import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ComparisonTests(unittest.TestCase):
    def test_different_control_cadences_cannot_be_labelled_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spectrum = dict(mean=0, ac_rms=0.01, peak=0.02, peaks=[], bands_rms={},
                            frequency_hz=[0, 1000], density=[1e-7, 1e-8])
            probe = dict(mode='null', deterministic=True, sources_unchanged=True, manifest_sha256='same-build')
            for name, speed in [('baseline', 3), ('candidate', 6)]:
                folder = root / name
                folder.mkdir()
                (folder / 'frequency.csv').write_text('physics_s\n40.0000\n40.0005\n')
                (folder / 'frequency_wheels.csv').write_text(
                    'physics_s,FL_angularVelocity,FR_angularVelocity\n40.0000,10,10\n40.0005,10,10\n')
                files = {
                    'frequency.json': dict(complete=True),
                    'frequency_wheels.json': dict(complete=True, job_id=name, samples=2, names=['FL', 'FR', 'RL', 'RR']),
                    'job.json': dict(id=name, scenario='steady_speed', steady_speed=dict(target_m_s=speed)),
                    'probe.json': dict(probe, deterministic=name == 'baseline'),
                }
                for filename, data in files.items():
                    (folder / filename).write_text(json.dumps(data))
                evidence = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest()
                            for n in ('frequency.json', 'frequency.csv')}
                report = dict(qualification_status='diagnostic_only', samples=2, evidence_sha256=evidence,
                              channels=dict(FL_toe_error_deg=spectrum, FR_toe_error_deg=spectrum))
                (folder / 'frequency_analysis.json').write_text(json.dumps(report))

            script = Path(__file__).resolve().parents[1] / 'tools/compare-suspension-frequency.py'
            output = root / 'result.json'
            command = [sys.executable, str(script), str(root / 'baseline'), str(root / 'candidate'),
                       '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Mismatched execution/control timing', result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix('.png').exists())

            (root / 'candidate' / 'probe.json').write_text(json.dumps(probe))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertTrue(output.with_suffix('.png').is_file())


if __name__=='__main__':unittest.main()
