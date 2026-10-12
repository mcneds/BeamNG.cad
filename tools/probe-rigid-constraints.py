"""Read-only comparison of broad and complete angular constraint candidates."""
import argparse,itertools,json,sys
from pathlib import Path
import numpy as np
from scipy.optimize import nnls
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import reinforce,gradient
from frame_harness.projection import axial_columns,modal_frequencies
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args();m=json.loads(a.manifest.read_text())
for owner in ('fl_lower_wishbone','fl_upper_wishbone','fl_upright','rl_trailing_arm'):
 if owner not in m['mass_allocations']:continue
 allocation=m['mass_allocations'][owner];names=list(allocation);xyz=np.array([m['nodes'][n]['position'] for n in names]);masses=np.array(list(allocation.values()))
 edges=list(itertools.combinations(range(len(names)),2));spring,damp,bars=reinforce(xyz,edges,masses)
 axial,_,_=axial_columns(xyz,edges);vectors=[];minimum=np.linalg.norm(np.ptp(xyz,axis=0))*.04
 for quartet in itertools.combinations(range(len(xyz)),4):
  candidates=[]
  for ids in itertools.permutations(quartet):
   f,s,t,d=ids;u=xyz[f]-xyz[s];v=xyz[t]-xyz[s];w=xyz[d]-xyz[t]
   lu,lv,lw=map(np.linalg.norm,(u,v,w))
   if min(lu,lv,lw)<1e-7:continue
   a=np.linalg.norm(np.cross(u,v))/(lu*lv);b=np.linalg.norm(np.cross(w,v))/(lw*lv)
   if min(lu*a,lw*b)>=minimum and min(a,b)>=.4:candidates.append((min(a,b),ids))
  if candidates:
   _,ids=max(candidates);g=np.zeros_like(xyz);g[list(ids)]=gradient(xyz[list(ids)]);vectors.append(g.ravel())
 A=np.column_stack((axial,np.array(vectors).T));W=A/np.sqrt(np.repeat(masses,3))[:,None];inverse=np.sum(W*W,axis=0)
 U,S,_=np.linalg.svd(W,full_matrices=False);U=U[:,S>S[0]*1e-6];target=U@U.T;unit=W/np.sqrt(inverse)
 D=(unit[:,None,:]*unit[None,:,:]).reshape((len(W)**2,-1));coeff,_=nnls(D,target.ravel(),maxiter=20*D.shape[1])
 k=np.maximum(coeff,1e-3)*(2*np.pi*400)**2/inverse
 k*=min(1,(2*np.pi*400)**2/np.linalg.eigvalsh((W*k)@W.T)[-1]);frequencies=modal_frequencies(A,masses,k)
 print(owner,'candidates',len(vectors),'active angular',sum(coeff[len(edges):]>.001),'min/max Hz',frequencies[6],frequencies[-1],flush=True)
