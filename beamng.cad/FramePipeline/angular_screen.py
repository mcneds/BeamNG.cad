"""Rest-pose discrete dynamics screen for native angular constraints.

The nonsymmetric angular tangent must not enter the symmetric spring budget.
This separate diagnostic omits tires, prestress, stops and filtered damping;
passing it is necessary for this experiment, never native qualification.
"""
import math
import numpy as np
from scipy.sparse import coo_matrix
from scipy.linalg import eigvals
from angular_beams import tangent,validate_references
from rigid_bracing import gradient


def matrices(part,nodes):
    names=list(nodes);index={n:i for i,n in enumerate(names)};size=3*len(names)
    mass=np.repeat([float(nodes[n]['options']['nodeWeight']) for n in names],3)
    if not np.isfinite(mass).all() or np.min(mass)<=0:raise ValueError('Positive finite node masses required')
    if any(nodes[n]['options'].get('fixed',False) for n in names):raise ValueError('Fixed-node elimination is not implemented in this screen')
    validate_references(part)
    rows=[];cols=[];kv=[];cv=[]
    def add(ids,k,c):
        ix=np.array([3*index[n]+a for n in ids for a in range(3)])
        scale=np.sqrt(mass[ix,None]*mass[None,ix])
        rr,cc=np.meshgrid(ix,ix,indexing='ij')
        rows.extend(rr.ravel());cols.extend(cc.ravel());kv.extend((k/scale).ravel());cv.extend((c/scale).ravel())
    def column(ids,g,k,c):
        if not all(math.isfinite(v) and v>=0 for v in (k,c)):raise ValueError('Invalid linear constraint')
        outer=np.outer(np.asarray(g).ravel(),np.asarray(g).ravel());add(ids,k*outer,c*outer)
    for section in ('beams','hydros'):
        defaults={}
        for row in part.get(section,[])[1:]:
            if isinstance(row,dict):defaults.update(row);continue
            ids=row[:2];o=defaults|(row[-1] if isinstance(row[-1],dict) else {});kind=o.get('beamType','|NORMAL')
            if kind=='|LBEAM':
                ids=ids+[o['id3:']];add(ids,tangent([nodes[n]['position'] for n in ids],float(o['beamSpring'])),np.zeros((9,9)));continue
            if kind not in ('|NORMAL','|BOUNDED','|SUPPORT'):raise ValueError('Unsupported beam type '+kind)
            filtered=o.get('dampCutoffHz',0)
            if filtered and kind!='|BOUNDED':raise ValueError('Filtered ordinary beam requires additional state')
            d=np.asarray(nodes[ids[1]]['position'],float)-nodes[ids[0]]['position'];length=np.linalg.norm(d)
            if length<1e-10:raise ValueError('Coincident ordinary nodes')
            d/=length;column(ids,[-d,d],float(o.get('beamSpring',0)),0. if filtered else float(o.get('beamDamp',0)))
    for row in part.get('torsionbars',[])[1:]:
        if not isinstance(row,list):raise ValueError('Explicit torsion options required')
        ids=row[:4];o=row[4];column(ids,gradient(np.array([nodes[n]['position'] for n in ids])),o['spring'],o['damp'])
    for row in part.get('slidenodes',[])[1:]:
        if not isinstance(row,list):continue
        n,rail,o=row;a,b=part['rails'][rail]['links:'];pa,pb,pc=[np.array(nodes[x]['position']) for x in (a,b,n)]
        d=pb-pa;t=float((pc-pa)@d/(d@d))
        if not 0<=t<=1 or np.linalg.norm(pc-pa-t*d)>1e-7:raise ValueError('Slider does not start on its rail')
        for direction in np.eye(3):column([n,a,b],[direction,-(1-t)*direction,-t*direction],o['spring'],0.)
    shape=(size,size)
    return tuple(coo_matrix((v,(rows,cols)),shape=shape).tocsr() for v in (kv,cv))


def symmetric_step_operator(k,c,dt=.0005):
    """Reject nonreciprocal constraints before a symmetric eigenvalue budget."""
    for matrix in (k,c):
        skew=matrix-matrix.T
        scale=max(1.,float(np.max(np.abs(matrix.data),initial=0.)))
        if np.max(np.abs(skew.data),initial=0.)>1e-12*scale:
            raise ValueError('Nonsymmetric constraints require the full discrete screen, not a mass budget')
    return dt*dt*k+2*dt*c


def discrete_spectrum(k,c,dt=.0005):
    """Semi-implicit Euler state uses scaled velocity dt*v for conditioning."""
    k=k.toarray() if hasattr(k,'toarray') else np.asarray(k)
    c=c.toarray() if hasattr(c,'toarray') else np.asarray(c)
    n=len(k);eye=np.eye(n);kd=dt*dt*k;cd=eye-dt*c
    state=np.block([[eye-kd,cd],[-kd,cd]])
    values=eigvals(state,overwrite_a=True,check_finite=True)
    radius=np.abs(values);order=np.argsort(radius)[-12:][::-1]
    return dict(step_seconds=dt,dimension=2*n,spectral_radius=float(radius.max()),
        unstable_modes=int(np.sum(radius>1+1e-7)),passed=bool(radius.max()<=1+1e-7),
        largest=[dict(real=float(values[i].real),imag=float(values[i].imag),modulus=float(radius[i])) for i in order],
        scope=__doc__)
