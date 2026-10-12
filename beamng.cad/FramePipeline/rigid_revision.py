"""Refit an existing rigid body's internal constraints after mass assembly.

Use final shared physical masses, without moving nodes, adding mass or bridging
separate suspension members. Existing shared hinge edges remain untouched.
"""
import itertools
import numpy as np
from frame_harness.build import node_table
from rigid_bracing import reinforce


def refit(part, allocations, owner, *, angular=True, damping_budget=2.,priority_nodes=(),priority=1.,frequency=400.):
    nodes=node_table(part); names=list(allocations[owner]); own=set(names)
    if len(names)<3:raise ValueError('Rigid refit needs at least three noncollinear points')
    xyz=np.array([nodes[n]['position'] for n in names],dtype=float)
    if np.linalg.matrix_rank(xyz-xyz.mean(0),tol=1e-8)<2:raise ValueError('Rigid refit needs noncollinear points')
    masses=np.array([nodes[n]['options']['nodeWeight'] for n in names],dtype=float)
    pairs=list(itertools.combinations(range(len(names)),2))
    edges={}
    for row in part.get('beams',[])[1:]:
        if isinstance(row,list) and set(row[:2])<=own:
            if row[-1].get('beamType','|NORMAL')!='|NORMAL':
                raise ValueError('Rigid component contains a moving spring or stop')
            edges.setdefault(frozenset(row[:2]),[]).append(row)
    if set(edges)!={frozenset((names[a],names[b])) for a,b in pairs}:
        raise ValueError('Rigid refit requires an existing complete internal graph')
    # Even a single shared edge can be a neighbouring member's constraint.
    # Preserve it rather than attempting to infer its owner from row order.
    shared={key for key in edges if any(other!=owner and key<=set(values)
                                      for other,values in allocations.items())}
    if any(len(rows)!=1 for key,rows in edges.items() if key not in shared):
        raise ValueError('Ambiguous duplicate internal edge')
    if not np.isfinite(frequency) or not 100<=frequency<=600:raise ValueError('Rigid numerical frequency must be between 100 and 600 Hz')
    springs,dampers,torsions=reinforce(xyz,pairs,masses,angular=angular,damping_budget=damping_budget,frequency=frequency,
        priority_nodes=[i for i,n in enumerate(names) if n in priority_nodes],priority=priority)
    changed=[]
    for (a,b),spring,damp in zip(pairs,springs,dampers):
        key=frozenset((names[a],names[b]))
        if key in shared:continue
        options=edges[key][0][-1]
        options.update(beamSpring=float(spring),beamDamp=float(damp));changed.append(options)
    original=part.get('torsionbars',[['id1:','id2:','id3:','id4:']])
    for row in original[1:]:
        if isinstance(row,list) and set(row[:4])<=own and any(
                other!=owner and set(row[:4])<=set(values) for other,values in allocations.items()):
            raise ValueError('Angular constraint belongs to more than one component')
    kept=original[:1]+[row for row in original[1:] if not isinstance(row,list) or not set(row[:4])<=own]
    for ids,spring,damp in torsions:
        options=dict(spring=spring,damp=damp,deform=1e30,strength=1e30)
        kept.append([*[names[i] for i in ids],options]);changed.append(options)
    part['torsionbars']=kept
    return changed,dict(owner=owner,nodes=names,shared_hinge_edges_preserved=[sorted(k) for k in sorted(shared,key=lambda k:sorted(k))],
                        allocated_mass_kg=sum(allocations[owner].values()),assembled_node_mass_kg=float(masses.sum()),
                        requested_internal_step_budget=damping_budget,
                        requested_frequency_hz=frequency,
                        loaded_node_priority=priority,priority_nodes=[n for n in names if n in priority_nodes],
                        scope='Internal rigid-body constraints only; node masses, geometry, inter-member beams and coilovers unchanged')
