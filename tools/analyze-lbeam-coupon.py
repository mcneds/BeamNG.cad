"""Compare a prescribed-displacement native coupon with its local force tangent."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def tangent(points,full,parallel_normal=False):
    K=np.zeros((9,9));edges=[(0,1),(1,2),(0,2)];D=[];lengths=[]
    for a,b in edges:
        v=points[b]-points[a];lengths.append(np.linalg.norm(v));v/=np.linalg.norm(v)
        col=np.zeros((3,3));col[a]=-v;col[b]=v;D.append(col.ravel())
    D=np.array(D).T
    for i in (range(3) if full or parallel_normal else range(2)):K+=10*np.outer(D[:,i],D[:,i])
    J=np.eye(3)
    for i in range(3):
        for j in range(3):
            if i==j:continue
            k=3-i-j;J[i,j]=-(lengths[i]**2+lengths[j]**2-lengths[k]**2)/(2*lengths[i]*lengths[j])
    indices=range(3) if full else [2]
    for i in indices:K+=10000*np.outer(D[:,i],D@J[i])
    return K,J


def analyze(run):
    completion=json.loads((run/'completion.json').read_bytes());job=json.loads((run/'job.json').read_bytes())
    if completion.get('status')!='completed' or completion.get('job_id')!=job['id']:
        raise ValueError('Incomplete or mismatched native coupon')
    rows=np.loadtxt(run/'coupon.csv',delimiter=',',skiprows=1)
    if not np.isfinite(rows).all() or not np.all(np.diff(rows[:,0])>0):raise ValueError('Invalid coupon telemetry')
    config=json.loads((run/'cad_lbeam_coupon.jbeam').read_bytes())['cad_lbeam_coupon'];full=len(config['beams'])==7
    indices=np.array([[2+i*6+j for j in range(3)] for i in range(3)])
    def mean(case,which):
        selected=rows[rows[:,1]==case][-5:]
        if len(selected)!=5:raise ValueError('Incomplete coupon case')
        return selected[:,(indices+which).ravel()].mean(0)
    xyz=mean(0,0).reshape(3,3);K,J=tangent(xyz,full,len(config['beams'])==5);dx=[];df=[]
    for coordinate in range(9):
        dx.append(mean(1+coordinate*2,0)-mean(2+coordinate*2,0))
        df.append(mean(1+coordinate*2,3)-mean(2+coordinate*2,3))
    dx=np.array(dx).T;df=np.array(df).T;predicted=-K@dx
    # Moving the vehicle reference node also moves its world origin. Remove
    # common translation before checking prescribed relative displacements.
    relative=np.eye(9)-np.kron(np.ones((3,3))/3,np.eye(3))
    if np.linalg.matrix_rank(dx)!=9 or not np.allclose(relative@dx,relative*.0002,rtol=.01,atol=1e-7):
        raise ValueError('Prescribed coupon displacements were not recorded correctly')
    error=float(np.linalg.norm(df-predicted)/np.linalg.norm(predicted))
    measured=-df@np.linalg.pinv(dx)
    normal_only=np.zeros((9,9))
    for a,b in ((0,1),(1,2),(0,2)):
        direction=xyz[b]-xyz[a];direction/=np.linalg.norm(direction)
        column=np.zeros((3,3));column[a]=-direction;column[b]=direction
        normal_only+=10010*np.outer(column.ravel(),column.ravel())
    normal_error=float(np.linalg.norm(df+normal_only@dx)/np.linalg.norm(normal_only@dx)) if full else None
    return dict(status='model_agrees' if error<.005 else 'model_rejected',full_triangle=full,relative_force_tangent_error=error,
        normal_only_relative_force_tangent_error=normal_error,
        normal_only_comparison_scope='Alternative diagnostic: whether the three-angle coupon behaves like three ordinary axial springs; never an angular-model acceptance',
        theoretical_asymmetry=float(np.linalg.norm(K-K.T)/np.linalg.norm(K)),
        measured_asymmetry=float(np.linalg.norm(measured-measured.T)/np.linalg.norm(measured)),
        theoretical_eigenvalues=np.linalg.eigvalsh((K+K.T)/2).tolist(),
        measured_symmetric_part_eigenvalues=np.linalg.eigvalsh((measured+measured.T)/2).tolist(),
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('coupon.csv','coupon.json','cad_lbeam_coupon.jbeam','completion.json','job.json','recorder.lua')},
        length_coupling=J.tolist(),scope='Small-displacement undamped tangent; finite-deformation and damping not yet qualified')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();result=analyze(a.run)
    (a.run/'tangent_analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
