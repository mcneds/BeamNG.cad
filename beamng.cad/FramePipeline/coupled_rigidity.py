"""Fit existing numerical constraints together, retaining their exact nullspace.

Only explicitly selected coefficients change. The positive span of existing
constraint gradients determines the target; no spring across a free mechanism
is introduced. The full assembly must still pass its separate step budget.
"""
import math
import numpy as np
from scipy.optimize import minimize
from frame_harness.build import node_table
from rigid_bracing import gradient


def logdet_objective(x,b,penalty=1e-4):
    from scipy.linalg import cho_factor,cho_solve
    matrix=(b*x)@b.T;factor=cho_factor(matrix,lower=True,check_finite=False)
    trace=np.sum(b*b,axis=0)
    solved=cho_solve(factor,b,check_finite=False)
    value=float(trace@x-2*np.log(np.diag(factor[0])).sum()+penalty*(x@x))
    derivative=trace-np.sum(b*solved,axis=0)+2*penalty*x
    return value,derivative


def compliance_objective(x,b,outputs):
    """Minimize output compliance under a smooth spectral stiffness cap.

    The eighth spectral norm is an upper bound on the highest eigenvalue.
    Its scale cancels the inverse stiffness response. A small all-mode term
    protects unrelated deformation directions; a trace penalty fixes scale.
    """
    from scipy.linalg import eigh
    k=(b*x)@b.T
    eigen,vectors=eigh(k,check_finite=False);high=eigen[-1]
    if eigen[0]<=0:raise ValueError('Nonpositive constrained stiffness in motion fit')
    ratio=eigen/high;total=np.sum(ratio**8);cap=high*total**(1/8)
    columns=vectors.T@b;squared=columns**2
    dc=np.sum(squared*(ratio**7*total**(-7/8))[:,None],axis=0)
    response=(vectors.T@outputs)/eigen[:,None];twice=response/eigen[:,None]
    norm=float(np.sum(response**2));dn=-2*np.sum((columns.T@response)*(columns.T@twice),axis=1)
    softness=float(np.sum(1/eigen))/len(k);ds=-np.sum(squared/eigen[:,None]**2,axis=0)/len(k)
    trace=np.sum(b*b,axis=0);scale=(trace@x)/len(k)-1
    return cap**2*norm+.01*cap*softness+scale**2,2*cap*dc*norm+cap**2*dn+.01*(dc*softness+cap*ds)+2*scale*trace/len(k)


def fit(part,options,frequency,objective_kind='isotropic',manifest=None):
    if not math.isfinite(frequency) or not 100<=frequency<=600:raise ValueError('Coupled rigidity frequency must be in [100,600] Hz')
    if objective_kind not in ('isotropic','logdet','motion'):raise ValueError('Unknown coupled rigidity objective')
    selected={id(o) for o in options};nodes=node_table(part);entries=[];seen=set()
    for section in ('beams','hydros'):
        for row in part.get(section,[])[1:]:
            if not isinstance(row,list) or id(row[-1]) not in selected:continue
            o=row[-1]
            if o.get('beamType','|NORMAL')!='|NORMAL' or o.get('dampCutoffHz',0):raise ValueError('Coupled fit requires unfiltered normal constraints')
            xyz=np.array([nodes[n]['position'] for n in row[:2]],dtype=float);d=xyz[1]-xyz[0];d/=np.linalg.norm(d)
            entries.append((row[:2],np.array([-d,d]),o,'beamSpring','beamDamp'));seen.add(id(o))
    for row in part.get('torsionbars',[])[1:]:
        if not isinstance(row,list) or id(row[-1]) not in selected:continue
        o=row[-1];entries.append((row[:4],gradient(np.array([nodes[n]['position'] for n in row[:4]],dtype=float)),o,'spring','damp'));seen.add(id(o))
    if seen!=selected:raise ValueError('Selected constraint is missing or unsupported')
    names=sorted({n for ids,_,_,_,_ in entries for n in ids});index={n:i for i,n in enumerate(names)}
    if not names or len(names)>250 or len(entries)>5000:raise ValueError('Coupled numerical fit exceeds bounded size')
    mass=np.array([nodes[n]['options']['nodeWeight'] for n in names]);columns=[]
    for ids,vectors,_,_,_ in entries:
        column=np.zeros((len(names),3))
        for n,vector in zip(ids,vectors):column[index[n]]+=vector/np.sqrt(mass[index[n]])
        columns.append(column.ravel())
    a=np.array(columns).T;inverse=np.sum(a*a,axis=0);unit=a/np.sqrt(inverse)
    u,s,_=np.linalg.svd(unit,full_matrices=False);rank=int(np.count_nonzero(s>s[0]*1e-6));retained=u[:,:rank]
    reduced=retained.T@unit
    motion_report=None
    if objective_kind=='isotropic':
        target=np.sum(reduced**2,axis=0);gram=(unit.T@unit)**2+np.eye(len(entries))*1e-4
        def objective(x):
            g=gram@x-target
            return float(x@(g-target)),2*g
        minimum=0.
    elif objective_kind=='logdet':
        # log(det) weights a weak constrained mode more strongly than a squared
        # operator error. The basis excludes every intended free motion; the
        # exported operator still uses only the existing positive constraints.
        def objective(x):return logdet_objective(x,reduced)
        minimum=1e-8
    else:
        if manifest is None:raise ValueError('CAD manifest required for motion objective')
        from motion_objective import front_columns
        outputs,motion_report=front_columns(part,names,manifest)
        outputs=retained.T@outputs
        outputs/=np.linalg.norm(outputs)
        def objective(x):return compliance_objective(x,reduced,outputs)
        minimum=1e-6
    initial=np.full(len(entries),rank/len(entries));initial_value=objective(initial)[0];iterations=0
    def progress(x):
        nonlocal iterations
        iterations+=1
        if objective_kind=='motion' and iterations%50==0:
            from frame_harness.progress import emit
            emit('CAD motion fit',completed=iterations,total=1000,detail='Bounded numerical optimization; native accuracy still unverified')
    result=minimize(objective,initial,jac=True,bounds=[(minimum,None)]*len(entries),callback=progress,
                    method='L-BFGS-B',options={'maxiter':1000 if objective_kind=='motion' else 3000,'ftol':1e-12,'gtol':1e-8,'maxcor':20})
    # Iterative design need not reach the global numerical optimum to produce
    # a useful experimental candidate. Keep an explicitly labelled, improving
    # iteration-limited motion fit only; every physical/native gate still runs.
    limited=(objective_kind=='motion' and result.status==1 and np.isfinite(result.x).all()
             and np.isfinite(result.fun) and result.fun<initial_value*.9)
    if not result.success and not limited:raise ValueError('Coupled operator fit failed: '+result.message)
    springs=np.maximum(result.x,1e-5)*(2*math.pi*frequency)**2/inverse
    springs*=min(1.,(2*math.pi*frequency)**2/np.linalg.eigvalsh((a*springs)@a.T)[-1])
    for (_,_,o,key,damp),spring in zip(entries,springs):
        old=float(o[key]);o[damp]=float(o.get(damp,0))*math.sqrt(float(spring)/old) if old>0 else 0.
        o[key]=float(spring)
    spectrum=np.linalg.eigvalsh((a*springs)@a.T);positive=spectrum[-rank:]
    return dict(node_count=len(names),constraint_count=len(entries),rank=rank,nullity=3*len(names)-rank,objective=objective_kind,iterations=int(result.nit),motion_objective=motion_report,
        optimizer_status='converged' if result.success else 'iteration_limit_diagnostic_candidate',objective_initial=float(initial_value),objective_final=float(result.fun),
        requested_frequency_hz=frequency,minimum_internal_frequency_hz=float(np.sqrt(max(0,positive[0]))/(2*math.pi)),
        maximum_internal_frequency_hz=float(np.sqrt(positive[-1])/(2*math.pi)),
        damping_policy='Preserve each selected constraint damping ratio before the separate assembled budget',
        scope='Positive refit on existing gradients only; no new constraints, nodes, masses, hardpoints or actuator targets. Physical coilovers are excluded by the caller.')
