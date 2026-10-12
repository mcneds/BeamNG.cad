"""Audited bilateral stiffness ties for explicitly symmetric frame graphs.

The hull setting alone is insufficient: the independent circular-member CAD
reference, body mass and assigned materials must also match across the plane.
Asymmetric or unsupported references keep their unconstrained material fit.
"""
import numpy as np
from .build import node_table,beam_table
from .torsion import table as torsion_table


def constraint_groups(part,sections,audits,materials):
    declaration=part.get('cadGraphSymmetry')
    count=len(beam_table(part))+len(torsion_table(part))
    independent=np.arange(count)
    report=dict(applied=False,position_tolerance_m=.0001,property_relative_tolerance=.001)
    def skip(reason):return independent,report|dict(reason=reason)
    if not declaration:return skip('No symmetric graph declared')
    if not sections or set(sections)!={a['name'] for a in audits}:
        return skip('Complete independently audited member sections required')
    center=float(declaration['center_x_m']);sign=np.array([-1,1,1])
    def reflect(x):return np.asarray(x)*sign+[2*center,0,0]
    audit={a['name']:a for a in audits};body_pairs={};maximum_path_error=0.
    for name,section in sections.items():
        if 'circular' not in section.get('method','').lower():
            return skip('Reflection ties currently require circular member sections')
        path=np.array(section.get('path',[section['a'],section['b']]))
        target=reflect(path);candidates=[]
        for other,value in sections.items():
            other_path=np.array(value.get('path',[value['a'],value['b']]))
            if other_path.shape!=target.shape:continue
            error=min(np.max(np.linalg.norm(target-other_path,axis=1)),np.max(np.linalg.norm(target-other_path[::-1],axis=1)))
            if error<=report['position_tolerance_m']:candidates.append((error,other))
        if not candidates:return skip('A CAD member has no reflected path: '+name)
        path_error,other=min(candidates);value=sections[other]
        maximum_path_error=max(maximum_path_error,float(path_error))
        # Circular-section principal axes may swap under reflection. Compare
        # their unordered moments rather than their arbitrary Y/Z labels.
        if not np.allclose(sorted((section['Iy_m4'],section['Iz_m4'])),
                           sorted((value['Iy_m4'],value['Iz_m4'])),rtol=report['property_relative_tolerance'],atol=0):
            return skip('Reflected CAD bending moments differ: '+name)
        for key in ('area_m2','J_m4','radius_m'):
            if abs(section[key]-value[key])>report['property_relative_tolerance']*max(abs(section[key]),abs(value[key])):
                return skip('Reflected CAD section properties differ: '+name)
        for key in ('volume_m3','native_mass_kg'):
            if key in audit[name] and key in audit[other]:
                a,b=audit[name][key],audit[other][key]
                if abs(a-b)>report['property_relative_tolerance']*max(abs(a),abs(b)):
                    return skip('Reflected CAD mass/volume differs: '+name)
        for key in ('density_kg_m3','young_pa','poisson','yield_pa','ultimate_pa'):
            a,b=materials[name][key],materials[other][key]
            if not np.isclose(a,b,rtol=1e-8,atol=0):return skip('Reflected assigned materials differ: '+name)
        body_pairs[name]=other
    if any(body_pairs.get(other)!=name for name,other in body_pairs.items()):
        return skip('Reflected CAD body correspondence is ambiguous')
    nodes=node_table(part);names=list(nodes);xyz=np.array([nodes[n]['position'] for n in names]);mapping={}
    for name,position in zip(names,xyz):
        distance=np.linalg.norm(xyz-reflect(position),axis=1);i=int(np.argmin(distance))
        if distance[i]<1e-7:mapping[name]=names[i]
    constraints=[('beam',tuple(sorted((b['a'],b['b'])))) for b in beam_table(part)]
    def angular_key(ids):
        a,b,c,d=ids
        return min((a,b,c,d),(d,b,c,a),(a,c,b,d),(d,c,b,a))
    constraints += [('angle',angular_key(t['nodes'])) for t in torsion_table(part)]
    indices={key:i for i,key in enumerate(constraints)};labels=[];groups={};paired=0
    for i,(kind,ids) in enumerate(constraints):
        key=i
        if all(n in mapping for n in ids):
            reflected=[mapping[n] for n in ids]
            other=indices.get((kind,tuple(sorted(reflected)) if kind=='beam' else angular_key(reflected)))
            if other is not None:key=min(i,other);paired+=int(i!=other)
        if key not in groups:groups[key]=len(groups)
        labels.append(groups[key])
    return np.array(labels),report|dict(applied=paired>0,body_pairs=body_pairs,
        maximum_path_error_m=maximum_path_error,
        tied_constraints=paired,independent_coefficients=len(groups),
        scope='Stiffness/damping symmetry within audited reference tolerances; CAD mass moments are unchanged')


def average_groups(values,groups):
    values=np.asarray(values,float)
    return (np.bincount(groups,weights=values)/np.bincount(groups))[groups]
