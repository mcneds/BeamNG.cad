"""Limit numerical damping inside explicit permanently fixed assemblies.

Keep every stiffness, mass, connection and physical suspension law unchanged.
Only unbreakable normal constraints belonging to the fixed contract qualify.
"""
import copy,math
from frame_harness.build import node_table
from rigid_bracing import budget_connections


def apply(part,manifest,limit=3.1):
    if not math.isfinite(limit) or not 2.9<=limit<3.2:raise ValueError('Fixed damping envelope limit must be in [2.9,3.2)')
    original=copy.deepcopy(part);shadow=copy.deepcopy(part);shadow.pop('cadConstraintGroups',None)
    contracts=[(set(c['nodes']),set(c['parents'])) for c in manifest.get('fixed_attachment_contract',{}).values()]
    defaults={};selected=[]
    for i,row in enumerate(shadow['beams'][1:],1):
        if isinstance(row,dict):defaults.update(row);continue
        pair=set(row[:2]);options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
        if not any(pair&children and pair<=children|parents for children,parents in contracts):continue
        if options.get('beamType','|NORMAL')!='|NORMAL' or options.get('breakGroup'):continue
        if min(options.get('beamStrength',0),options.get('beamDeform',0))<1e20:continue
        if options.get('dampCutoffHz',0):raise ValueError('Fixed damping screen requires an unfiltered baseline')
        damping=float(options.get('beamDamp',0.))
        if damping<=0:continue
        if len(row)!=3 or not isinstance(row[-1],dict):raise ValueError('Explicit fixed constraint options required')
        shadow['beams'][i]=row[:2]+[options|{'beamDamp':0.}]
        selected.append((i,row[:2],damping))
    if not selected:raise ValueError('No eligible fixed numerical damping constraints')
    adjustable=[]
    for i,pair,damping in selected:
        options=dict(beamType='|NORMAL',beamSpring=0.,beamDamp=damping,dampCutoffHz=0.)
        shadow['beams'].append(pair+[options]);adjustable.append(options)
    budget=budget_connections(shadow,node_table(shadow),adjustable,limit=limit)
    if any(shadow.get(k)!=original.get(k) for k in original if k not in ('beams','cadConstraintGroups')):
        raise ValueError('Damping screen changed a different physical constraint')
    changes=[]
    for (i,pair,before),options in zip(selected,adjustable):
        after=options['beamDamp']
        if after>before+1e-12:raise ValueError('Fixed damping cap increased damping')
        part['beams'][i][-1]['beamDamp']=after
        if after!=before:changes.append(dict(nodes=pair,before_ns_m=before,after_ns_m=after))
    report=dict(screen=budget,eligible_constraints=len(selected),changes=changes,
        scope='Numerical damping on explicit fixed unbreakable normal constraints only; all spring coefficients, masses, geometry, strengths and moving joints unchanged. Native verification required.')
    manifest['fixed_strain_damping']=report
    return report
