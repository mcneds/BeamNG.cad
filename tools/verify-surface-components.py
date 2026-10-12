"""Isolated weighted sheet and zero-mass skin fixture using an archived frame project."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from prepare_frame import write_stl


def sheet(root,name,points,density):
    folder=root/name;folder.mkdir()
    points=np.asarray(points);triangles=points[[[0,1,2],[0,2,3]]]
    area=float(np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2)
    cad=triangles[:,:,[0,2,1]].copy();cad[:,:,2]*=-1;write_stl(folder/'body.stl',cad)
    (folder/'geometry.json').write_text(json.dumps({'Meshes':[dict(Id=name,Body=name,File='body.stl',BodyKind='surface',SurfaceAreaM2=area,DensityKgM3=density)]}))
    return folder


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--foundation',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',type=Path,required=True);parser.add_argument('--cgal');parser.add_argument('--game');parser.add_argument('--profile');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);project=json.loads(args.foundation.read_text())
    folder=sheet(args.output,'surface_panel',[[.55,.325,.475],[.55,.975,.475],[.55,.975,.925],[.55,.325,.925]],2700.)
    panel=next(c for c in project['Components'] if c['Id']=='panel');panel.update(GeometryDirectory=str(folder),BodyIds=['surface_panel'],Thickness=.003,SurfaceMassMode='thickness',MvpRole='panel')
    skin=sheet(args.output,'weightless_skin',[[-.14,1.40,.705],[.14,1.40,.705],[.14,1.70,.705],[-.14,1.70,.705]],None)
    from component_representation import acknowledgement
    visual=dict(Id='skin',Name='Zero mass surface skin',MvpRole='panel',Template='panel',GeometryDirectory=str(skin),BodyIds=['weightless_skin'],SurfaceMassMode='ignore',VisualParentId='accessory',Representation='visual_only',MassPolicy='exclude')
    # This harness explicitly requests a zero-mass fixture; production projects
    # acknowledge that choice through the component properties UI.
    visual['MassAcknowledgement']=acknowledgement(visual);project['Components'].append(visual)
    path=args.output/'project.json';path.write_text(json.dumps(project,indent=2))
    subprocess.run([sys.executable,str(args.worker),'build','--project',str(path),'--output',str(args.output/'build'),'--cgal',args.cgal or ''],check=True)
    manifest=json.loads((args.output/'build/manifest.json').read_text());report=manifest['component_reports']['skin']
    assert report['nodes']==0 and report['mass']['actual_mass_kg']==0
    assert abs(manifest['component_reports']['panel']['mass']['actual_mass_kg']-.65*.45*.003*2700)<1e-9
    if args.game:
        subprocess.run([sys.executable,str(args.worker),'verify','--project',str(path),'--manifest',str(args.output/'build/manifest.json'),'--game',args.game,'--profile',args.profile],check=True)


if __name__=='__main__':main()
