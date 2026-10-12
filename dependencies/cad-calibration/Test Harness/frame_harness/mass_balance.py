"""Unique positive mass allocation within an exact CAD moment polytope."""
import numpy as np


def balance(features,target,initial,lower,importance):
    """Minimize sum(mass**2 / importance), preserving moments and lower bounds.

    An LP optimum is generally a vertex selected by variable order. This strictly
    convex second stage removes that arbitrary asymmetry. An active-set QP uses
    only small equality solves; SVD removes dependent planar/linear moments.
    """
    u,s,v=np.linalg.svd(features,full_matrices=False);keep=s>s[0]*1e-12
    matrix=v[keep];rhs=(u[:,keep].T@target)/s[keep]
    values=initial.copy();active=np.zeros(len(values),dtype=bool)
    for iteration in range(20*len(values)):
        free=~active
        remaining=rhs-matrix[:,active]@lower[active]
        system=(matrix[:,free]*importance[free])@matrix[:,free].T
        multipliers=np.linalg.lstsq(system,remaining,rcond=1e-12)[0]
        candidate=lower.copy();candidate[free]=importance[free]*(matrix[:,free].T@multipliers)
        direction=candidate-values;violated=free&(candidate<lower-1e-11)
        if np.any(violated):
            ratio=np.where(violated,(values-lower)/np.maximum(-direction,1e-30),np.inf)
            index=int(np.argmin(ratio))
            values+=max(0.,min(1.,ratio[index]))*direction
            values[index]=lower[index];active[index]=True
            continue
        values=candidate;bound_gradient=values/importance-matrix.T@multipliers
        if np.any(active&(bound_gradient< -1e-10)):
            active[np.argmin(np.where(active,bound_gradient,np.inf))]=False
            continue
        if np.max(abs(features@values-target))>1e-9 or np.any(values<lower-1e-10):
            raise ValueError('Balanced node masses failed exact moment/lower-bound validation')
        return values,dict(method='Unique minimum weighted squared mass at exact CAD moments',iterations=iteration+1,
                           maximum_moment_residual=float(np.max(abs(features@values-target))))
    raise ValueError('Balanced node mass allocation did not converge')
