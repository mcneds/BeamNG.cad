"""Attach native evidence without confusing generation, recording and qualification."""
import json
from collections import Counter
from pathlib import Path
from build_static_frame import completed_build,digest
import components as c


def record_vehicle_check(manifest_path,evidence_path,kind='pilot',diagnostic=None):
    if kind not in ('pilot','acceptance'):raise ValueError('Unknown verification kind')
    manifest_path=Path(manifest_path).resolve();evidence_path=Path(evidence_path).resolve()
    result=json.loads(evidence_path.read_text(encoding='utf-8'))
    if result.get('manifest_sha256')!=digest(manifest_path):raise ValueError('Verification belongs to a different manifest')
    if not result.get('verifier_unchanged'):raise ValueError('Verification implementation changed during recording')
    runs=result.get('runs',[])
    diagnostic=diagnostic or result.get('diagnostic') or next((r.get('diagnostic') for r in runs if r.get('diagnostic')),None)
    passed=result.get('status')=='passed'
    if passed and (not runs or any(r.get('status')!='passed' or r.get('recording_status')!='completed' for r in runs)):
        raise ValueError('Passing verification lacks passing recordings')
    if kind=='acceptance' and passed:
        from frame_harness.vehicle import SCENARIOS
        if (result.get('required_runs')!=3*len(SCENARIOS) or len(runs)!=result.get('completed_runs')
                or Counter(r.get('scenario') for r in runs)!={name:3 for name in SCENARIOS}):
            raise ValueError('Acceptance repeat set is incomplete')
        if (any(not r.get('directory') for r in runs)
                or len({Path(r['directory']).resolve() for r in runs})!=len(runs)):
            raise ValueError('Acceptance requires independent recording directories')
    receipt=manifest_path.parent/'static_frame_build.json';record,_=completed_build(receipt)
    evidence=dict(kind=kind,status=result.get('status'),path=str(evidence_path),sha256=digest(evidence_path),
                  manifest_sha256=result['manifest_sha256'],recordings=len(runs),diagnostic=diagnostic)
    if diagnostic:
        record['latest_diagnostic']=evidence
    else:
        record['latest_native_verification']=evidence
        record['recording_status']=result.get('recording_status','completed' if runs and all(r.get('recording_status')=='completed' for r in runs) else 'incomplete')
        if not passed:record['qualification_status']='failed'
        elif kind=='acceptance':
            record['qualification_status']='template_acceptance_passed'
            record['vehicle_verification_sha256']=evidence['sha256']
        # Passing pilots cannot promote an unqualified or previously failed build.
    c.write(receipt,record)
    return record
