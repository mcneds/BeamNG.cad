"""Read-only test of exact-moment mass redistribution under a stiffness cap."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.linalg import eigh
from scipy.optimize import minimize
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from frame_harness.calibration import load_part
from frame_harness.build import node_table,beam_table
from frame_harness.projection import axial_columns,modal_frequencies
p=argparse.ArgumentParser();p.add_argument('study',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
r=json.loads((a.study/'solidworks-assigned/report.json').read_text());config=json.loads((a.study/'reference.json').read_text())
part=load_part(a.study/'solidworks-assigned/mochi.jbeam');nodes=node_table(part);names=list(nodes);edges=beam_table(part)
mass=np.array([nodes[n]['mass'] for n in names]);xyz=np.array([nodes[n]['position'] for n in names]);ends=np.array([[names.index(b['a']),names.index(b['b'])] for b in edges])
columns,_,_=axial_columns(xyz,ends);springs=np.array([b['spring'] for b in edges]);limit=(2*np.pi*config['frequency_limit_hz'])**2
x,y,z=((xyz-mass@xyz/mass.sum())/np.linalg.norm(np.ptp(xyz,axis=0))).T
features=np.array([np.ones(len(mass)),x,y,z,y*y+z*z,x*x+z*z,x*x+y*y,-x*y,-x*z,-y*z]);target=features@mass
weighted=columns/np.sqrt(np.repeat(mass,3))[:,None]
matrix=(weighted*(springs*1.5))@weighted.T/limit
def objective(values):
    eigen,v=eigh(matrix-np.diag(np.repeat(values/mass,3)),subset_by_value=(0,np.inf),check_finite=False)
    value=float(eigen@eigen)+1e-7*float(np.sum((values/mass-1)**2))
    grad=-2*np.sum(v*v*eigen,axis=1).reshape(-1,3).sum(axis=1)/mass+2e-7*(values/mass-1)/mass
    return value,grad
fit=minimize(objective,mass,jac=True,method='SLSQP',bounds=[(max(.05,float(m*.1)),None) for m in mass],
             constraints=[dict(type='eq',fun=lambda m:features@m-target,jac=lambda m:features)],options=dict(maxiter=500,ftol=1e-12))
result=dict(success=bool(fit.success),message=str(fit.message),objective=float(fit.fun),before_frequency_hz=float(modal_frequencies(columns,mass,springs*1.5)[-1]),
            after_frequency_hz=float(modal_frequencies(columns,fit.x,springs*1.5)[-1]),moment_error=float(max(abs(features@fit.x-target))),
            masses=dict(zip(names,fit.x.tolist())),original_masses=dict(zip(names,mass.tolist())))
a.output.write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if not isinstance(v,dict)},flush=True)
