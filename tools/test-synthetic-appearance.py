"""Pair native scenarios across an appearance-only change with sealed physics."""
import argparse,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];HARNESS=ROOT/'dependencies/cad-calibration/Test Harness'
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(HARNESS)]
from vehicle_revisions import load_baseline
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.vehicle import run_vehicle
from frame_harness.build import write_json


def compiled_physics(record):
    # Instantaneous length depends on startup scheduling; rest length and every
    # actual spring/damper are retained. Visual controller counts are excluded.
    return {key:([{k:v for k,v in beam.items() if k!='length'} for beam in record[key]] if key=='beams' else record[key])
            for key in ('actual_nodes','beams','torsionbars','device_graph','tire_physics','mass_kg','node_count','fixed_nodes')}


def compare(a,b,path='compiled'):
    if isinstance(a,dict) and isinstance(b,dict):
        if a.keys()!=b.keys():raise ValueError('Compiled keys differ: '+path)
        for key in a:compare(a[key],b[key],path+'/'+key)
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):raise ValueError('Compiled lengths differ: '+path)
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+'/'+str(i))
    elif isinstance(a,(float,int)) and isinstance(b,(float,int)):
        if not math.isfinite(a) or not math.isfinite(b) or not math.isclose(a,b,rel_tol=1e-5,abs_tol=1e-7):
            raise ValueError('Compiled numeric property differs: '+path)
    elif a!=b:raise ValueError('Compiled value differs: '+path)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('appearance',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--profile',type=Path,default=Path('H:/BeamNGCadHarness/synthetic-mvp-20261007'))
    p.add_argument('--game',type=Path,default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'));a=p.parse_args()
    if a.output.exists():raise FileExistsError('Use a fresh comparison evidence path')
    before=load_baseline(a.baseline.parent/'static_frame_build.json');after=load_baseline(a.appearance.parent/'static_frame_build.json')
    if before[3]!=after[3]:raise ValueError('Appearance candidate changed sealed physics')
    if before[1]['appearance_sha256']==after[1]['appearance_sha256']:raise ValueError('Appearance did not change')
    hashes=lambda:{str(f.relative_to(HARNESS)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py','.lua')}
    manifests={'baseline':a.baseline,'appearance':a.appearance}
    manifest_hashes={label:hashlib.sha256(path.read_bytes()).hexdigest() for label,path in manifests.items()}
    implementation=hashes();result=dict(status='running',physics_sha256=before[3]['sha256'],runs=[],comparisons=[],manifest_hashes=manifest_hashes)
    project=HarnessProject(game=a.game,userpath=a.profile,runs=a.output.parent)
    try:
        with DriveSession(project,'vehicle') as session:
            for scenario in ('settle','acceleration','braking'):
                pair=[]
                for label,manifest in (('baseline',a.baseline),('appearance',a.appearance)):
                    run=run_vehicle(manifest,scenario,project=project,session=session)
                    result['runs'].append(dict(candidate=label,**run));write_json(a.output,result)
                    if run['status']!='passed':raise ValueError(label+' failed '+scenario)
                    pair.append(json.loads((Path(run['directory'])/'compiled.json').read_text()))
                compare(compiled_physics(pair[0]),compiled_physics(pair[1]))
                result['comparisons'].append(dict(scenario=scenario,compiled_physics_equivalent=True))
        if hashes()!=implementation:raise ValueError('Verifier changed during paired runs')
        if any(hashlib.sha256(path.read_bytes()).hexdigest()!=manifest_hashes[label] for label,path in manifests.items()):
            raise ValueError('Manifest changed during paired runs')
        result['status']='passed'
    except (Exception,KeyboardInterrupt) as error:
        result.update(status='failed',reason=str(error) or 'Interrupted')
    if result['status']=='passed':
        from frame_harness.component_tests import compact_success
        for run in result['runs']:compact_success(run['directory'])
    unchanged=hashes()==implementation
    result.update(implementation=implementation,verifier_unchanged=unchanged);write_json(a.output,result)
    from verification_receipts import record_vehicle_check
    for label,manifest in manifests.items():
        runs=[r for r in result['runs'] if r['candidate']==label]
        if not runs or not unchanged or hashlib.sha256(manifest.read_bytes()).hexdigest()!=manifest_hashes[label]:continue
        evidence=a.output.with_name(a.output.stem+'-'+label+'.json')
        write_json(evidence,dict(status='passed' if all(r['status']=='passed' for r in runs) else 'failed',
                                runs=runs,manifest_sha256=manifest_hashes[label],verifier_unchanged=True,
                                comparison_evidence=str(a.output)))
        # A later failed baseline run must withdraw its former qualification.
        # Successful paired pilots cannot promote a newly revised vehicle.
        record_vehicle_check(manifest,evidence)
    print('NATIVE_APPEARANCE_PAIR '+result['status'],flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
