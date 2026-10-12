"""Redistribute existing point masses without changing each owner's moments.

This is an optional numerical experiment. It preserves the current discrete CAD
representation, not a new claim of material accuracy. Split moving owners are
frozen so mass cannot move between, for example, a rack and its housing.
"""
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, vstack


def redistribute(graph, targets, minimum_donor_mass=.25):
    if not np.isfinite(minimum_donor_mass) or minimum_donor_mass<=0:
        raise ValueError('Redistribution donor mass floor must be positive')
    frozen={v['owner'] for v in getattr(graph,'rigid_member_allocations',{}).values()}
    owners={o:dict(a) for o,a in graph.mass_allocations.items() if a}
    for node,data in graph.nodes.items():
        mass=float(data['options']['nodeWeight'])
        if abs(sum(a.get(node,0.) for a in owners.values())-mass)>max(1e-8,mass*1e-8):
            raise ValueError('Redistribution requires complete node mass ownership: '+node)
    variables=[(o,n) for o,a in sorted(owners.items()) for n in sorted(a)]
    names=sorted(targets);count=len(variables);nvar=2*count+len(names)
    original=np.array([owners[o][n] for o,n in variables])
    indices={key:i for i,key in enumerate(variables)}
    equal=lil_matrix((10*len(owners),nvar));rhs=[]
    for row,(owner,allocation) in enumerate(sorted(owners.items())):
        nodes=sorted(allocation);weights=np.array([allocation[n] for n in nodes])
        points=np.array([graph.nodes[n]['position'] for n in nodes],float)
        center=weights@points/sum(weights)
        scale=max(float(np.max(np.linalg.norm(points-center,axis=1))),1e-6)
        x,y,z=((points-center)/scale).T
        moments=np.array([np.ones(len(nodes)),x,y,z,x*x,y*y,z*z,x*y,x*z,y*z])
        for j,node in enumerate(nodes):equal[10*row:10*row+10,indices[owner,node]]=moments[:,j,None]
        rhs.extend(moments@weights)
    # Loaded-node shortfalls plus absolute changes for a second, least-change fit.
    upper=lil_matrix((len(names)+2*count,nvar));bound=[]
    for row,node in enumerate(names):
        for owner in owners:
            if (owner,node) in indices:upper[row,indices[owner,node]]=-1
        upper[row,count+row]=-1;bound.append(-targets[node])
    for i,mass in enumerate(original):
        row=len(names)+2*i;deviation=count+len(names)+i
        upper[row,i]=1;upper[row,deviation]=-1;bound.append(mass)
        upper[row+1,i]=-1;upper[row+1,deviation]=-1;bound.append(-mass)
    bounds=[(m,m) if o in frozen else (min(m,minimum_donor_mass),None)
            for (o,n),m in zip(variables,original)]+[(0,None)]*(nvar-count)
    objective=np.zeros(nvar);objective[count:count+len(names)]=1
    equal=equal.tocsr();upper=upper.tocsr();rhs=np.array(rhs)
    first=linprog(objective,A_ub=upper,b_ub=bound,A_eq=equal,b_eq=rhs,bounds=bounds,method='highs')
    if not first.success:raise ValueError('Support mass redistribution failed: '+first.message)
    best=float(objective@first.x)
    upper=vstack([upper,objective.reshape(1,-1)]).tocsr();bound=np.r_[bound,best+1e-8]
    least_change=np.zeros(nvar);least_change[count+len(names):]=1
    fit=linprog(least_change,A_ub=upper,b_ub=bound,A_eq=equal,b_eq=rhs,bounds=bounds,method='highs')
    if not fit.success:raise ValueError('Support mass least-change fit failed: '+fit.message)
    residual=float(np.max(abs(equal@fit.x-rhs)/np.maximum(1.,abs(rhs))))
    if residual>1e-7 or min(fit.x[:count])<=0:raise ValueError('Support mass moments/positivity check failed')
    totals={n:0. for n in graph.nodes};moved={}
    for i,(owner,node) in enumerate(variables):
        value=float(fit.x[i]);graph.mass_allocations[owner][node]=value;totals[node]+=value
        moved[owner]=moved.get(owner,0.)+abs(value-original[i])/2
    for node,mass in totals.items():graph.nodes[node]['options']['nodeWeight']=mass
    return dict(moved_mass_kg=sum(moved.values()),moved_by_component_kg=moved,
                minimum_donor_mass_kg=minimum_donor_mass,normalized_moment_residual=residual,
                remaining_support_shortfall_kg=best,frozen_split_owners=sorted(frozen),
                scope='Each existing component mass, COM and inertia retained before separately reported ballast; node positions, joints and wheel rings unchanged.')
