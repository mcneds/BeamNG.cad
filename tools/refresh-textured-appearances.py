"""Repackage captured texture-bearing CAD appearances without regenerating physics."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline,replace_appearance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();receipt=args.receipt.resolve()
    _,_,_,before=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_text(encoding='utf-8'))
    project['LastBuildReceipt']=str(receipt)
    owners=[]
    for component in project['Components']:
        directory=component.get('AppearanceDirectory') or component.get('GeometryDirectory')
        if not directory:continue
        geometry=json.loads((Path(directory)/'geometry.json').read_text(encoding='utf-8-sig'))
        if any(g['Appearance'].get('TextureFile') for mesh in geometry['Meshes'] for g in mesh.get('AppearanceGroups',[])):
            owners.append(component['Id']);print('Texture appearance: '+component['Name'],flush=True)
    if not owners:raise ValueError('No captured texture-bearing component appearances')
    replace_appearance(project,owners,args.output)
    _,manifest,contents,after=load_baseline(args.output/'static_frame_build.json')
    if before['sha256']!=after['sha256']:raise AssertionError('Appearance update changed physics')
    prefix='vehicles/'+manifest['model']+'/'
    materials=json.loads(contents[prefix+'main.materials.json'])
    maps={s['baseColorMap'].lstrip('/') for m in materials.values() for s in m.get('Stages',[]) if s.get('baseColorMap')}
    for name in maps:
        if name not in contents:raise ValueError('Missing packaged colour texture: '+name)
    audit=dict(components=owners,textures=sorted(maps),physics_sha256=after['sha256'],physics_unchanged=True,
               mapping='100 mm box projection for legacy captures without UVs; SolidWorks mapping scale/orientation is not reproduced')
    (args.output/'texture-export-audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':main()
