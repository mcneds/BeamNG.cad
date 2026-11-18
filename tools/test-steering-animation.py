"""Native steering appearance diagnostic in an exclusively owned Drive profile."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.models import HarnessProject
from frame_harness.vehicle import run_vehicle
from vehicle_revisions import load_baseline
from steering_visual_probe import analyze

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--game',type=Path,required=True)
    a=p.parse_args();_,manifest,_,_=load_baseline(a.manifest.parent/'static_frame_build.json')
    if not any(v.get('steering') for v in manifest.get('rigid_render',{}).values()):raise ValueError('Package has no steering animation contract')
    project=HarnessProject(userpath=a.profile,game=a.game,runs=a.manifest.parent/'tests',startup_timeout=240.)
    sources=[*(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness').rglob('*.py'),*(ROOT/'dependencies/cad-calibration/Test Harness/frame_harness').rglob('*.lua'),ROOT/'beamng.cad/FramePipeline/steering_visual_probe.py']
    implementation={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    manifest_hash=hashlib.sha256(a.manifest.read_bytes()).hexdigest()
    run=run_vehicle(a.manifest,'steering_visual',project=project)
    unchanged=implementation=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources} and manifest_hash==hashlib.sha256(a.manifest.read_bytes()).hexdigest()
    (Path(run['directory'])/'steering-verifier.json').write_text(json.dumps(dict(implementation=implementation,manifest_sha256=manifest_hash,unchanged=unchanged),indent=2))
    if run['recording_status']!='completed':print(json.dumps(run));return 1
    result=analyze(run['directory'],manifest)
    if not unchanged:result['status']='failed';result['errors'].append('Verifier or manifest changed during recording')
    result['vehicle_result']=dict(status=run['status'],reason=run.get('reason'),recording_status=run['recording_status'],
                                 broken_beams=run['metrics'].get('broken_beams'),peak_relative_node_speed_m_s=run['metrics'].get('peak_relative_node_speed_m_s'))
    result['qualification_status']='diagnostic_only'
    (Path(run['directory'])/'steering-animation-result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    return 0 if result['status']=='passed' and run['checks'].get('no_broken_beams') else 1

if __name__=='__main__':raise SystemExit(main())
