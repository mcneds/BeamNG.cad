"""Read-only instantaneous mobility audit of an Inspect-SuspensionMates snapshot.

This analyses the entire connected mechanism, not a sum of pairwise joint DOFs.
Only the explicitly supported, solved mate primitives are accepted. No native
mate is suppressed; omission studies operate solely on the saved snapshot.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.linalg import null_space


def cross(p):
    x,y,z=p
    return np.array([[0,-z,y],[z,0,-x],[-y,x,0]])


def kind(e):
    k=e['kind']
    if k.startswith('feature:RefPoint:') or e['reference_type'] in (11,25):return 'point'
    if e['reference_type'] in (10,24):return 'line'
    if k.startswith('feature:RefAxis:'):return 'line'
    if k.startswith('feature:RefPlane:'):return 'plane'
    return k


def analyze(data,omitted=()):
    mates=[m for m in data['mates'] if not m['suppressed'] and m['name'] not in omitted]
    referenced={e['component'] for m in mates for e in m['entities']}
    moving=[c['name'] for c in data['components'] if c['name'] in referenced and not c['is_fixed']]
    centers={n:np.mean([e['parameters'][:3] for m in mates for e in m['entities'] if e['component']==n],axis=0) for n in moving}
    rows=[];labels=[]
    for m in mates:
        if m['error'] and not m['warning']:raise ValueError('Unsolved mate: '+m['name'])
        a,b=m['entities'];ka,kb=kind(a),kind(b)
        pa,pb=np.array(a['parameters'][:3]),np.array(b['parameters'][:3])
        u,v=np.array(a['parameters'][3:6]),np.array(b['parameters'][3:6])
        t=m['type'];p=(pa+pb)/2;blocks=[]
        if t=='swMateCOINCIDENT' and ka==kb=='point':
            if np.linalg.norm(pa-pb)>1e-6:raise ValueError('Unsolved point mate')
            blocks=[(np.eye(3),False)]
        elif t=='swMateCOINCIDENT' and {ka,kb}=={'point','line'}:
            p=pa if ka=='point' else pb
            origin=pb if ka=='point' else pa
            direction=v if kb=='line' else u
            direction=direction/np.linalg.norm(direction)
            if np.linalg.norm(np.cross(p-origin,direction))>1e-6:raise ValueError('Point is off axis: '+m['name'])
            blocks=[(null_space(direction[None,:]).T,False)]
        elif t=='swMatePARALLEL' and ka==kb=='line':
            u=u/np.linalg.norm(u);v=v/np.linalg.norm(v)
            if np.linalg.norm(np.cross(u,v))>1e-6:raise ValueError('Nonparallel lines')
            blocks=[(null_space(u[None,:]).T,True)]
        elif t=='swMateCONCENTRIC' and {ka,kb}<={'line','circle','cylinder'}:
            u=u/np.linalg.norm(u);v=v/np.linalg.norm(v)
            if np.linalg.norm(np.cross(u,v))>1e-6 or np.linalg.norm(np.cross(pa-pb,u))>1e-6:raise ValueError('Unsolved concentric mate')
            basis=null_space(u[None,:]).T;blocks=[(basis,False),(basis,True)]
            if m['settings']['lock_rotation']:blocks.append((u[None,:],True))
        elif t in ('swMatePARALLEL','swMateCOINCIDENT') and {ka,kb}<={'plane','circle'}:
            u=u/np.linalg.norm(u);v=v/np.linalg.norm(v)
            if np.linalg.norm(np.cross(u,v))>1e-6:raise ValueError('Nonparallel planes')
            blocks=[(null_space(u[None,:]).T,True)]
            if t=='swMateCOINCIDENT':
                if abs((pa-pb)@u)>1e-6:raise ValueError('Separated coincident planes')
                # A circle lies in the plane; evaluate its centre's normal velocity.
                p=pa if ka=='circle' else pb if kb=='circle' else p
                blocks.append((u[None,:],False))
        else:raise ValueError('Unsupported mate: '+m['name']+' '+ka+'/'+kb)
        for basis,rotation in blocks:
            block=np.zeros((len(basis),6*len(moving)))
            for sign,e in [(1,a),(-1,b)]:
                n=e['component']
                if n not in moving:continue
                local=np.column_stack((np.zeros((3,3)),np.eye(3))) if rotation else np.column_stack((np.eye(3),-cross(p-centers[n])))
                i=6*moving.index(n);block[:,i:i+6]+=sign*basis@local
            rows.extend(block);labels.extend([m['name']]*len(block))
    matrix=np.array(rows);free=null_space(matrix,rcond=1e-8)
    mobility={}
    for i,n in enumerate(moving):
        local=free[6*i:6*i+6]
        mobility[n]=dict(local_motion_rank=int(np.linalg.matrix_rank(local,tol=1e-7)),rotation_rank=int(np.linalg.matrix_rank(local[3:],tol=1e-7)))
    return dict(omitted=list(omitted),mechanism_dof=free.shape[1],components=mobility,constraint_residual=float(np.linalg.norm(matrix@free)),singular_values=np.linalg.svd(matrix,compute_uv=False).tolist())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('snapshot',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=json.loads(args.snapshot.read_text())
    if not data['read_only_state_unchanged']:raise ValueError('Snapshot changed while being read')
    report=dict(scope='Instantaneous linearized mobility; not a native drag or finite-travel verification',baseline=analyze(data),without_parallel4=analyze(data,['Parallel4']),without_parallel1=analyze(data,['Parallel1']))
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    for name,case in report.items():
        if not isinstance(case,dict):continue
        print(name,case['mechanism_dof'],'DOF')
        for c,m in case['components'].items():print(' ',c,m)
