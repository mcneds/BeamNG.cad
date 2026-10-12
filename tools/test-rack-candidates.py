"""Compare isolated rack candidates in one owned Drive session; no installation."""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
HARNESS=ROOT/'dependencies/cad-calibration/Test Harness'
sys.path[:0]=[str(HARNESS),str(ROOT/'beamng.cad/FramePipeline')]
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.vehicle import intake,run_vehicle
from frame_harness.build import write_json
from verification_receipts import record_vehicle_check


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests',nargs='+',type=Path)
    parser.add_argument('--profile',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new output path')
    paths=[p.resolve() for p in args.manifests]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:intake(p)
    files=[p for p in (HARNESS/'frame_harness').rglob('*') if p.suffix in ('.py','.lua')]
    implementation={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report=dict(status='running',scope='Targeted pilots, not full acceptance',builds=[])
    write_json(args.output,report)
    project=HarnessProject(userpath=args.profile,startup_timeout=420,runs=paths[0].parent/'tests')
    with DriveSession(project,'vehicle') as session:
        for p in paths:
            project.runs=p.parent/'tests';runs=[]
            record=dict(manifest=str(p),manifest_sha256=hashes[str(p)],runs=runs)
            report['builds'].append(record)
            write_json(args.output,report)
            for scenario in ('settle','acceleration'):
                runs.append(run_vehicle(p,scenario,project=project,session=session))
                write_json(args.output,report)
                if runs[-1]['status']!='passed':break
            record['status']='passed' if len(runs)==2 and all(r['status']=='passed' for r in runs) else 'failed'
    unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest()==implementation[str(p)] for p in files)
    for record in report['builds']:
        p=Path(record['manifest']);record['verifier_unchanged']=unchanged
        record['manifest_unchanged']=hashlib.sha256(p.read_bytes()).hexdigest()==record['manifest_sha256']
        record['implementation']=implementation
        if not unchanged or not record['manifest_unchanged']:record['status']='failed'
        evidence=p.parent/'rack-pilot-verification.json';write_json(evidence,record)
        if unchanged and record['manifest_unchanged']:record_vehicle_check(p,evidence)
    report['status']='passed' if all(r['status']=='passed' for r in report['builds']) else 'failed'
    write_json(args.output,report)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
