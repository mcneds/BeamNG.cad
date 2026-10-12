"""Audit local CAD wheel-angle compliance; not a material or driving prediction."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline
from frame_harness.build import node_table
from rigid_bracing import gradient
from motion_objective import front_columns


def audit(receipt,positions=None):
    _,manifest,files,_=load_baseline(receipt)
    parts=json.loads(next(v for k,v in files.items() if k.endswith('.jbeam')))
    if len(parts)!=1:raise ValueError('Expected one assembled part')
    part=next(iter(parts.values()));nodes=node_table(part)
    if positions is not None:
        if not set(nodes)<=set(positions):raise ValueError('Incomplete recorded pose')
        for name,node in nodes.items():
            point=np.asarray(positions[name],float)
            if point.shape!=(3,) or not np.isfinite(point).all():raise ValueError('Invalid recorded point')
            node['position']=point
    groups=[set(manifest['chassis_nodes'])]
    for owner,role in manifest['component_roles'].items():
        if role in ('fl_upper_wishbone','fl_lower_wishbone','fr_upper_wishbone','fr_lower_wishbone','fl_upright','fr_upright'):
            groups.append(set(manifest['mass_allocations'][owner]))
    names=sorted(set.union(*groups));index={n:i for i,n in enumerate(names)}
    mass=np.array([nodes[n]['options']['nodeWeight'] for n in names]);entries=[]
    ties=[{manifest['wheels'][c]['hardpoint_nodes'][k] for k in ('tie_inner','tie_outer')} for c in ('FL','FR')]
    for section in ('beams','hydros','torsionbars'):
        defaults={}
        for row in part.get(section,[])[1:]:
            if isinstance(row,dict):defaults.update(row);continue
            ids=row[:4] if section=='torsionbars' else row[:2]
            if not any(set(ids)<=group for group in (ties if section=='hydros' else groups)):continue
            o=defaults|row[-1];xyz=np.array([nodes[n]['position'] for n in ids])
            if section=='torsionbars':vectors=gradient(xyz);k=o['spring']
            else:
                if o.get('beamType','|NORMAL')!='|NORMAL':raise ValueError('Non-rigid beam in selected mechanism')
                v=xyz[1]-xyz[0];v/=np.linalg.norm(v);vectors=np.array([-v,v]);k=o['beamSpring']
            col=np.zeros((len(names),3))
            for n,v in zip(ids,vectors):col[index[n]]+=v/np.sqrt(mass[index[n]])
            entries.append((col.ravel(),k))
    a=np.array([v for v,k in entries]).T;springs=np.array([k for v,k in entries])
    u,s,_=np.linalg.svd(a/np.linalg.norm(a,axis=0),full_matrices=False);rank=np.count_nonzero(s>s[0]*1e-6)
    q=u[:,:rank];k=q.T@((a*springs)@a.T)@q
    eigen=np.linalg.eigvalsh(k)
    if positions is None:
        g,reference=front_columns(part,names,manifest);g=q.T@g
        response=np.linalg.solve(k,g)
        angle_response={c:float(np.linalg.norm(response[:,i])) for i,c in enumerate(reference['channels'])}
    else:
        reference=None;angle_response=None
    return dict(scope=__doc__,receipt=str(receipt),receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        nodes=len(names),constraints=len(entries),rank=int(rank),nullity=len(names)*3-int(rank),
        minimum_internal_frequency_hz=float(np.sqrt(eigen[0])/(2*np.pi)),maximum_internal_frequency_hz=float(np.sqrt(eigen[-1])/(2*np.pi)),
        angle_response_norm=angle_response,
        units='radians per unit mass-normalized force; local zero-frequency tangent, tires and attachments excluded',reference=reference,
        pose_scope='Positive elastic constraint tangent at recorded coordinates; prestress, damping, tires and external attachments excluded. Not the complete native modal spectrum.' if positions is not None else 'Authored CAD pose')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.receipt);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
