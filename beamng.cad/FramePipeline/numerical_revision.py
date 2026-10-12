"""Refit numerical suspension/frame constraints in an immutable, verified vehicle.

Uses the normal generation fitter; no new nodes, load paths, CAD geometry, mass,
alignment, actuator targets or coilover changes. Diagnostic until native tests.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

from frame_harness.build import node_table
from rigid_revision import refit
from rigid_bracing import budget_connections
from vehicle_revisions import load_baseline,package_revision,canonical


def condition(part,manifest,frequency,members='all',frame_priority=1.,frame_frequency=None,front_load_path_frequency=None,frame_only=False):
    if members not in ('all','upper','lower'):raise ValueError('Wishbone members must be all, upper or lower')
    step_limit=float(manifest['template_definition']['parameters'].get('numerical_step_limit',3.2))
    if not math.isfinite(step_limit) or not 2<=step_limit<=3.6:
        raise ValueError('Experimental assembled step limit must be in [2,3.6]; native stability verification is required')
    coupled_frequency=manifest['template_definition']['parameters'].get('coupled_front_frequency_hz')
    if frame_only and (frame_frequency is None or front_load_path_frequency is not None or coupled_frequency is not None):
        raise ValueError('Frame-only conditioning requires explicit frame frequency and no front/coupled refit')
    if coupled_frequency is not None and (frame_frequency is None or front_load_path_frequency is None):
        raise ValueError('Coupled front fit requires explicit frame and front load-path settings')
    original=copy.deepcopy(part);changed=[];reports={}
    frame=set()
    if frame_priority!=1 or frame_frequency is not None:
        if manifest.get('frame_reference',{}).get('mode')!='rigid_reference':
            raise ValueError('Pivot priority can only refit an explicit numerical rigid frame reference')
        from frame_reference import fit
        frame=set(manifest['chassis_nodes'])
        options,reports['_frame_reference']=fit(part,manifest['chassis_nodes'],frame_frequency if frame_frequency is not None else manifest['frame_reference']['requested_frequency_hz'],frame_priority)
        changed.extend(options)
    owners=[owner for owner,role in manifest['component_roles'].items() if role and role.endswith('_wishbone') and (members=='all' or role.endswith('_'+members+'_wishbone'))]
    if frame_only:owners=[]
    elif not owners:raise ValueError('No wishbones in the physical baseline')
    front_owners=[];ties=set()
    if front_load_path_frequency is not None:
        if not math.isfinite(front_load_path_frequency) or not 100<=front_load_path_frequency<=500:
            raise ValueError('Front load-path frequency must be in [100,500] Hz')
        for role in ('fl_upright','fr_upright'):
            found=[o for o,r in manifest['component_roles'].items() if r==role]
            if len(found)!=1:raise ValueError('Front load-path conditioning requires one '+role)
            front_owners.extend(found)
        owners.extend(front_owners)
    for owner in owners:
        parameters=manifest['template_definition']['parameters']
        damping_budget=parameters.get('rigid_damping_budget',2.) if owner in front_owners else parameters.get('wishbone_damping_budget',parameters.get('rigid_damping_budget',2.))
        options,reports[owner]=refit(part,manifest['mass_allocations'],owner,frequency=front_load_path_frequency if owner in front_owners else frequency,
            damping_budget=damping_budget,
            priority_nodes=list(manifest['numerical_mass']['nodes']),
            priority=manifest['template_definition']['parameters'].get('wishbone_loaded_priority',1.))
        if owner not in front_owners and parameters.get('wishbone_shared_edge_fit',False):
            # The chassis owns the edge joining an arm's two inner pivots.
            # Fit only the constraints this member can actually change; fitting
            # a complete triangle and then discarding its shared edge spends
            # part of the local frequency budget on an unexported coefficient.
            from coupled_rigidity import fit as member_fit
            reports[owner]['owned_constraint_fit']=member_fit(part,options,frequency)
        changed.extend(options)
    if front_load_path_frequency is not None:
        nodes=node_table(part);steering=[]
        for corner in ('FL','FR'):
            points=manifest['wheels'][corner]['hardpoint_nodes'];pair=frozenset((points['tie_inner'],points['tie_outer']))
            matches=[r for r in part.get('hydros',[])[1:] if isinstance(r,list) and frozenset(r[:2])==pair]
            if len(matches)!=1 or matches[0][-1].get('inputSource')!='steering_input' or matches[0][-1].get('beamType','|NORMAL')!='|NORMAL':
                raise ValueError('Front load-path conditioning requires one normal equivalent steering hydro per corner')
            if any(isinstance(r,list) and frozenset(r[:2])==pair for r in part['beams'][1:]):
                raise ValueError('Ambiguous parallel steering constraint')
            row=matches[0];ma,mb=[nodes[n]['options']['nodeWeight'] for n in row[:2]];reduced=ma*mb/(ma+mb)
            row[-1]['beamSpring']=reduced*(2*math.pi*front_load_path_frequency)**2
            changed.append(row[-1]);ties.add(pair)
            steering.append(dict(corner=corner,nodes=row[:2],requested_frequency_hz=front_load_path_frequency,requested_spring_n_m=row[-1]['beamSpring']))
        reports['_steering_links']=steering
    # Coupled coilover coefficients must remain untouched. Their groups are not
    # adjustable in this revision; reject overlap rather than retuning a spring.
    groups=part.pop('cadConstraintGroups',None)
    try:
        selected={id(v) for v in changed}
        for group in (groups or {}).values():
            for section,pairs in group.items():
                for pair in pairs:
                    if any(isinstance(row,list) and set(row[:2])==set(pair) and id(row[-1]) in selected
                           for row in part.get(section,[])[1:]):
                        raise ValueError('Rigid revision overlaps a coupled physical spring')
        if coupled_frequency is not None:
            from coupled_rigidity import fit as coupled_fit
            reports['_coupled_front']=coupled_fit(part,changed,float(coupled_frequency),manifest['template_definition']['parameters'].get('coupled_fit_objective','isotropic'),manifest)
        budget=budget_connections(part,node_table(part),changed,limit=step_limit)
    finally:
        if groups is not None:part['cadConstraintGroups']=groups
    # Only selected existing coefficients and internal member torsionbars vary.
    allowed={'beams','torsionbars','hydros'}
    if {k:v for k,v in part.items() if k not in allowed}!={k:v for k,v in original.items() if k not in allowed}:
        raise ValueError('Numerical revision changed physical setup')
    def expanded(rows):
        defaults={};result=[]
        for row in rows[1:]:
            if isinstance(row,dict):defaults.update(row)
            else:result.append(row[:2]+[defaults|(row[-1] if isinstance(row[-1],dict) else {})])
        return result
    for section in ('beams','hydros'):
        before_rows,after_rows=expanded(original.get(section,[[]])),expanded(part.get(section,[[]]))
        if len(after_rows)!=len(before_rows):raise ValueError('Numerical revision added beams')
        for before,after in zip(before_rows,after_rows):
            if before==after:continue
            if not isinstance(before,list) or before[:2]!=after[:2]:raise ValueError('Numerical revision changed topology')
            if section=='hydros':
                if frozenset(before[:2]) not in ties:raise ValueError('Numerical revision changed an unrelated actuator')
            elif not set(before[:2])<=frame and not any(set(before[:2])<=set(manifest['mass_allocations'][o]) for o in owners):
                raise ValueError('Numerical revision changed an inter-member connection')
            def fixed(row):return row[:-1]+[{k:v for k,v in row[-1].items() if k not in ('beamSpring','beamDamp')}]
            if fixed(before)!=fixed(after):raise ValueError('Numerical revision changed beam physical properties')
    return reports,budget


def build(receipt,output,frequency,members='all',frame_priority=1.,frame_frequency=None,front_load_path_frequency=None,damping_budget=None,step_limit=None,coupled_frequency=None,coupled_objective='isotropic',shared_edge_fit=False,frame_only=False):
    if frame_only and (damping_budget is not None or step_limit is not None or coupled_frequency is not None or shared_edge_fit):
        raise ValueError('Frame-only revisions must preserve baseline member tuning and step-limit settings')
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes())
    files=[name for name in contents if name.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('Numerical revision requires one assembled vehicle part')
    name=files[0];parts=json.loads(contents[name])
    if len(parts)!=1:raise ValueError('Ambiguous assembled vehicle part')
    part=next(iter(parts.values()))
    if damping_budget is not None:manifest['template_definition']['parameters']['wishbone_damping_budget']=float(damping_budget)
    if step_limit is not None:manifest['template_definition']['parameters']['numerical_step_limit']=float(step_limit)
    if shared_edge_fit:manifest['template_definition']['parameters']['wishbone_shared_edge_fit']=True
    if coupled_frequency is not None:manifest['template_definition']['parameters']['coupled_front_frequency_hz']=float(coupled_frequency)
    if coupled_frequency is not None:manifest['template_definition']['parameters']['coupled_fit_objective']=coupled_objective
    apply_conditioning(part,manifest,float(frequency),members,frame_priority,frame_frequency,front_load_path_frequency,frame_only)
    if frame_only:
        manifest['template_definition']['parameters']['frame_refinement_frequency_hz']=frame_frequency
        manifest['template_definition']['parameters']['frame_refinement_pivot_priority']=frame_priority
    else:
        manifest['template_definition']['parameters']['wishbone_frequency_hz']=float(frequency)
        manifest['template_definition']['parameters']['wishbone_frequency_members']=members
        manifest['template_definition']['parameters']['frame_pivot_priority']=frame_priority
        if frame_frequency is not None:manifest['template_definition']['parameters']['conditioned_frame_frequency_hz']=frame_frequency
    if front_load_path_frequency is not None:manifest['template_definition']['parameters']['front_load_path_frequency_hz']=front_load_path_frequency
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest['numerical_revision']=dict(baseline_physics_sha256=snapshot['sha256'],frame_only=frame_only,wishbone_frequency_hz=frequency,members=members,frame_pivot_priority=frame_priority,frame_frequency_hz=frame_frequency,front_load_path_frequency_hz=front_load_path_frequency,wishbone_damping_budget=manifest['template_definition']['parameters'].get('wishbone_damping_budget'),numerical_step_limit=manifest['connection_budget']['step_limit'],
        scope='Existing rigid constraints, optional numerical frame and front upright/steering fit; geometry, mass, coilovers, actuator targets and joint topology unchanged')
    manifest.pop('verification',None)
    manifest.pop('physical_evidence',None)
    manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[name]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'numerical-revision.json':canonical(manifest['numerical_revision'])})
    for file in ('numerical_revision.py','rigid_revision.py','rigid_bracing.py','frame_reference.py','coupled_rigidity.py','motion_objective.py'):
        provenance['numerical-generator/'+file]=Path(__file__).with_name(file).read_bytes()
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during numerical revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Numerical rigidity revision; source CAD mechanism unchanged; native qualification pending')


def apply_conditioning(part,manifest,frequency,members='all',frame_priority=1.,frame_frequency=None,front_load_path_frequency=None,frame_only=False):
    """Shared final stage for full generation and immutable numerical trials.

    Apply after the ordinary assembled budget. Frame and front load-path fits
    require explicit options; all other components and coilover laws stay fixed.
    """
    reports,budget=condition(part,manifest,float(frequency),members,frame_priority,frame_frequency,front_load_path_frequency,frame_only)
    if '_frame_reference' in reports:manifest['frame_reference']=reports.pop('_frame_reference')
    if '_steering_links' in reports:manifest['front_steering_conditioning']=reports.pop('_steering_links')
    if '_coupled_front' in reports:manifest['coupled_front_conditioning']=reports.pop('_coupled_front')
    manifest['rigid_refits'].update(reports)
    manifest.setdefault('base_connection_budget',manifest['connection_budget'])
    manifest['connection_budget']=budget
    manifest['torsionbars']=part.get('torsionbars',[])[1:]
    key='frame_only_conditioning' if frame_only else 'wishbone_conditioning'
    manifest[key]=dict(frequency_hz=float(frequency),members=members,frame_only=frame_only,frame_pivot_priority=frame_priority,frame_frequency_hz=frame_frequency,front_load_path_frequency_hz=front_load_path_frequency,stage='after assembled baseline',
        scope='Existing rigid constraints and optional numerical frame/upright/steering fit; CAD geometry, masses, coilovers and actuator targets unchanged')
