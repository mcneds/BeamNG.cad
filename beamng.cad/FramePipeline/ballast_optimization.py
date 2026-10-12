"""Offline redistribution of numerical ballast at fixed stiffness and damping.

The symmetric rest-state timestep inequality is only a screening condition.
Its feasible mass distributions still require nonlinear native validation.
"""
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigsh


def minimize(operator, mass, lower, upper, costs, limit=3.2, iterations=200, progress=None):
    mass, lower, upper, costs = [np.asarray(v, float) for v in (mass, lower, upper, costs)]
    n = len(mass)
    if any(v.shape != (n,) or not np.isfinite(v).all() for v in (mass, lower, upper, costs)):
        raise ValueError('Invalid mass optimization vectors')
    if np.any(lower <= 0) or np.any(lower > mass) or np.any(upper < mass) or np.any(costs <= 0):
        raise ValueError('Bounds must contain the positive reference mass')
    a = csr_matrix(operator)
    if a.shape != (3*n, 3*n) or not np.isfinite(a.data).all() or np.max(abs((a-a.T).data), initial=0) > 1e-9:
        raise ValueError('Finite symmetric three-coordinate operator required')
    if not np.isfinite(limit) or limit <= 0 or iterations < 1:
        raise ValueError('Invalid solver limits')
    start = np.random.default_rng(0).normal(size=3*n)

    def eigen(w, many=False):
        inv = np.repeat(1/np.sqrt(w), 3)
        scaled = a.multiply(inv[:, None]).multiply(inv[None, :]).tocsr()
        if 3*n <= 24:
            values, vectors = np.linalg.eigh(scaled.toarray())
        else:
            values, vectors = eigsh(scaled, k=12 if many else 1, which='LA', tol=1e-9, v0=start)
        return values, vectors, inv

    reference = np.ones(n)
    reference_peak = float(eigen(reference)[0][-1])
    if reference_peak > limit+1e-7:
        raise ValueError('Reference does not satisfy the requested timestep screen')
    objective = costs*mass
    cuts, rhs = [mass.copy()], [float(mass.sum())]
    bounds = list(zip(lower/mass, upper/mass))
    best = reference.copy(); best_cost = float(objective@best)
    history = []; weights = reference.copy(); lower_bound = None
    for iteration in range(iterations):
        fit = linprog(objective, A_ub=np.array(cuts), b_ub=np.array(rhs), bounds=bounds, method='highs')
        if not fit.success:
            raise ValueError('Ballast relaxation failed: '+fit.message)
        weights = fit.x; lower_bound = float(fit.fun)
        values, vectors, inv = eigen(weights, True); peak = float(values[-1])
        history.append(dict(iteration=iteration,step_eigenvalue=peak,mass_kg=float(mass@weights),objective=lower_bound))
        if progress: progress(history[-1])
        if peak <= limit+1e-7:
            best = weights.copy(); best_cost = lower_bound
            break
        for value, vector in zip(values, vectors.T):
            if value <= limit+1e-8: continue
            q = vector*inv
            participation = np.sum(q.reshape(-1,3)**2, axis=1)
            cuts.append(-limit*participation); rhs.append(-float(q@(a@q)))
    # A convex blend with a verified feasible reference is checked explicitly.
    # This repairs finite cutting-plane convergence, not an optimality claim.
    if history[-1]['step_eigenvalue'] > limit+1e-7:
        low, high = 0., 1.
        for _ in range(28):
            fraction = (low+high)/2
            candidate = (1-fraction)*weights+fraction*reference
            if eigen(candidate)[0][-1] > limit+1e-7: low = fraction
            else: high = fraction
        candidate = (1-high)*weights+high*reference
        if float(objective@candidate) < best_cost:
            best = candidate; best_cost = float(objective@best)
    final_peak = float(eigen(best)[0][-1]); after = mass*best
    if final_peak > limit+1e-7 or after.sum() > mass.sum()+1e-7 or np.any(after < lower-1e-8) or np.any(after > upper+1e-8):
        raise ValueError('Reconstructed ballast solution violates bounds')
    return dict(masses=after.tolist(),reference_step_eigenvalue=reference_peak,final_step_eigenvalue=final_peak,
                reference_objective=float(objective@reference),objective=best_cost,objective_lower_bound=lower_bound,
                optimality_gap=best_cost-lower_bound,history=history,qualified=False)
