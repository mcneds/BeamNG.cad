"""Experimental wheel-moment-preserving replacement of reported axle ballast.

Explicit axle masses and all mechanical coefficients stay fixed. Existing rim
mass supplies part of those masses; ring redistribution preserves the wheel's
mass, COM and inertia. Internal rim width changes, so native tire validation is
required even though pressure, contact dimensions and coefficients are frozen.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from frame_harness.build import node_table
from rigidity_mass_plan import refresh_load_metadata
from vehicle_revisions import canonical, load_baseline, package_revision


def ring_moments(options, half_span, axle_mass=0.):
    """Mass and axial/transverse inertia of symmetric rings and two axle masses."""
    count=2*options['numRays']
    hub=count*options['hubNodeWeight']; tread=count*options['nodeWeight']
    spin=hub*options['hubRadius']**2+tread*options['radius']**2
    lateral=hub*(options['hubWidth']/2)**2+tread*(options['tireWidth']/2)**2+2*axle_mass*half_span**2
    return np.array([hub+tread+2*axle_mass,spin,spin/2+lateral])


def renormalize_couplings(part, contract, wheel_inertias, parameters):
    """Retain actual coupling laws when native hub-only inertia changes.

    Drive's wheels.lua calculates powertrain inertia from wheel.nodes (hub
    rings), excluding the separately deforming tread. Its devices multiply a
    damping ratio by sqrt(spring * native inertia) at initialization.
    """
    from vehicle_drivetrain import configure_carrier
    if contract.get('template')!='cvt_rear_front_output':
        raise ValueError('Wheel reuse currently requires the audited CVT rear/front-output coupling contract')
    old=contract['carrier_coupling']
    if set(wheel_inertias)!=set(old['wheel_inertias_kg_m2']) or any(not math.isfinite(v) or v<=0 for v in wheel_inertias.values()):
        raise ValueError('Incomplete positive native wheel inertias')
    trial_part=copy.deepcopy(part);trial_contract=copy.deepcopy(contract)
    configure_carrier(trial_part,trial_contract,old['reaction_inertias_kg_m2'],wheel_inertias,parameters)
    specifications=[('clutch_coupling',part['clutch'],'lockSpring','lockDampRatio','native_inertia_kg_m2'),
        ('parking_lock',part['gearbox'],'parkLockSpring','parkLockDampRatio','native_output_inertia_kg_m2'),
        ('carrier_coupling',next(r[4] for r in part['powertrain'][1:] if r[1]=='rearCarrierTakeoff'),
         'lockSpring','lockDampRatio','secondary_inertia_kg_m2')]
    pending=[];report={}
    for key,options,spring_key,ratio_key,inertia_key in specifications:
        before=contract[key];derived=trial_contract[key];spring=options[spring_key];damp=before['damping_nm_s_rad']
        expected_spring=before['spring_nm_rad'] if key=='parking_lock' else before['lock_spring_nm_rad2']
        if not math.isclose(spring,expected_spring,rel_tol=1e-10) or not math.isclose(options[ratio_key]*math.sqrt(spring*before[inertia_key]),damp,rel_tol=1e-10):
            raise ValueError('Original coupling contract differs from its exported coefficients')
        tangent=spring if key=='parking_lock' else before['maximum_tangent_nm_rad']
        dt=before['step_seconds'];step=(dt*dt*tangent+2*dt*damp)/derived['effective_inertia_kg_m2']
        if not math.isfinite(step) or step>3.2:raise ValueError('Wheel redistribution exceeds coupling timestep bound')
        ratio=damp/math.sqrt(spring*derived[inertia_key])
        budget=copy.deepcopy(before)
        for name in ('effective_inertia_kg_m2',inertia_key,'wheel_inertias_kg_m2'):
            if name in derived:budget[name]=derived[name]
        budget['step_eigenvalue']=step
        budget['frequency_limit_hz']=math.sqrt(tangent/derived['effective_inertia_kg_m2'])/(2*math.pi)
        budget['normalization_scope']='Existing spring/damping retained with updated native hub-only inertia; original frequency target is not retuned'
        pending.append((key,options,ratio_key,ratio,budget))
        report[key]=dict(native_inertia_before=before[inertia_key],native_inertia_after=derived[inertia_key],
            damping_ratio_before=options[ratio_key],damping_ratio_after=ratio,
            retained_spring=spring,retained_damping=damp,step_eigenvalue=step)
    for key,options,ratio_key,ratio,budget in pending:
        options[ratio_key]=ratio;contract[key]=budget
    return report


def apply(part, manifest, per_axle_kg):
    from vehicle_templates import wheel_support_mass
    if isinstance(per_axle_kg,bool) or not math.isfinite(per_axle_kg) or not 0<per_axle_kg<=1:
        raise ValueError('Wheel support reuse must be in (0, 1] kg per axle node')
    if manifest.get('wheel_support_reuse'):
        raise ValueError('Wheel support reuse already applied')
    shadow=copy.deepcopy(part); updated=copy.deepcopy(manifest)
    nodes=node_table(shadow); numerical=updated['numerical_mass']; reports={}
    wheels=updated['wheels']; roles=updated['component_roles']
    rows=[r for r in shadow.get('pressureWheels',[])[1:] if isinstance(r,list)]
    if len(rows)!=len(wheels) or {r[0] for r in rows}!=set(wheels):
        raise ValueError('Exactly one explicit pressure wheel per declared corner is required')
    removed=0.
    for row in rows:
        corner=row[0]; wheel=wheels[corner]; options=row[-1]
        owners=[o for o,r in roles.items() if r==corner.lower()+'_wheel']
        if len(owners)!=1:raise ValueError('Unique wheel mass owner required: '+corner)
        owner=owners[0]; axes=[wheel['nodes'][k] for k in ('axis_in','axis_out')]
        if len(set(axes))!=2 or set(row[3:5])!=set(axes):raise ValueError('Wheel axle contract differs')
        span=float(np.linalg.norm(np.array(nodes[axes[0]]['position'])-nodes[axes[1]]['position'])/2)
        before=ring_moments(options,span)
        if not math.isclose(before[0],wheel['wheel_mass_kg'],abs_tol=1e-8):
            raise ValueError('Wheel generated mass differs from its manifest')
        allocation=wheel['mass_allocation']
        if allocation.get('added_per_axle_node_kg',0)!=0 or updated['mass_allocations'].get(owner):
            raise ValueError('Start with wheel mass entirely in its rings')
        replacement,extra,detail=wheel_support_mass(options,[1.,1.],span,minimum=1.+per_axle_kg)
        after=ring_moments(replacement,span,extra)
        if not np.allclose(before,after,atol=1e-10,rtol=1e-10):
            raise ValueError('Wheel redistribution changed mass or inertia')
        updated['mass_allocations'][owner]={}
        for name in axes:
            entry=numerical['nodes'][name]; simulated=nodes[name]['options']['nodeWeight']
            if not math.isfinite(simulated) or simulated<max(2.,entry['target_kg'])-1e-8:
                raise ValueError('Loaded axle does not meet its minimum node mass')
            if not math.isclose(simulated,updated['nodes'][name]['mass_kg'],abs_tol=1e-8):
                raise ValueError('Explicit node mass differs from its manifest')
            amounts=entry['added_by_component_kg']; available=sum(amounts.values())
            if min(amounts.values(),default=0)<0 or available<extra-1e-9 or not math.isclose(available,entry['added_mass_kg'],abs_tol=1e-8):
                raise ValueError('Insufficient verified numerical ballast at '+name)
            allocations=updated['mass_allocations']
            if not math.isclose(sum(v.get(name,0) for v in allocations.values()),simulated,abs_tol=1e-8):
                raise ValueError('Incomplete mass ownership at '+name)
            for previous,value in list(amounts.items()):
                take=extra*value/available
                if allocations[previous].get(name,0)<value-1e-8:
                    raise ValueError('Numerical mass exceeds owner allocation')
                allocations[previous][name]-=take; amounts[previous]-=take
                numerical['added_by_component_kg'][previous]-=take
                if previous in updated['component_reports']:
                    updated['component_reports'][previous]['numerical_added_mass_kg']-=take
            allocations[owner][name]=extra
            entry['added_mass_kg']-=extra
            entry['redistributed_cad_mass_kg']+=extra
            entry['wheel_cad_mass_reused_kg']=extra
            entry['reasons'].append('existing wheel mass replaces reported ballast')
            if not math.isclose(entry['redistributed_cad_mass_kg']+entry['added_mass_kg'],simulated,abs_tol=1e-8):
                raise ValueError('Wheel support mass ledger does not balance')
        row[-1]=replacement
        wheel['wheel_mass_kg']-=2*extra
        # Actual explicit node masses did not change. Only generated ring mass
        # changed; its gravity load acts at the same wheel center as before.
        wheel['effective_unsprung_mass_kg']-=2*extra
        if wheel['effective_unsprung_mass_kg']<=0:raise ValueError('Invalid resulting unsprung load')
        allocation.update(added_per_axle_node_kg=extra,generated_mass_kg=wheel['wheel_mass_kg'],
            support_mass_source='existing_wheel_mass_replaces_reported_ballast',
            rim_redistribution=detail)
        reports[corner]=dict(replaced_ballast_kg=2*extra,moments_before=before.tolist(),moments_after=after.tolist(),
            hub_width_before_m=options['hubWidth'],hub_width_after_m=replacement['hubWidth'],
            hub_node_mass_kg=replacement['hubNodeWeight'],tread_node_mass_kg=replacement['nodeWeight'])
        removed+=2*extra
    inertias={r[0]:2*r[-1]['numRays']*r[-1]['hubNodeWeight']*r[-1]['hubRadius']**2 for r in rows}
    coupling=renormalize_couplings(shadow,updated['device_contract'],inertias,updated['template_definition']['parameters'])
    numerical['added_mass_kg']-=removed
    numerical['wheel_ballast_replaced_kg']=removed
    refresh_load_metadata(updated,{})
    if not math.isclose(updated['expected_dry_mass_kg'],manifest['expected_dry_mass_kg']-removed,abs_tol=1e-7):
        raise ValueError('Total mass did not decrease by the replaced ballast')
    report=dict(per_axle_kg=per_axle_kg,replaced_ballast_kg=removed,corners=reports,coupling_normalization=coupling,
        scope=__doc__,status='native_validation_required')
    updated['wheel_support_reuse']=report
    updated['limitations']=[s for s in updated['limitations'] if not s.startswith('Numerical support mass adds ')]
    updated['limitations'].append(f"Numerical support mass adds {numerical['added_mass_kg']:.6f} kg beyond CAD mass after replacing {removed:.6f} kg axle ballast with existing wheel mass. Dynamic equivalence remains unqualified.")
    updated['limitations'].append('Wheel support reuse changes internal rim width and ring masses, retaining wheel mass/inertia and tire coefficients; native tire response requires validation.')
    part.clear();part.update(shadow);manifest.clear();manifest.update(updated)
    return report


def build(receipt,output,per_axle_kg=1.):
    if Path(output).exists():raise FileExistsError('Use a fresh output directory')
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes())
    files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    apply(next(iter(parts.values())),manifest,per_axle_kg)
    manifest['template_definition']['parameters']['wheel_support_reuse_kg']=per_axle_kg
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest.pop('verification',None);manifest.pop('physical_evidence',None)
    manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'wheel-reuse-baseline-receipt.json':receipt.read_bytes(),
        'numerical-generator/wheel_support_reuse.py':Path(__file__).read_bytes(),
        'numerical-generator/vehicle_templates.py':Path(__file__).with_name('vehicle_templates.py').read_bytes(),
        'numerical-generator/rigidity_mass_plan.py':Path(__file__).with_name('rigidity_mass_plan.py').read_bytes()})
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Wheel CAD mass replaces numerical axle ballast; native qualification pending')
