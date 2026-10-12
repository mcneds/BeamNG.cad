"""Optional rigid-frame reference with chassis-only hardpoint bracing.

This is an integration reference, never a material/fracture calibration. Fit a
positive numerical operator on axial and angular chassis constraints. The Gram
form avoids allocating one dense outer-product column per frame constraint.
"""
import math,itertools
import numpy as np
from scipy.optimize import minimize
from frame_harness.build import node_table
from rigid_bracing import gradient


def fit(part, frame_ids, frequency, pivot_priority=1.):
    if not math.isfinite(frequency) or not 0<frequency<=600:
        raise ValueError('Rigid frame reference frequency must be in (0,600] Hz')
    if not math.isfinite(pivot_priority) or not 1<=pivot_priority<=16:
        raise ValueError('Rigid frame pivot priority must be in [1,16]')
    nodes=node_table(part);names=list(frame_ids);index={n:i for i,n in enumerate(names)};own=set(names)
    # These points are all on the chassis side of a joint. Direct constraints
    # make the reference frame support its hardpoints without routing every
    # suspension force through light shell tessellation points. No moving
    # member or spring endpoint is added to this set.
    pivots=sorted({p['parents'][0] for p in part.get('cadMountPatches',{}).values() if p.get('mode')=='joint'})
    if not set(pivots)<=own:raise ValueError('Rigid frame reference pivot outside chassis')
    existing={frozenset(r[:2]) for r in part['beams'][1:] if isinstance(r,list)}
    extra=[]
    for a,b in itertools.combinations(pivots,2):
        if frozenset((a,b)) in existing:continue
        if np.linalg.norm(np.array(nodes[a]['position'])-nodes[b]['position'])<1e-7:
            raise ValueError('Coincident distinct rigid frame pivots')
        extra.append([a,b,dict(beamType='|NORMAL',beamSpring=1.,beamDamp=0.,beamDeform=1e30,beamStrength=1e30,breakGroup='')])
    part['beams'].extend(extra)
    masses=np.array([nodes[n]['options']['nodeWeight'] for n in names]);columns=[];options=[];kinds=[]
    def add(ids,vectors,opts,kind):
        col=np.zeros((len(names),3))
        for n,v in zip(ids,vectors):col[index[n]]+=v/np.sqrt(masses[index[n]])
        columns.append(col.ravel());options.append(opts);kinds.append(kind)
    defaults={};rows=[]
    for row in part['beams'][1:]:
        if isinstance(row,dict):defaults.update(row);continue
        opts=defaults|(row[-1] if isinstance(row[-1],dict) else {});a,b=row[:2];rows.append([a,b,opts])
        if not {a,b}<=own:continue
        if opts.get('breakGroup') or opts.get('beamType','|NORMAL')!='|NORMAL':raise ValueError('Rigid frame reference contains a moving or release connection')
        d=np.array(nodes[b]['position'],dtype=float)-nodes[a]['position'];d/=np.linalg.norm(d)
        add([a,b],[-d,d],opts,'beam')
    part['beams']=[part['beams'][0],*rows]
    for row in part.get('torsionbars',[])[1:]:
        if not isinstance(row,list) or not set(row[:4])<=own:continue
        if row[-1].get('breakGroup'):raise ValueError('Rigid frame reference contains angular release connection')
        add(row[:4],gradient(np.array([nodes[n]['position'] for n in row[:4]])),row[-1],'angular')
    a=np.array(columns).T;inverse=np.sum(a*a,axis=0);unit=a/np.sqrt(inverse)
    left,singular,_=np.linalg.svd(unit,full_matrices=False);rank=int(np.count_nonzero(singular>singular[0]*1e-6))
    if rank!=3*len(names)-6:raise ValueError('Rigid frame reference has an internal mechanism')
    retained=left[:,:rank];target=np.sum((retained.T@unit)**2,axis=0)
    if pivot_priority!=1:
        # Prioritize the coordinates where joints transmit load, projected onto
        # deformation only. Whole-frame translation and rotation remain free.
        projected=retained@(retained.T@unit)
        weights=np.repeat([pivot_priority if n in pivots else 1. for n in names],3)
        target=np.sum(projected**2*weights[:,None],axis=0)
    gram=(unit.T@unit)**2+np.eye(len(columns))*1e-4
    def objective(x):
        g=gram@x-target
        return float(x@(g-target)),2*g
    result=minimize(objective,np.full(len(columns),rank/len(columns)),jac=True,bounds=[(0,None)]*len(columns),
                    method='L-BFGS-B',options={'maxiter':2000,'ftol':1e-12,'gtol':1e-8,'maxcor':20})
    if not result.success:raise ValueError('Rigid frame operator fit failed: '+result.message)
    k=np.maximum(result.x,1e-5)*(2*math.pi*frequency)**2/inverse
    k*=min(1.,(2*math.pi*frequency)**2/np.linalg.eigvalsh((a*k)@a.T)[-1])
    damp=.15*np.sqrt(k/inverse)
    dt=.0005;stiff=dt*dt*np.linalg.eigvalsh((a*k)@a.T)[-1];visc=2*dt*np.linalg.eigvalsh((a*damp)@a.T)[-1]
    damp*=min(1.,max(0,2.-stiff)/max(visc,1e-12))
    for opts,kind,spring,damping in zip(options,kinds,k,damp):
        if kind=='beam':opts.update(beamSpring=float(spring),beamDamp=float(damping),beamDeform=1e30,beamStrength=1e30)
        else:opts.update(spring=float(spring),damp=float(damping),deform=1e30,strength=1e30)
    spectrum=np.linalg.eigvalsh((a*k)@a.T)
    return options,dict(mode='rigid_reference',requested_frequency_hz=frequency,node_count=len(names),constraint_count=len(columns),added_chassis_beams=len(extra),
        pivot_priority=pivot_priority,
        minimum_internal_frequency_hz=float(np.sqrt(max(0,spectrum[6]))/(2*math.pi)),material_response_qualified=False,
        scope='Numerical rigid frame reference with chassis-only pivot bracing; CAD geometry and mass retained, frame material stiffness and fracture replaced. Moving suspension joints and coilover laws unchanged.')
