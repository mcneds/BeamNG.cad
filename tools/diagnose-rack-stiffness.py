"""Linear rack compliance with its housing mounting sites held fixed.

This offline diagnostic assembles exported axial, angular and transverse rail
springs. It does not replace nonlinear native vehicle qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import gradient


def diagnose(manifest_path, include_mount_compliance=False):
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    path=manifest_path.parent/manifest['vehicle_directory']/manifest['main_jbeam']
    part=json.loads(path.read_text(encoding='utf-8'))[manifest['main_part']]
    rack=manifest['steering_contract'];names=rack['housing_nodes']+rack['slider_nodes']
    external=set()
    if include_mount_compliance:
        housing=set(rack['housing_nodes']);rack_nodes=set(names)
        for section,count in [('beams',2),('torsionbars',4)]:
            for row in part.get(section,[])[1:]:
                if isinstance(row,list) and housing.intersection(row[:count]):
                    external.update(set(row[:count])-rack_nodes)
        names=names+sorted(external)
    index={name:i for i,name in enumerate(names)}
    positions={n:np.array(manifest['nodes'][n]['position']) for n in names}
    K=np.zeros((3*len(names),3*len(names)))
    def add(ids,vectors,spring):
        column=np.zeros((len(names),3))
        for name,vector in zip(ids,vectors):column[index[name]]+=vector
        nonlocal K
        K+=spring*np.outer(column.ravel(),column.ravel())
    for section in ('beams','hydros'):
        defaults={}
        for row in part.get(section,[])[1:]:
            if isinstance(row,dict):defaults.update(row);continue
            a,b=row[:2]
            if a not in index or b not in index:continue
            options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
            delta=positions[b]-positions[a];delta/=np.linalg.norm(delta)
            add([a,b],[-delta,delta],options.get('beamSpring',0.))
    for row in part.get('torsionbars',[])[1:]:
        if isinstance(row,list) and all(n in index for n in row[:4]):
            add(row[:4],gradient(np.array([positions[n] for n in row[:4]])),row[4]['spring'])
    for name,rail,options in part['slidenodes'][1:]:
        if name not in index:continue
        a,b=part['rails'][rail]['links:'];d=positions[b]-positions[a]
        t=(positions[name]-positions[a])@d/(d@d);axis=d/np.linalg.norm(d)
        # Inside the stroke only transverse rail directions resist motion.
        projection=np.eye(3)-np.outer(axis,axis)
        for direction in projection:
            add([name,a,b],[direction,-(1-t)*direction,-t*direction],options['spring'])
    fixed=sorted(external) if include_mount_compliance else [n for n in rack['housing_nodes'] if '_mount_' in n]
    free=[3*i+axis for i,name in enumerate(names) if name not in fixed for axis in range(3)]
    reduced=K[np.ix_(free,free)];eigen=np.linalg.eigvalsh(reduced)
    if eigen[0]<=1e-6:raise ValueError('Isolated rack has an unconstrained mode')
    axis=np.array(rack['axis']);cases={}
    loads=[('common',axis,1),('opposed',axis,-1),
           ('common_vertical',np.array([0.,0,1.]),1),('opposed_vertical',np.array([0.,0,1.]),-1),
           ('common_fore_aft',np.array([0.,1.,0]),1),('opposed_fore_aft',np.array([0.,1.,0]),-1)]
    for label,direction,sign in loads:
        force=np.zeros((len(names),3));force[index['FL_tie_inner']]=direction*100
        force[index['FR_tie_inner']]=direction*100*sign
        motion=np.zeros(3*len(names));motion[free]=np.linalg.solve(reduced,force.ravel()[free]);motion=motion.reshape(-1,3)
        displacement=[float(motion[index[c+'_tie_inner']]@axis) for c in ('FL','FR')]
        cases[label]=dict(endpoint_axial_m=displacement,mean_axial_m=float(np.mean(displacement)))
    return dict(scope=__doc__,boundary='external housing supports fixed' if include_mount_compliance else 'housing mount nodes fixed',
                manifest=str(manifest_path.resolve()),fixed_mounts=fixed,
                stiffness_eigenvalues_n_m=[float(eigen[0]),float(eigen[-1])],cases=cases,
                hashes={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (manifest_path,path)})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    p.add_argument('--include-mount-compliance',action='store_true',help='Hold surrounding supports, retaining housing mount compliance; excludes chassis flex')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=diagnose(a.manifest,a.include_mount_compliance)
    a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report['cases'],indent=2))
