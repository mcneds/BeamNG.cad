"""Compare native prescribed-position torsion forces with the generation tangent."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from rigid_bracing import gradient


def tangent(points,spring,normal_spring):
    g=gradient(points).ravel();matrix=spring*np.outer(g,g)
    for a,b in itertools.combinations(range(4),2):
        d=points[b]-points[a];d/=np.linalg.norm(d);column=np.zeros((4,3));column[a]=-d;column[b]=d
        matrix+=normal_spring*np.outer(column.ravel(),column.ravel())
    return matrix


def analyze(run):
    job=json.loads((run/'job.json').read_bytes());completion=json.loads((run/'completion.json').read_bytes())
    if completion.get('status')!='completed' or completion.get('job_id')!=job['id']:raise ValueError('Incomplete coupon')
    rows=np.loadtxt(run/'torsion_coupon.csv',delimiter=',',skiprows=1)
    if rows.shape[1]!=2+24*len(job['coupons']) or not np.isfinite(rows).all() or not np.all(np.diff(rows[:,0])>0):raise ValueError('Invalid coupon recording')
    reports=[]
    for group,item in enumerate(job['coupons']):
        indices=np.array([[2+group*24+i*6+j for j in range(3)] for i in range(4)])
        def mean(case,offset):
            selected=rows[rows[:,1]==case][-5:]
            if len(selected)!=5:raise ValueError('Missing prescribed displacement case')
            return selected[:,(indices+offset).ravel()].mean(0)
        points=mean(0,0).reshape(4,3);matrix=tangent(points,item['spring'],item['normal_spring'])
        dx=np.array([mean(1+i*2,0)-mean(2+i*2,0) for i in range(12)]).T
        df=np.array([mean(1+i*2,3)-mean(2+i*2,3) for i in range(12)]).T
        if not np.allclose(dx,np.eye(12)*.0002,rtol=.01,atol=1e-7):raise ValueError('Prescribed positions were not recorded correctly')
        predicted=-matrix@dx;measured=-df@np.linalg.inv(dx)
        error=float(np.linalg.norm(df-predicted)/np.linalg.norm(predicted))
        reports.append(dict(name=item['name'],status='model_agrees' if error<.005 else 'model_rejected',relative_force_error=error,
            measured_asymmetry=float(np.linalg.norm(measured-measured.T)/np.linalg.norm(measured)),
            predicted_eigenvalues=np.linalg.eigvalsh(matrix).tolist(),measured_symmetric_eigenvalues=np.linalg.eigvalsh((measured+measured.T)/2).tolist(),
            positions=points.tolist(),predicted_tangent=matrix.tolist(),measured_tangent=measured.tolist()))
    return dict(scope='Small-displacement, zero-damping native force tangent only; dynamic stability and fracture are not qualified.',
        status='model_agrees' if all(r['status']=='model_agrees' for r in reports) else 'model_rejected',coupons=reports,
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('job.json','completion.json','torsion_coupon.csv','compiled_coupon.json','recorder.lua')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'tangent_analysis.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=r['status'],coupons=[{k:v for k,v in row.items() if k in ('name','status','relative_force_error','measured_asymmetry')} for row in r['coupons']]),indent=2))
