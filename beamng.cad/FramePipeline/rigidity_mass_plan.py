"""Apply a source-bound numerical stiffness/mass plan without changing hardware laws."""
import copy,hashlib,json,math
from pathlib import Path
import numpy as np
from scipy.sparse.linalg import eigsh
from angular_screen import matrices,symmetric_step_operator
from frame_harness.build import node_table
from vehicle_revisions import canonical,load_baseline,package_revision


def constraint_factor(manifest,ids,section,factor,upper_factor=None,upright_factor=None):
    """Optional extra rigidity for upper arms/locators and front upright bodies.

    This classifies existing numerical constraints only. It never selects a new
    edge or relaxes the caller's physical-spring and cross-joint guards.
    """
    for label,value in [('Upper-arm',upper_factor),('Upright',upright_factor)]:
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or
                not math.isfinite(value) or not factor<=value<=3):
            raise ValueError(label+' factor must be finite, at least the base factor and at most 3')
    if section=='hydros':return factor
    ids=set(ids)
    if upright_factor is not None:
        for owner,role in manifest['component_roles'].items():
            if role in ('fl_upright','fr_upright') and ids<=set(manifest['mass_allocations'][owner]):
                if owner not in manifest['rigid_refits']:raise ValueError('Upright override requires numerical rigid fit')
                return upright_factor
    if upper_factor is None:return factor
    for owner,role in manifest['component_roles'].items():
        if role in ('fl_upper_wishbone','fr_upper_wishbone') and ids<=set(manifest['mass_allocations'][owner]):
            if owner not in manifest['rigid_refits']:raise ValueError('Upper-arm override requires numerical rigid fit')
            return upper_factor
    frame=set(manifest['chassis_nodes'])
    anchors={w['hardpoint_nodes'][key] for corner,w in manifest['wheels'].items() if corner in ('FL','FR')
             for key in ('upper_inner_front','upper_inner_rear') if key in w['hardpoint_nodes']}
    if ids<=frame and ids&anchors:
        if manifest.get('frame_reference',{}).get('mode')!='rigid_reference':raise ValueError('Upper-mount override requires numerical frame')
        return upper_factor
    return factor


def refresh_load_metadata(manifest,delta_allocations):
    from suspension_loads import corner_masses,effective_moving_mass,ride_reference
    from vehicle_templates import TemplateModel,Mechanism
    wheels=manifest['wheels'];order=list(wheels);definition=manifest['template_definition'];model=TemplateModel(definition)
    roles={r:o for o,r in manifest['component_roles'].items() if r};positions={n:np.array(v['position']) for n,v in manifest['nodes'].items()}
    mass=np.array([v['mass_kg'] for v in manifest['nodes'].values()]);total=float(sum(mass));moment=mass@np.array(list(positions.values()))
    hubs=np.array([(positions[wheels[c]['nodes']['axis_in']]+positions[wheels[c]['nodes']['axis_out']])/2 for c in order])
    for c,hub in zip(order,hubs):total+=wheels[c]['wheel_mass_kg'];moment+=wheels[c]['wheel_mass_kg']*hub
    support=corner_masses(hubs,total,moment/total)
    for corner,normal in zip(order,support):
        mechanism=Mechanism(model,corner);height,extension,_=ride_reference(model,corner,manifest.get('alignment',{}));step=1e-4
        low,lo=mechanism.solve(height-step,extension);high,hi=mechanism.solve(height+step,extension)
        tl=mechanism.component_transforms(low,extension);th=mechanism.component_transforms(high,extension);derivative={k:(th[k]-tl[k])/(2*step) for k in tl}
        prefix=corner.lower();bodies={};points={};hp=wheels[corner]['hardpoint_nodes']
        for suffix,key in [('upper_wishbone','upper_arm'),('lower_wishbone','lower_arm'),('upright','upright'),('trailing_arm','trailing_arm'),('wheel','wheel')]:
            owner=roles.get(prefix+'_'+suffix)
            if owner in delta_allocations and key in derivative:bodies[owner]=derivative[key]
        for suffix,keys in [('tie_rod',('tie_inner','tie_outer')),('toe_link',('tie_inner','tie_outer')),('spring_damper',('shock_top','shock_bottom')),
                            ('upper_radius_rod',('radius_upper_inner','radius_upper_outer')),('lower_radius_rod',('radius_lower_inner','radius_lower_outer'))]:
            owner=roles.get(prefix+'_'+suffix)
            if owner in delta_allocations:
                points[owner]={hp[key]:float((hi[key][2]-lo[key][2])/(2*step)) for key in keys if hp[key] in delta_allocations[owner]}
        extra=effective_moving_mass(delta_allocations,positions,bodies,points)
        unsprung=wheels[corner]['effective_unsprung_mass_kg']+extra;sprung=float(normal-unsprung)
        if sprung<=0:raise ValueError('Mass plan leaves no positive sprung support load')
        wheels[corner].update(static_support_mass_kg=float(normal),effective_unsprung_mass_kg=unsprung,effective_sprung_mass_kg=sprung,
            static_load_method='Balanced updated numerical mass/COM; linkage gravity derivative; physical spring/damping/preload retained')
    manifest['expected_dry_mass_kg']=total


def apply(part,manifest,plan,added_limit=30.):
    if manifest.get('rigidity_mass_plan'):raise ValueError('Start from an unmodified baseline')
    if plan.get('status')!='offline_plan_only':raise ValueError('A feasible offline mass plan is required')
    if hashlib.sha256(canonical({manifest['main_part']:part})).hexdigest()!=plan['baseline_jbeam_sha256']:raise ValueError('Mass plan does not match this generated vehicle; create a fresh plan')
    if not math.isfinite(added_limit) or not 0<added_limit<=50:raise ValueError('Invalid numerical mass allowance')
    factor=float(plan['factor']);limit=float(plan['step_limit']);upper_factor=plan.get('upper_factor');upright_factor=plan.get('upright_factor')
    if not 1<factor<=3 or not 3.2<=limit<=3.6:raise ValueError('Invalid numerical growth bounds')
    if upper_factor is not None and (not isinstance(upper_factor,(int,float)) or isinstance(upper_factor,bool) or not math.isfinite(upper_factor) or not factor<=upper_factor<=3):raise ValueError('Invalid upper-arm factor')
    if upright_factor is not None and (not isinstance(upright_factor,(int,float)) or isinstance(upright_factor,bool) or not math.isfinite(upright_factor) or not factor<=upright_factor<=3):raise ValueError('Invalid upright factor')
    shadow=copy.deepcopy(part);updated=copy.deepcopy(manifest);nodes=node_table(shadow);groups=[]
    if manifest.get('frame_reference',{}).get('mode')=='rigid_reference':groups.append(set(manifest['chassis_nodes']))
    for owner,role in manifest['component_roles'].items():
        if role and role.startswith(('fl_','fr_')) and role.endswith(('_wishbone','_upright')) and owner in manifest['rigid_refits']:groups.append(set(manifest['mass_allocations'][owner]))
    protected={frozenset(pair) for group in part.get('cadConstraintGroups',{}).values() for pairs in group.values() for pair in pairs};seen=set();eligible=set()
    for change in plan['changed_constraints']:
        section=change['section'];index=change['index']
        if section not in ('beams','hydros','torsionbars') or index<1 or (section,index) in seen:raise ValueError('Invalid numerical constraint selection')
        seen.add((section,index));row=shadow[section][index];count=4 if section=='torsionbars' else 2;key='spring' if section=='torsionbars' else 'beamSpring'
        if not isinstance(row,list) or len(row)!=count+1 or not isinstance(row[-1],dict):raise ValueError('Explicit constraint options required')
        ids=set(row[:count]);eligible.update(ids)
        if section=='hydros':
            if row[-1].get('inputSource')!='steering_input' or not any(ids=={w['hardpoint_nodes'][k] for k in ('tie_inner','tie_outer')} for c,w in manifest['wheels'].items() if c.startswith('F')):raise ValueError('Unrelated actuator in plan')
        elif not any(ids<=g for g in groups):raise ValueError('Mass plan crosses a moving joint')
        if section!='torsionbars' and (row[-1].get('beamType','|NORMAL')!='|NORMAL' or frozenset(ids) in protected):raise ValueError('Mass plan alters a physical spring')
        before=float(row[-1][key]);after=float(change['after'])
        expected_factor=constraint_factor(manifest,ids,section,factor,upper_factor,upright_factor)
        if change['key']!=key or before!=change['before'] or not math.isclose(after,before*expected_factor,rel_tol=1e-12):raise ValueError('Constraint plan coefficient mismatch')
        row[-1][key]=after
    delta_allocations={};mass_changes=[];seen=set();row_by_name={r[0]:r for r in shadow['nodes'][1:] if isinstance(r,list)}
    for change in plan['nodes']:
        name=change['name'];before=float(nodes[name]['options']['nodeWeight']);after=float(change['after_kg'])
        if name not in eligible or name in seen or before!=change['before_kg'] or not math.isfinite(after) or not before<=after<=4*before:raise ValueError('Invalid numerical mass increment')
        seen.add(name);extra=after-before;owners={o:v[name] for o,v in manifest['mass_allocations'].items() if v.get(name,0)>0}
        if not math.isclose(sum(owners.values()),before,abs_tol=1e-8,rel_tol=1e-8):raise ValueError('Mass ownership incomplete')
        row_by_name[name][-1]['nodeWeight']=after;updated['nodes'][name]['mass_kg']=after
        for owner,value in owners.items():
            delta=extra*value/before;updated['mass_allocations'][owner][name]+=delta;delta_allocations.setdefault(owner,{})[name]=delta
        mass_changes.append(dict(name=name,before_kg=before,after_kg=after,added_kg=extra))
    added=sum(v['added_kg'] for v in mass_changes)
    declared_limit=plan.get('added_budget_kg')
    if declared_limit is not None and (not math.isfinite(declared_limit) or not 0<declared_limit<=50 or added>declared_limit+1e-8):raise ValueError('Mass plan exceeds its declared budget')
    if added>added_limit+1e-8 or not math.isclose(added,plan['total_added_kg'],abs_tol=1e-5):raise ValueError('Mass plan exceeds its allowance or accounting differs')
    k,c=matrices(shadow,node_table(shadow));operator=symmetric_step_operator(k,c)
    peak=float(eigsh(operator,k=1,which='LA',return_eigenvectors=False,tol=1e-9,v0=np.random.default_rng(0).normal(size=operator.shape[0]))[0])
    if peak>limit+1e-7:raise ValueError('Reconstructed mass plan exceeds timestep screen: '+str(peak))
    numerical=updated['numerical_mass'];numerical['added_mass_kg']+=added;numerical['material_mass_equivalent']=False
    for owner,values in delta_allocations.items():
        extra=sum(values.values());numerical['added_by_component_kg'][owner]=numerical['added_by_component_kg'].get(owner,0)+extra
        if owner in updated['component_reports']:updated['component_reports'][owner]['numerical_added_mass_kg']=updated['component_reports'][owner].get('numerical_added_mass_kg',0)+extra
    for row in mass_changes:
        if row['name'] in numerical['nodes']:
            item=numerical['nodes'][row['name']];item['simulated_mass_kg']=row['after_kg'];item['added_mass_kg']+=row['added_kg'];item['reasons'].append('numerical rigidity timestep plan')
            for owner,values in delta_allocations.items():
                if row['name'] in values:item['added_by_component_kg'][owner]=item['added_by_component_kg'].get(owner,0)+values[row['name']]
    numerical['spectral_mass_increments']=mass_changes
    refresh_load_metadata(updated,delta_allocations)
    if not math.isclose(updated['expected_dry_mass_kg'],manifest['expected_dry_mass_kg']+added,abs_tol=1e-6):raise ValueError('Vehicle mass accounting differs')
    updated['torsionbars']=shadow.get('torsionbars',[])[1:]
    updated['prior_to_mass_plan_budget']=updated['connection_budget'];updated['connection_budget']=dict(step_seconds=.0005,step_limit=limit,final_step_eigenvalue=peak,strategy='Verified prescribed stiffness and additive mass plan')
    updated['rigidity_mass_plan']=dict(plan=plan,added_mass_kg=added,screen_eigenvalue=peak,scope=__doc__)
    updated['limitations']=[v for v in updated['limitations'] if not v.startswith('Numerical support mass adds ')]
    updated['limitations'].append(f"Numerical support mass adds {numerical['added_mass_kg']:.6f} kg beyond CAD mass, including {added:.6f} kg from the stiffness timestep plan. Physical coilover and brake coefficients are unchanged; mass/material equivalence remains unqualified.")
    part.clear();part.update(shadow);manifest.clear();manifest.update(updated)
    return updated['rigidity_mass_plan']


def build(receipt,plan_path,output,added_limit=30.):
    if Path(output).exists():raise FileExistsError('Use a fresh output directory')
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt);plan=json.loads(Path(plan_path).read_bytes())
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes());files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    apply(next(iter(parts.values())),manifest,plan,added_limit)
    manifest['template_definition']['parameters'].update(rigidity_mass_plan_path=str(Path(plan_path).resolve()),rigidity_mass_added_limit_kg=added_limit)
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest();manifest.pop('verification',None);manifest.pop('physical_evidence',None);manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts);provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'rigidity-mass-plan.json':canonical(plan),'numerical-generator/rigidity_mass_plan.py':Path(__file__).read_bytes()})
    for name in ('angular_screen.py','angular_beams.py','rigid_bracing.py','mass_motion.py','suspension_inertia.py'):
        provenance['numerical-generator/'+name]=Path(__file__).with_name(name).read_bytes()
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Prescribed numerical stiffness with reported added mass; native qualification pending')
