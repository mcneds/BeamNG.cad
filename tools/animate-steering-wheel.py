"""Create an immutable steering appearance revision, preserving all physics."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from steering_visuals import fit
from vehicle_revisions import appearance_meshes,replace_appearance

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt',type=Path);parser.add_argument('--component',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();project=json.loads((args.receipt.parent/'project.snapshot.json').read_text())
    component=next((c for c in project['Components'] if c['Id']==args.component),None)
    if component is None:raise ValueError('Component ID is absent from the completed build')
    component['SteeringAppearance']=fit(appearance_meshes(component)[0])
    project['LastBuildReceipt']=str(args.receipt.resolve())
    print(json.dumps(component['SteeringAppearance']),flush=True)
    result=replace_appearance(project,[args.component],args.output)
    print(json.dumps(dict(receipt=str(args.output/'static_frame_build.json'),physics_sha256=result['physics_sha256'])),flush=True)

if __name__=='__main__':main()
