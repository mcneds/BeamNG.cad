"""Coupled tangent diagnostic, including BeamNG-generated pressure wheel beams."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import eigsh
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import gradient
p=argparse.ArgumentParser();p.add_argument('compiled',type=Path);a=p.parse_args();d=json.loads(a.compiled.read_text())
nodes=d['actual_nodes'];bycid={n['cid']:name for name,n in nodes.items()};free={name:i for i,(name,n) in enumerate((k,v) for k,v in nodes.items() if not v['fixed'])}
rows=[];cols=[];values=[];springs=[];dampers=[];filtered=[]
def column(names,vectors,k,c):
    index=len(springs);springs.append(k);dampers.append(c)
    for name,vector in zip(names,vectors):
        if name not in free:continue
        for axis,value in enumerate(vector):rows.append(3*free[name]+axis);cols.append(index);values.append(value/np.sqrt(nodes[name]['mass_kg']))
for beam in d['beams']:
    names=[bycid[beam[k]] for k in ('a','b')];delta=np.array(nodes[names[1]]['position'])-nodes[names[0]]['position'];delta/=np.linalg.norm(delta)
    column(names,[-delta,delta],beam['spring'],beam['damp'])
    filtered.append(bool(beam.get('damp_cutoff_hz')))
for t in d['torsionbars']:
    column(t[:4],gradient(np.array([nodes[n]['position'] for n in t[:4]])),t[4]['spring'],t[4]['damp'])
    filtered.append(False)
A=coo_matrix((values,(rows,cols)),shape=(3*len(free),len(springs))).tocsr();dt=.0005
K=A.multiply(springs)@A.T
for label,coefficients in [('all_damping_as_instantaneous',dampers),('unfiltered_damping_only',np.where(filtered,0,dampers))]:
    C=A.multiply(coefficients)@A.T;step=dt*dt*K+2*dt*C
    eigen,modes=eigsh(step,k=3,which='LA');v=modes[:,-1].reshape(-1,3);order=np.argsort(-np.linalg.norm(v,axis=1))[:16];names=list(free)
    print(label,'step eigenvalues',eigen,'limit 4; estimate excludes pressure, prestress and filter dynamics')
    print('dominant nodes',[(names[i],round(float(np.linalg.norm(v[i])),4)) for i in order])
print('frequency',float(np.sqrt(eigsh(K,k=1,which='LA',return_eigenvectors=False)[0])/(2*np.pi)))
