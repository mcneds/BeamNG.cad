"""Prefer existing loaded hardpoints for numerically equivalent brake reactions.

This changes where the native wheel's reaction torque enters a rigid carrier;
it does not change its commanded torque. Finite carrier compliance makes native
validation essential. No node is created, moved or given additional mass.
"""
import hashlib,json,math
from pathlib import Path
import numpy as np
from frame_harness.build import node_table
from vehicle_revisions import canonical,load_baseline,package_revision


def choose(nodes,group,axes,preferred,fraction=.95,minimum_mass=2.):
    if not math.isfinite(fraction) or not 0<fraction<=1:raise ValueError('Invalid inertia retention fraction')
    if len(axes)!=2 or len(set(axes))!=2 or not set(axes)<=set(group):raise ValueError('Carrier must own both axle nodes')
    point=lambda n:np.asarray(nodes[n]['position'],float)
    axis=point(axes[1])-point(axes[0]);length=np.linalg.norm(axis)
    if length<1e-5:raise ValueError('Degenerate wheel axis')
    axis/=length;candidates=[]
    for name in sorted(set(group)-set(axes)):
        ns=axes+[name];mass=np.array([nodes[n]['options']['nodeWeight'] for n in ns],float)
        if not np.isfinite(mass).all() or min(mass)<=0:raise ValueError('Invalid reaction node masses')
        lever=float(np.linalg.norm(np.cross(axis,point(name)-point(axes[0]))))
        if lever<.001:continue
        xyz=np.array([point(n) for n in ns]);xyz-=mass@xyz/mass.sum()
        tensor=sum(m*(p@p*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,xyz))
        inertia=1/float(axis@np.linalg.solve(tensor,axis))
        if not math.isfinite(inertia) or inertia<=0:raise ValueError('Invalid carrier reaction inertia')
        candidates.append(dict(node=name,inertia_kg_m2=inertia,lever_m=lever,mass_kg=float(mass[-1]),preferred=name in preferred))
    if not candidates:raise ValueError('No valid brake reaction lever')
    best=max(candidates,key=lambda v:v['inertia_kg_m2'])
    eligible=[v for v in candidates if v['preferred'] and v['mass_kg']>=minimum_mass and v['inertia_kg_m2']>=fraction*best['inertia_kg_m2']]
    selected=max(eligible,key=lambda v:v['inertia_kg_m2']) if eligible else best
    # Never create an unconditioned new force application site.
    if selected['mass_kg']<minimum_mass:raise ValueError('Selected reaction node is below the existing support mass floor')
    return selected['node'],dict(selected=selected,best=best,candidates=candidates,retained_inertia_fraction=selected['inertia_kg_m2']/best['inertia_kg_m2'])


def apply(part,manifest,corners=('FL','FR'),fraction=.95):
    if manifest.get('brake_reaction_routing'):raise ValueError('Brake reaction routing already applied')
    if not corners or len(set(corners))!=len(corners) or not set(corners)<=set(manifest['wheels']):raise ValueError('Choose distinct existing wheels')
    nodes=node_table(part);rows=part['pressureWheels'];column=rows[0].index('nodeArm:');reports={};changes=[]
    for corner in corners:
        wheel=manifest['wheels'][corner];axes=wheel['tire_contract']['axle_nodes']
        owners=[o for o,r in manifest['component_roles'].items() if r in (corner.lower()+'_upright',corner.lower()+'_trailing_arm') and set(axes)<=set(manifest['mass_allocations'].get(o,{}))]
        if len(owners)!=1:raise ValueError('One carrier must own the axle nodes')
        preferred=set(wheel['hardpoint_nodes'].values());group=manifest['mass_allocations'][owners[0]]
        name,report=choose(nodes,group,axes,preferred,fraction)
        matches=[r for r in rows[1:] if isinstance(r,list) and r[0]==corner]
        if len(matches)!=1 or matches[0][column]!=wheel['brake_reaction_node']:raise ValueError('Wheel reaction metadata does not match JBeam')
        report.update(before=wheel['brake_reaction_node'],after=name);reports[corner]=report;changes.append((matches[0],wheel,name))
    for row,wheel,name in changes:
        row[column]=name;wheel['brake_reaction_node']=name
        if 'reaction_nodes' in wheel:wheel['reaction_nodes']['nodeArm']=name
    manifest['brake_reaction_routing']=dict(corners=list(corners),minimum_inertia_fraction=fraction,wheels=reports,scope=__doc__)
    return manifest['brake_reaction_routing']


def build(receipt,output,corners=('FL','FR'),fraction=.95):
    if Path(output).exists():raise FileExistsError('Use a fresh output directory')
    receipt=Path(receipt);record,manifest,contents,snapshot=load_baseline(receipt)
    project=json.loads((receipt.parent/'project.snapshot.json').read_bytes());files=[n for n in contents if n.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    parts=json.loads(contents[files[0]])
    if len(parts)!=1:raise ValueError('One assembled part required')
    apply(next(iter(parts.values())),manifest,corners,fraction)
    manifest['template_definition']['parameters'].update(brake_reaction_hardpoint_corners=list(corners),brake_reaction_inertia_fraction=fraction)
    manifest['template_sha256']=hashlib.sha256(canonical(manifest['template_definition'])).hexdigest()
    manifest.pop('verification',None);manifest.pop('physical_evidence',None);manifest.update(rendered_review_status='required',calibration_inputs_status='numerical_revision')
    contents[files[0]]=canonical(parts)
    provenance={key:(receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'baseline-receipt.json':receipt.read_bytes(),'brake-reaction-routing.json':canonical(manifest['brake_reaction_routing']),'numerical-generator/brake_reaction.py':Path(__file__).read_bytes()})
    if load_baseline(receipt)[3]!=snapshot:raise ValueError('Baseline changed during revision')
    return package_revision(output,project,manifest,contents,provenance,receipt,'Existing hardpoint brake reaction routing; native qualification pending')
