"""Linear discrete-time stability diagnostic for each rigid mechanism body."""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
from frame_harness.build import node_table,beam_table
from frame_harness.projection import axial_columns
from rigid_bracing import gradient

p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args();m=json.loads(a.manifest.read_text())
part=next(iter(json.loads((a.manifest.parent/m['vehicle_directory']/m['main_jbeam']).read_text()).values()));nodes=node_table(part)
for owner in m['component_reports']:
    role=m.get('component_roles',{}).get(owner) or owner
    if not any(token in role for token in ('wishbone','upright','trailing_arm')):continue
    names=[n for n,v in m['nodes'].items() if v['component']==owner];indices={n:i for i,n in enumerate(names)}
    xyz=np.array([nodes[n]['position'] for n in names]);mass=np.array([nodes[n]['options']['nodeWeight'] for n in names]);cols=[];ks=[];cs=[]
    for b in beam_table(part):
        if b['a'] in indices and b['b'] in indices:
            i,j=indices[b['a']],indices[b['b']];u=xyz[j]-xyz[i];u/=np.linalg.norm(u);col=np.zeros_like(xyz);col[i]=-u;col[j]=u
            cols.append(col.ravel());ks.append(b['spring']);cs.append(b['damp'])
    for row in part.get('torsionbars',[])[1:]:
        if all(n in indices for n in row[:4]):
            ids=[indices[n] for n in row[:4]];col=np.zeros_like(xyz);col[ids]=gradient(xyz[ids]);cols.append(col.ravel());ks.append(row[4]['spring']);cs.append(row[4]['damp'])
    a0=np.array(cols).T/np.repeat(np.sqrt(mass),3)[:,None];k=(a0*ks)@a0.T;d=(a0*cs)@a0.T;dt=.0005
    print(json.dumps(dict(component=owner,role=role,frequency_hz=float(np.sqrt(max(np.linalg.eigvalsh(k)))/(2*np.pi)),
        step_eigenvalue=float(max(np.linalg.eigvalsh(dt*dt*k+2*dt*d))),limit=4.,min_mass_kg=float(min(mass)))))
