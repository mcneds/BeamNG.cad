import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import verification_receipts as module


class VerificationReceiptTests(unittest.TestCase):
    def test_worker_checks_recorded_evidence_before_promoting_build(self):
        import component_worker
        from frame_harness.vehicle import SCENARIOS
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=root/'manifest.json';manifest.write_text('{"capabilities":["vehicle"]}')
            (root/'tests').mkdir()
            record=dict(status='succeeded',generation_status='succeeded',qualification_status='diagnostic')
            evidence=dict(status='passed',recording_status='completed',verifier_unchanged=True,
                          manifest_sha256=module.digest(manifest),required_runs=3*len(SCENARIOS),completed_runs=3*len(SCENARIOS),
                          runs=[dict(status='passed',recording_status='completed',scenario=name,directory=str(root/f'{name}-{i}')) for name in SCENARIOS for i in range(3)])
            args=['worker','verify','--manifest',str(manifest),'--game',str(root/'game'),'--profile',str(root/'profile')]
            with patch.object(sys,'argv',args), patch.object(component_worker,'completed_build',return_value=(record,root/'mod.zip')), \
                 patch.object(module,'completed_build',return_value=(record,root/'mod.zip')), \
                 patch('frame_harness.vehicle.run_acceptance',return_value=evidence):
                (root/'tests/acceptance.json').write_text(json.dumps(evidence))
                component_worker.main()
                saved=json.loads((root/'static_frame_build.json').read_text())
                self.assertEqual(saved['qualification_status'],'template_acceptance_passed')
                self.assertEqual(saved['vehicle_verification_sha256'],module.digest(root/'tests/acceptance.json'))
                before=(root/'static_frame_build.json').read_bytes()
                evidence['manifest_sha256']='changed'
                (root/'tests/acceptance.json').write_text(json.dumps(evidence))
                with self.assertRaisesRegex(ValueError,'different manifest'):component_worker.main()
                self.assertEqual((root/'static_frame_build.json').read_bytes(),before)

    def test_failed_repeat_withdraws_pass_and_pilots_cannot_requalify(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=root/'manifest.json';manifest.write_text('{}');evidence=root/'check.json'
            record=dict(status='succeeded',generation_status='succeeded',qualification_status='template_acceptance_passed')
            result=dict(status='failed',manifest_sha256=module.digest(manifest),verifier_unchanged=True,
                        runs=[dict(status='failed',recording_status='completed')])
            with patch.object(module,'completed_build',side_effect=lambda p:(copy.deepcopy(record),root/'mod.zip')):
                evidence.write_text(json.dumps(result));record=module.record_vehicle_check(manifest,evidence)
                self.assertEqual(record['qualification_status'],'failed')
                self.assertEqual(record['recording_status'],'completed')
                self.assertEqual(record['generation_status'],'succeeded')
                result['status']='passed';result['runs'][0]['status']='passed';evidence.write_text(json.dumps(result))
                record=module.record_vehicle_check(manifest,evidence)
                self.assertEqual(record['qualification_status'],'failed')
                result.update(required_runs=2,completed_runs=1);evidence.write_text(json.dumps(result))
                with self.assertRaisesRegex(ValueError,'incomplete'):module.record_vehicle_check(manifest,evidence,'acceptance')
                from frame_harness.vehicle import SCENARIOS
                result.update(required_runs=3*len(SCENARIOS),completed_runs=3*len(SCENARIOS),
                              runs=[dict(status='passed',recording_status='completed',scenario=name,directory=str(root/f'{name}-{i}')) for name in SCENARIOS for i in range(3)])
                evidence.write_text(json.dumps(result))
                record=module.record_vehicle_check(manifest,evidence,'acceptance')
                self.assertEqual(record['qualification_status'],'template_acceptance_passed')
                result['runs'][1]['directory']=result['runs'][0]['directory']
                evidence.write_text(json.dumps(result))
                with self.assertRaisesRegex(ValueError,'independent'):module.record_vehicle_check(manifest,evidence,'acceptance')

    def test_diagnostic_cannot_promote_or_withdraw_and_stale_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=root/'manifest.json';manifest.write_text('{}');evidence=root/'check.json'
            result=dict(status='failed',manifest_sha256=module.digest(manifest),verifier_unchanged=True,
                        runs=[dict(status='failed',diagnostic='balance_ballast')])
            evidence.write_text(json.dumps(result))
            for status in ('diagnostic','template_acceptance_passed'):
                with patch.object(module,'completed_build',return_value=(dict(qualification_status=status),root/'mod.zip')):
                    record=module.record_vehicle_check(manifest,evidence)
                    self.assertEqual(record['qualification_status'],status)
                    self.assertEqual(record['latest_diagnostic']['diagnostic'],'balance_ballast')
            manifest.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'different manifest'):module.record_vehicle_check(manifest,evidence)


if __name__=='__main__':unittest.main()
