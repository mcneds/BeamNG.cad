"""Positive stiffness increments on existing numerical front/frame constraints.

Unlike a refit, this cannot weaken an existing spring or add a load path. The
assembled rest-pose screen limits increments only. Native checks remain required.
"""
import copy,hashlib,json,math
from pathlib import Path
from frame_harness.build import node_table
from rigid_bracing import budget_connections
from vehicle_revisions import canonical,load_baseline,package_revision

ROLES={'fl_upper_wishbone','fl_lower_wishbone','fr_upper_wishbone','fr_lower_wishbone','fl_upright','fr_upright'}


def apply(part,manifest,factor=1.5,limit=3.6,selection='front'):
    if not math.isfinite(factor) or not 1<factor<=3:raise ValueError('Stiffness growth factor must be in (1,3]')
    if not math.isfinite(limit) or not 3.2<=limit<=3.6:raise ValueError('Experimental step limit must be in [3.2,3.6]')
    if selection not in ('front','frame','members'):raise ValueError('Choose front, frame or members')
    if manifest.get('monotone_rigidity'):raise ValueError('Start from a baseline without a monotone revision')
    groups=[]
    if selection in ('front','frame'):
        if manifest.get('frame_reference',{}).get('mode')!='rigid_reference':raise ValueError('Requires an explicit numerical rigid frame')
        groups.append(set(manifest['chassis_nodes']))
    if selection in ('front','members'):
        for owner,role in manifest['component_roles'].items():
            if role in ROLES:
                if owner not in manifest['rigid_refits']:raise ValueError('Front member has no numerical rigid fit')
                groups.append(set(manifest['mass_allocations'][owner]))
    original=copy.deepcopy(part);shadow=copy.deepcopy(part)
    protected={frozenset(pair) for group in shadow.pop('cadConstraintGroups',{}).values() for pairs in group.values() for pair in pairs}
    ties=[]
    if selection=='front':
        ties=[{manifest['wheels'][c]['hardpoint_nodes'][k] for k in ('tie_inner','tie_outer')} for c in ('FL','FR')]
    chosen=[]
    for section in ('beams','hydros','torsionbars'):
        defaults={}
        for index,row in enumerate(part.get(section,[])[1:],1):
            if isinstance(row,dict):defaults.update(row);continue
            count=4 if section=='torsionbars' else 2;ids=row[:count]
            if not any(set(ids)<=g for g in (ties if section=='hydros' else groups)):continue
            if len(row)!=count+1 or not isinstance(row[-1],dict):raise ValueError('Explicit numerical constraint options required')
            options=defaults|row[-1]
            key='spring' if section=='torsionbars' else 'beamSpring'
            if section!='torsionbars' and (options.get('beamType','|NORMAL')!='|NORMAL' or frozenset(ids) in protected):
                raise ValueError('Stiffness growth overlaps a physical spring or stop')
            if section=='hydros' and options.get('inputSource')!='steering_input':raise ValueError('Unsupported steering actuator')
            spring=float(options.get(key,0.))
            if not math.isfinite(spring) or spring<0:raise ValueError('Invalid existing numerical spring')
            if spring==0:continue
            chosen.append(dict(section=section,index=index,nodes=ids,key=key,before=spring))
    if not chosen:raise ValueError('No existing numerical constraints selected')
    adjustable=[]
    for entry in chosen:
        # Add analysis-only columns. Only their positive increments can be
        # reduced; existing K and all C remain fixed throughout the screen.
        if entry['section']=='torsionbars':options=dict(spring=entry['before']*(factor-1),damp=0.)
        else:options=dict(beamType='|NORMAL',beamSpring=entry['before']*(factor-1),beamDamp=0.,dampCutoffHz=0.)
        shadow[entry['section']].append(entry['nodes']+[options]);adjustable.append(options)
    budget=budget_connections(shadow,node_table(shadow),adjustable,limit=limit)
    for section in original:
        if section in ('beams','hydros','torsionbars'):
            if shadow[section][:len(original[section])]!=original[section]:raise ValueError('Screen altered a baseline constraint')
        elif section!='cadConstraintGroups' and shadow.get(section)!=original[section]:raise ValueError('Screen changed the physical setup')
    for entry,options in zip(chosen,adjustable):
        delta=options[entry['key']]
        if delta<0 or not math.isfinite(delta):raise ValueError('Invalid stiffness increment')
        part[entry['section']][entry['index']][-1][entry['key']]=entry['before']+delta
        entry['after']=entry['before']+delta
    report=dict(requested_factor=factor,selection=selection,screen=budget,constraints=chosen,
        scope='Positive increments to existing numerical front/frame springs only. No decreases, additional constraints, mass, geometry, damping, strength or physical spring/actuator target changes. Rest-pose screening is not native qualification.')
    manifest['monotone_rigidity']=report
    manifest['prior_to_monotone_increment_budget']=manifest.get('connection_budget')
    manifest['connection_budget']=budget
    manifest['torsionbars']=part.get('torsionbars',[])[1:]
    return report


def build(receipt,output,factor=1.5,limit=3.6,selection='front'):
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes())
    files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    apply(next(iter(parts.values())),manifest,factor,limit,selection)
    manifest['template_definition']['parameters'].update(rigid_stiffness_growth_factor=factor,rigid_stiffness_growth_limit=limit,rigid_stiffness_growth_selection=selection)
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest.pop('verification',None);manifest.pop('physical_evidence',None)
    manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'monotone-rigidity.json':canonical(manifest['monotone_rigidity'])})
    for file in ('monotone_rigidity.py','rigid_bracing.py'):
        provenance['numerical-generator/'+file]=Path(__file__).with_name(file).read_bytes()
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Positive numerical stiffness increments; native qualification pending')
