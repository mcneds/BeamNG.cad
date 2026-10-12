"""Fit replacement CAD properties on an existing component graph, transactionally.

Mass contributions are stored separately when a link shares an endpoint with an
arm. Fitting one component therefore cannot erase its neighbour's mass. Rigid
template stiffness remains a numerical representation, not a material test.
"""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path
import numpy as np
import components as c
from frame_harness.build import node_table
from vehicle_revisions import load_baseline, canonical, package_revision


def topology(contents):
    result={}
    for name,data in contents.items():
        if not name.endswith('.jbeam'):continue
        for owner,part in json.loads(data).items():
            result[owner]=dict(nodes={n:v['position'] for n,v in node_table(part).items()},
                               beams=[row[:2] for row in part.get('beams',[])[1:] if isinstance(row,list)],
                               hydros=[row[:2] for row in part.get('hydros',[])[1:] if isinstance(row,list)],
                               torsionbars=[row[:4] for row in part.get('torsionbars',[])[1:] if isinstance(row,list)],
                               triangles=part.get('triangles',[]),wheels=part.get('pressureWheels',[]))
    return result


def recalibrate_component(project,owner,output):
    receipt=Path(project['LastBuildReceipt']);record,manifest,contents,before=load_baseline(receipt)
    if project['Identity']!=record['identity']:raise ValueError('Import the baseline into this project first')
    if manifest.get('numerical_mass',{}).get('added_mass_kg',0)>0:
        raise ValueError('Regenerate vehicle physics after changing CAD properties: this build includes numerical support mass. Its support allocation, suspension loads and assembled rigidity must be fitted together; the existing build is unchanged.')
    if manifest.get('rigid_refits') or manifest.get('frame_reference'):
        raise ValueError('Regenerate vehicle physics after changing CAD properties: this build fits assembled rigid members together; the existing build is unchanged.')
    component=next(v for v in project['Components'] if v['Id']==owner)
    from component_worker import geometry_inputs
    hashes=geometry_inputs({'Components':[component]})
    if component.get('Template')=='calibrated_frame':
        raise ValueError('Frame properties need the independent CAD reference fit. Prepare a fresh frame calibration before regenerating vehicle physics.')
    old=manifest.get('mass_allocations',{}).get(owner)
    if not old:raise ValueError('This representation has no explicit component mass allocation; regenerate physics for this component')
    part_id=manifest['component_parts'][owner]
    matches=[(name,json.loads(data)) for name,data in contents.items() if name.endswith('.jbeam') and part_id in json.loads(data)]
    if len(matches)!=1:raise ValueError('Ambiguous physical component')
    name,parts=matches[0];part=parts[part_id];nodes=node_table(part);names=list(old)
    xyz=np.array([nodes[n]['position'] for n in names]);_,moments,_=c.read_geometry(component)
    if moments[0]<=0:raise ValueError('A physical component needs positive mass; use appearance replacement for a weightless skin')
    masses,fit=c.component_masses(xyz,*moments)
    if not fit['accepted'] or min(masses)<=0:
        raise ValueError('Replacement CAD cannot fit the fixed graph mass/COM/inertia. Regenerate physics; the baseline is unchanged.')
    original_topology=topology(contents)
    for n,mass in zip(names,masses):
        delta=float(mass)-old[n];nodes[n]['options']['nodeWeight']+=delta
        if nodes[n]['options']['nodeWeight']<=0:raise ValueError('Nonpositive combined node mass')
        manifest['nodes'][n]['mass_kg']=nodes[n]['options']['nodeWeight']
    part['nodes']=[['id','posX','posY','posZ']]+[[n,*v['position'],v['options']] for n,v in nodes.items()]
    # Preserve native beam kinds, stops, actuator controls and failure settings.
    # Lower endpoint mass can require a lower numerical spring/damping cap.
    degree={n:0 for n in nodes}
    expanded={section:list(c.expand(part[section])) for section in ('beams','hydros') if section in part}
    for rows in expanded.values():
        for row,_ in rows:
            for n in row[:2]:degree[n]+=1
    changed_springs=0
    for section,rows in expanded.items():
        replacement=[part[section][0]]
        for row,options in rows:
            a,b=row[:2]
            if (a in old or b in old) and options.get('beamType','|NORMAL')=='|NORMAL':
                ma=nodes[a]['options']['nodeWeight'];mb=nodes[b]['options']['nodeWeight']
                cap=min(ma/degree[a],mb/degree[b])*(2*math.pi*260)**2/2
                spring=min(options.get('beamSpring',180000),cap)
                changed_springs+=spring!=options.get('beamSpring')
                options=options|dict(beamSpring=spring,beamDamp=min(options.get('beamDamp',40),.6*math.sqrt(spring*ma*mb/(ma+mb))))
            replacement.append(row+[options])
        part[section]=replacement
    if 'torsionbars' in part:
        rows=[]
        original_masses=before['value']['contract']['nodes']
        for row,options in c.expand(part['torsionbars']):
            ratio=min(1.,*(nodes[n]['options']['nodeWeight']/original_masses[n]['mass_kg'] for n in row[:4]))
            # Both the spring and supported mass decrease together. Scaling C
            # by sqrt(ratio) would increase C/M and could break the timestep
            # budget even though the stiffness frequency stayed unchanged.
            rows.append(row+[options|dict(spring=options['spring']*ratio,damp=options.get('damp',0)*ratio)])
        part['torsionbars']=[part['torsionbars'][0]]+rows;manifest['torsionbars']=rows
    contents[name]=canonical(parts)
    if topology(contents)!=original_topology:raise ValueError('Property fit attempted to change topology or hardpoints')
    manifest['mass_allocations'][owner]=dict(zip(names,map(float,masses)))
    for chain in manifest.get('shaft_chains',{}).values():
        for section in chain['segments']:
            if section['component']==owner:section['mass_kg']=float(sum(masses))
    manifest['expected_dry_mass_kg']+=float(sum(masses))-sum(old.values())
    if hashes!=geometry_inputs({'Components':[component]}):raise ValueError('CAD changed during the property fit')
    if load_baseline(receipt)[3]!=before:raise ValueError('Physical baseline changed during the property fit')
    manifest.setdefault('geometry_inputs_sha256',{}).update(hashes)
    manifest.setdefault('component_reports',{})[owner]=fit|dict(numerical_springs_limited=changed_springs)
    manifest.pop('physical_evidence',None)
    # This rest-state assembly audit belongs to the previous mass/spring set.
    # Native verification must audit the revised compiled system again.
    manifest.pop('connection_budget',None)
    manifest.update(calibration_inputs_status='applied_for_'+owner,rendered_review_status='required',
                    property_revision=dict(component=owner,baseline_physics_sha256=before['sha256'],graph_preserved=True,
                                           scope='CAD mass/COM/inertia and numerical stability; template rigidity and rupture remain provisional'))
    provenance={'baseline-receipt.json':receipt.read_bytes(),'baseline-physics.json':canonical(before),
                'property-fit.json':canonical(fit),'property-inputs.json':canonical(hashes)}
    for entry in record.get('component_provenance_sha256',{}):provenance['baseline/'+entry]=(receipt.parent/entry).read_bytes()
    return package_revision(output,project,manifest,contents,provenance,receipt,manifest['physics_origin'])
