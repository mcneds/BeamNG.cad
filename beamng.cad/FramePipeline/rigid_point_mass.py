"""Explicit minimal-member mass approximation, without auxiliary inertial nodes."""
import numpy as np
from scipy.optimize import minimize


def distribute(moments, points):
    mass,center,inertia=moments
    xyz=np.asarray(points,float);center=np.asarray(center,float);inertia=np.asarray(inertia,float)
    if (xyz.ndim!=2 or xyz.shape[1]!=3 or center.shape!=(3,) or inertia.shape!=(3,3)
            or not all(np.isfinite(v).all() for v in (xyz,center,inertia)) or not np.isfinite(mass) or mass<=0 or len(xyz)<3):
        raise ValueError('Minimal rigid member needs positive mass and at least three finite hardpoints')
    span=float(np.linalg.norm(np.ptp(xyz,axis=0)))
    if span<=1e-6 or np.linalg.matrix_rank(xyz-xyz.mean(0),tol=1e-8)<2:
        raise ValueError('Minimal rigid hardpoints must be noncollinear')
    q=(xyz-center)/span
    tensors=np.array([np.dot(p,p)*np.eye(3)-np.outer(p,p) for p in q])
    A=np.vstack((q.T,tensors.reshape(len(xyz),9).T))
    target=np.r_[np.zeros(3),(inertia/(mass*span**2)).ravel()]
    # Convex normalized moment fit with exact total mass and positive weights.
    # Full tensors make the objective invariant to a reflected/rotated CAD frame.
    def objective(w):
        residual=A@w-target
        return .5*float(residual@residual)+5e-10*float(w@w),A.T@residual+1e-9*w
    fit=minimize(objective,np.full(len(xyz),1/len(xyz)),jac=True,method='SLSQP',
                 bounds=[(1e-6,1.)]*len(xyz),constraints=[dict(type='eq',fun=lambda w:w.sum()-1,jac=lambda w:np.ones(len(w)))],
                 options=dict(ftol=1e-13,maxiter=500))
    if not fit.success:raise ValueError('Minimal rigid mass fit failed: '+fit.message)
    weights=mass*fit.x/fit.x.sum();actual_center=weights@xyz/mass;relative=xyz-actual_center
    actual_inertia=sum(w*(p@p*np.eye(3)-np.outer(p,p)) for w,p in zip(weights,relative))
    report=dict(target_mass_kg=float(mass),actual_mass_kg=float(weights.sum()),
        target_com_m=center.tolist(),actual_com_m=actual_center.tolist(),
        com_error_m=float(np.linalg.norm(actual_center-center)),
        inertia_relative_error=float(np.linalg.norm(actual_inertia-inertia)/max(np.linalg.norm(inertia),1e-12)),
        mass_preserved=True,moments_qualified=False,allocation_method='hardpoint_lumped',
        representation='Mechanical hardpoints only; positive CAD mass distribution with approximate COM/inertia',
        limitations=['Minimal suspension arm representation approximates CAD COM/inertia; added numerical support mass is accounted separately.'])
    return xyz,weights,report
