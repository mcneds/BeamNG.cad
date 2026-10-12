"""Bound ballast on the existing ownership/node layout without proposing a tune.

Recover the pre-ballast discrete mass allocation from the audited ledger. Solve
three relaxations: retain each owner's mass; mass and COM; mass, COM and inertia.
Shared nodes count once. Non-loaded donor nodes may become massless and split
owners may redistribute internally, making these optimistic bounds, not usable
exports. Tire rings remain fixed. No timestep or elastic constraint is imposed.
The recovered discrete moments are not an independent continuum CAD reference.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix


def close(actual, expected, context):
    if not np.isfinite([actual, expected]).all() or abs(actual-expected)>1e-7*max(1.,abs(expected)):
        raise ValueError('Mass ledger mismatch: '+context)


def recover(manifest):
    """Remove each documented addition once, including unloaded spectral nodes."""
    m=manifest; ledger=m['numerical_mass']; allocations=m['mass_allocations']
    nodes=m['nodes']; loaded=ledger['nodes']; increments={}
    for row in ledger.get('spectral_mass_increments',[]):
        n=row['name']
        if n in increments:raise ValueError('Duplicate spectral increment')
        close(row['after_kg']-row['before_kg'],row['added_kg'],n+' increment')
        close(nodes[n]['mass_kg'],row['after_kg'],n+' final increment')
        if row['added_kg']<0:raise ValueError('Negative spectral increment')
        increments[n]=row['added_kg']
    baseline={o:{} for o in allocations}; additions={o:0. for o in allocations}
    for n,data in nodes.items():
        actual=float(data['mass_kg']); owners={o:a[n] for o,a in allocations.items() if n in a}
        if not owners or actual<=0 or any(v<0 for v in owners.values()):raise ValueError('Invalid ownership: '+n)
        close(sum(owners.values()),actual,n+' assembled ownership')
        if n in loaded:
            row=loaded[n]; extra=row['added_by_component_kg']
            if set(extra)-set(owners):raise ValueError('Unknown ballast owner: '+n)
            close(sum(extra.values()),row['added_mass_kg'],n+' loaded additions')
            close(row['simulated_mass_kg'],actual,n+' simulated mass')
            close(row['redistributed_cad_mass_kg']+row['added_mass_kg'],actual,n+' recovered mass')
        else:
            extra={o:v/actual*increments.get(n,0.) for o,v in owners.items()}
        for o,value in owners.items():
            added=extra.get(o,0.)
            if added < -1e-9 or value-added < -1e-9:raise ValueError('Invalid ballast allocation: '+n)
            baseline[o][n]=max(0.,value-added); additions[o]+=added
    for o in allocations:close(additions[o],ledger['added_by_component_kg'].get(o,0.),o+' additions')
    added=sum(additions.values()); close(added,ledger['added_mass_kg'],'total ballast')
    rings=sum(w['wheel_mass_kg'] for w in m['wheels'].values())
    cad=sum(sum(a.values()) for a in baseline.values())+rings
    close(cad,m['cad_dry_mass_kg'],'CAD total')
    close(cad+added,m['expected_dry_mass_kg'],'simulated total')
    return baseline, additions, rings


def bound(positions, allocations, targets, moment_order):
    """LP lower bound; its solution is deliberately not exposed as an export."""
    if moment_order not in (1,4,10):raise ValueError('Moment order must be 1, 4 or 10')
    if any(not np.isfinite(v) or v<=0 for v in targets.values()):raise ValueError('Invalid target')
    owners=sorted(o for o,a in allocations.items() if a)
    variables=[(o,n) for o in owners for n in sorted(allocations[o])]
    names=sorted(targets); count=len(variables); total=count+len(names)
    index={key:i for i,key in enumerate(variables)}
    equal=lil_matrix((moment_order*len(owners),total)); rhs=[]
    for row,o in enumerate(owners):
        a=allocations[o]; nn=sorted(a); weights=np.array([a[n] for n in nn])
        points=np.array([positions[n] for n in nn],float)
        if not np.isfinite(points).all() or not np.isfinite(weights).all() or min(weights)<0 or sum(weights)<=0:
            raise ValueError('Invalid physical allocation: '+o)
        center=weights@points/sum(weights); scale=max(float(np.max(np.linalg.norm(points-center,axis=1))),1e-6)
        x,y,z=((points-center)/scale).T
        features=np.array([np.ones(len(nn)),x,y,z,x*x,y*y,z*z,x*y,x*z,y*z])[:moment_order]
        for j,n in enumerate(nn):equal[row*moment_order:(row+1)*moment_order,index[o,n]]=features[:,j,None]
        rhs.extend(features@weights)
    upper=lil_matrix((len(names),total))
    for row,n in enumerate(names):
        if n not in positions:raise ValueError('Unknown loaded node: '+n)
        for o in owners:
            if (o,n) in index:upper[row,index[o,n]]=-1.
        upper[row,count+row]=-1.
    cost=np.r_[np.zeros(count),np.ones(len(names))]; limits=-np.array([targets[n] for n in names])
    equal=equal.tocsr(); upper=upper.tocsr(); rhs=np.array(rhs)
    fit=linprog(cost,A_ub=upper,b_ub=limits,A_eq=equal,b_eq=rhs,bounds=(0,None),method='highs')
    if not fit.success:raise ValueError('Ballast bound failed: '+fit.message)
    primal=float(cost@fit.x); dual=float(rhs@fit.eqlin.marginals+limits@fit.ineqlin.marginals)
    residuals=dict(equality=float(np.max(abs(equal@fit.x-rhs),initial=0)),
        inequality=float(np.max(upper@fit.x-limits,initial=0)),
        positivity=float(max(0.,-min(fit.x))),
        dual=float(np.max(equal.T@fit.eqlin.marginals+upper.T@fit.ineqlin.marginals-cost,initial=0)),
        dual_sign=float(np.max(fit.ineqlin.marginals,initial=0)),gap=abs(primal-dual))
    if max(residuals.values())>1e-6:raise ValueError('Ballast bound primal/dual check failed: '+str(residuals))
    return dict(minimum_added_kg=primal,dual_lower_bound_kg=dual,residuals=residuals,
        moment_order=moment_order,loaded_node_count=len(names),
        # A dual pressure measures the local objective sensitivity; it does not
        # identify a uniquely optimal mass allocation or a removable node.
        active_floor_prices={n:float(-fit.ineqlin.marginals[i]) for i,n in enumerate(names) if fit.ineqlin.marginals[i]<-1e-6})


def audit(manifest_path):
    raw=manifest_path.read_bytes(); m=json.loads(raw); a,extra,rings=recover(m)
    positions={n:v['position'] for n,v in m['nodes'].items()}; ledger=m['numerical_mass']
    base=float(ledger['target_kg']); targets={n:base for n in ledger['nodes']}
    conditioned={n:float(r['target_kg']) for n,r in ledger['nodes'].items()}
    result=dict(scope=__doc__,manifest=str(manifest_path.resolve()),manifest_sha256=hashlib.sha256(raw).hexdigest(),
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cad_mass_kg=m['cad_dry_mass_kg'],generated_mass_kg=m['expected_dry_mass_kg'],
        numerical_mass_kg=sum(extra.values()),fixed_generated_ring_mass_kg=rings,loaded_floor_kg=base,
        components=[dict(owner=o,role=m['component_roles'].get(o),physical_explicit_mass_kg=sum(a[o].values()),
            numerical_mass_kg=extra[o],generated_explicit_mass_kg=sum(m['mass_allocations'][o].values())) for o in a],
        bounds={},qualified=False,export_proposed=False)
    for label,values in [('base_floor',targets),('conditioned_floor',conditioned)]:
        result['bounds'][label]={}
        for mode,order in [('mass_only',1),('mass_com',4),('discrete_mass_com_inertia',10)]:
            r=bound(positions,a,values,order); result['bounds'][label][mode]=r
            print(label,mode,f"{r['minimum_added_kg']:.6f} kg lower bound",flush=True)
    result['interpretation']='Positive bounds rule out exact mass equivalence on this fixed ownership layout under these floors and wheel-ring allocation. They do not rule out another representation. The gap to current ballast is not a safe removable mass: stability, elastic response, positive donor masses and split-member restrictions were omitted.'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('Use a new evidence path')
    report=audit(args.manifest);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
