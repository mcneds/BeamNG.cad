"""Native pilot/acceptance batches using only an owned BeamNG test profile."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
HARNESS=ROOT/'dependencies/cad-calibration/Test Harness'
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(HARNESS)]
from build_static_frame import completed_build
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.vehicle import run_vehicle,run_acceptance
from frame_harness.build import write_json

p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--scenario',nargs='+',default=['settle','supported','articulation'])
p.add_argument('--continue-on-failure',action='store_true',help='Diagnostic pilots only: record all requested scenarios; failures still fail the batch')
p.add_argument('--diagnostic-no-aero',action='store_true',help='Disable aero in the owned test copy; results cannot qualify the vehicle')
p.add_argument('--diagnostic-no-self-collision',action='store_true',help='Disable explicit-node self collision in the owned test copy; results cannot qualify the vehicle')
p.add_argument('--diagnostic-balance-ballast',action='store_true',help='Add a test-only chassis counterweight to center lateral COM; never qualifies the vehicle')
p.add_argument('--diagnostic-symmetric-ballast',action='store_true',help='Mass-matched control: split that test counterweight over mirrored chassis nodes')
p.add_argument('--diagnostic-drop',action='store_true',help='Drop the unchanged vehicle 3 m onto the owned test surface; diagnostic only')
p.add_argument('--no-internal-static',action='store_true',help='Drop comparison only: explicitly disable terrain contact on already noncolliding internal nodes')
p.add_argument('--profile',type=Path,default=Path('H:/BeamNGCadHarness/synthetic-mvp-20261007'))
p.add_argument('--startup-timeout',type=float,default=180.,help='Wall-clock allowance for game/level startup; physics test durations and acceptance limits are unchanged')
p.add_argument('--game',type=Path,default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'));p.add_argument('--save-report',action='store_true');a=p.parse_args()
if a.continue_on_failure and a.scenario==['acceptance']:p.error('Acceptance always stops at the first failure')
if a.no_internal_static and not a.diagnostic_drop:p.error('Internal static-contact comparison requires --diagnostic-drop')
if a.diagnostic_drop and (a.scenario!=['settle'] or any((a.diagnostic_no_aero,a.diagnostic_no_self_collision,a.diagnostic_balance_ballast,a.diagnostic_symmetric_ballast))):
    p.error('Drop diagnostic requires one settling run without another intervention')
if (a.diagnostic_balance_ballast or a.diagnostic_symmetric_ballast) and (a.scenario!=['acceleration'] or
        sum((a.diagnostic_balance_ballast,a.diagnostic_symmetric_ballast,a.diagnostic_no_aero,a.diagnostic_no_self_collision))!=1):
    p.error('Counterweight intervention requires one acceleration pilot without another intervention')
if a.diagnostic_no_aero and a.scenario!=['acceleration']:p.error('Aero intervention requires one acceleration pilot')
if a.diagnostic_no_self_collision and (a.diagnostic_no_aero or any(s not in ('settle','acceleration') for s in a.scenario)):
    p.error('Self-collision intervention requires settling/acceleration pilots without another intervention')
diagnostic='drop' if a.diagnostic_drop else 'symmetric_ballast' if a.diagnostic_symmetric_ballast else 'balance_ballast' if a.diagnostic_balance_ballast else 'no_aero' if a.diagnostic_no_aero else 'no_self_collision' if a.diagnostic_no_self_collision else None
if a.no_internal_static:diagnostic='drop_no_internal_static'
completed_build(a.manifest.parent/'static_frame_build.json')
manifest_sha=hashlib.sha256(a.manifest.read_bytes()).hexdigest()
project=HarnessProject(game=a.game,userpath=a.profile,source=a.manifest.parent,runs=a.manifest.parent/'tests',startup_timeout=a.startup_timeout)
implementation={str(f.relative_to(HARNESS)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py','.lua')}
if a.scenario==['acceptance']:result=run_acceptance(a.manifest,project=project,save_report=a.save_report)
else:
    results=[]
    with DriveSession(project,'vehicle') as session:
        for scenario in a.scenario:
            results.append(run_vehicle(a.manifest,scenario,project=project,session=session,diagnostic=diagnostic))
            if results[-1]['status']!='passed' and not a.continue_on_failure:break
    result=dict(status='passed' if len(results)==len(a.scenario) and all(r['status']=='passed' for r in results) else 'failed',runs=results)
unchanged=implementation=={str(f.relative_to(HARNESS)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py','.lua')}
if not unchanged or hashlib.sha256(a.manifest.read_bytes()).hexdigest()!=manifest_sha:
    result.update(status='failed',reason='Manifest or verifier source changed during pilot')
if a.scenario!=['acceptance'] and result['status']=='passed' and not a.save_report:
    from frame_harness.component_tests import compact_success
    for run in result['runs']:compact_success(run['directory'])
    result['full_report_saved']=False
evidence=a.manifest.parent/('pilot-diagnostic-'+diagnostic+'.json' if diagnostic else 'pilot-verification.json')
write_json(evidence,result|dict(implementation=implementation,verifier_unchanged=unchanged,manifest_sha256=manifest_sha,diagnostic=diagnostic))
from verification_receipts import record_vehicle_check
if unchanged and hashlib.sha256(a.manifest.read_bytes()).hexdigest()==manifest_sha:
    acceptance=a.scenario==['acceptance']
    record_vehicle_check(a.manifest,a.manifest.parent/'tests/acceptance.json' if acceptance else evidence,
                         'acceptance' if acceptance else 'pilot',diagnostic)
print('NATIVE_VEHICLE_RESULT '+result['status'],flush=True)
raise SystemExit(0 if result['status']=='passed' else 1)
