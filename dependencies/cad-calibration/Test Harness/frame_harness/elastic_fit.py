"""Elastic response and smooth spectral penalty with analytic spring gradients."""
import numpy as np
from scipy.linalg import cho_factor,cho_solve,eigh
from scipy.sparse import issparse


def stiffness_matrix(columns,values):
    if issparse(columns):return (columns.multiply(values)@columns.T).toarray()
    return (columns*values)@columns.T


def objective(values,initial,weighted,cases,limit,regularizer=1e-5,response_pairs=()):
    trial=initial*np.exp(values);value=regularizer*float(np.mean(values*values));gradient=2*regularizer*values/len(values)
    compliance=np.zeros(len(cases));errors=np.zeros(len(cases));sensitivities=np.zeros((len(cases),len(values)))
    ceilings=np.zeros(len(cases),dtype=bool);groups={}
    for index,case in enumerate(cases):groups.setdefault(id(case[0]),[]).append((index,case))
    for group in groups.values():
        indices=[i for i,_ in group];matrix=group[0][1][0]
        loads=np.column_stack([case[1] for _,case in group]);targets=np.array([case[2] for _,case in group])
        flags=np.array([len(case)>3 and case[3] for _,case in group])
        stiffness=stiffness_matrix(matrix,trial)
        u=cho_solve(cho_factor(stiffness,check_finite=False),loads,check_finite=False)
        response=np.sum(loads*u,axis=0);error=np.log(response/targets)
        error=np.where(flags,np.maximum(0.,error),error)
        errors[indices]=error;sensitivities[indices]=(-trial[:,None]*(matrix.T@u)**2/response).T
        compliance[indices]=response/targets;ceilings[indices]=flags
    # One-sided local ceilings permit very unequal responses at corresponding
    # mounts. Preserve their independent CAD response ratio as well; this does
    # not assume equal left/right geometry or force every mount to its ceiling.
    pair_errors=[];pair_sensitivities=[]
    for first,second,ratio in response_pairs:
        actual=compliance[first]*cases[first][2]/(compliance[second]*cases[second][2])
        pair_errors.append(np.log(actual/ratio))
        pair_sensitivities.append(sensitivities[first]-sensitivities[second])
    if pair_errors:
        errors=np.r_[errors,pair_errors]
        sensitivities=np.vstack([sensitivities,pair_sensitivities])
    # Acceptance is per load case. A sum of squares can sacrifice one mounting
    # response to make already-good cases almost exact. A smooth minimax norm
    # directs the remaining modal budget toward the worst response instead.
    errors=np.asarray(errors);worst=float(np.max(abs(errors),initial=0.))
    if worst:
        normalized=errors/worst;norm=float(np.sum(abs(normalized)**8)**(1/8))
        value+=(worst*norm)**2
        weights=2*worst*normalized**7/norm**6
        gradient+=weights@np.asarray(sensitivities)
    # Only eigenvalues above the cap contribute. Subset extraction avoids
    # computing the hundreds of inactive eigenvectors in a larger frame graph.
    matrix=stiffness_matrix(weighted,trial)
    lam,vector=eigh(matrix,subset_by_value=(limit,np.inf),check_finite=False)
    excess=lam/limit-1
    value+=1000*float(excess@excess)
    if len(lam):gradient+=2000*trial*((weighted.T@vector)**2@excess)/limit
    scale=max(1.,float(lam[-1]/limit)) if len(lam) else 1.
    return value,gradient,dict(compliance_ratios=compliance.tolist(),projection_scale=1/scale,
        projected_relative_errors=[max(0.,ratio*scale-1) if ceiling else abs(ratio*scale-1) for ratio,ceiling in zip(compliance,ceilings)]+
                                  [abs(float(np.expm1(error))) for error in pair_errors],
        response_pair_relative_errors=[abs(float(np.expm1(error))) for error in pair_errors],excessive_modes=len(lam))
