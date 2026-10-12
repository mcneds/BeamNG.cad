"""Check controlled shared halfshaft/carrier generation against its baseline.

The carrier's residual-moment quadrature positions may change when the existing
shaft center joins its rigid node set. Authored geometry, other node positions,
joint centers, shaft plunge, physical suspension settings and tire inputs may not.
This verifies declared controls and package identity, not native motion or damage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np


def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def rest_mesh(path,part,manifest):
    """Normalize the exporter-only rigid prop translation; reject other changes."""
    tree=ET.parse(path);ns={'c':'http://www.collada.org/2005/11/COLLADASchema'};positions={}
    props={r[1]:r for r in part.get('props',[])[1:] if isinstance(r,list)}
    flex={};defaults={}
    for row in part.get('flexbodies',[])[1:]:
        if isinstance(row,dict):defaults.update(row)
        else:flex[row[0]]=defaults|(row[-1] if isinstance(row[-1],dict) else {})
    for geometry in tree.findall('.//c:geometry',ns):
        name=geometry.attrib['name'];p=props.get(name)
        zero={'x':0,'y':0,'z':0}
        if p is None:
            if name not in flex or any(flex[name].get(k,zero)!=zero for k in ('pos','rot')):raise ValueError('Unsupported flexbody rest transform')
            offset=np.zeros(3)
        else:
            if p[0]!='constant' or p[8:12]!=[0,0,0,1]:raise ValueError('Expected constant rigid prop')
            if any(p[i]!=zero for i in (5,6,7)) or p[-1].get('baseRotationGlobal')!=zero or p[-1].get('baseTranslation')!=zero:
                raise ValueError('Unsupported rigid prop transform')
            offset=np.asarray(manifest['nodes'][p[2]]['position'])
        inputs=geometry.findall('c:mesh/c:vertices/c:input',ns)
        refs=[v.attrib['source'].lstrip('#') for v in inputs if v.attrib['semantic']=='POSITION']
        if len(refs)!=1:raise ValueError('One vertex position stream required')
        sources=[s for s in geometry.findall('c:mesh/c:source',ns) if s.attrib['id']==refs[0]]
        if len(sources)!=1:raise ValueError('Position source missing')
        data=sources[0].find('c:float_array',ns);xyz=np.fromstring(data.text,sep=' ').reshape(-1,3)
        positions[name]=xyz+offset
        data.text='[normalized rigid position stream]'
    if not positions:raise ValueError('No rigid mesh geometry')
    return positions,ET.tostring(tree.getroot())


def audit(baseline,candidate):
    a,b=[read(p/'manifest.json') for p in (baseline,candidate)]
    for key in ('component_roles','geometry_inputs_sha256'):
        if a[key]!=b[key]:raise ValueError('Changed source identity: '+key)
    if not np.isclose(a['cad_dry_mass_kg'],b['cad_dry_mass_kg'],atol=1e-8,rtol=0):raise ValueError('CAD mass changed')
    for key in ('hardpoints','halfshafts','shafts','corners','attachment_contract'):
        if a['template_definition'].get(key)!=b['template_definition'].get(key):raise ValueError('Authored definition changed: '+key)
    old={j['id']:j for j in a['joints']};new={j['id']:j for j in b['joints']}
    if len(old)!=len(a['joints']) or len(new)!=len(b['joints']) or old.keys()!=new.keys():raise ValueError('Joint identities changed')
    changed=[];parents=set()
    for name,j in new.items():
        before=old[name]
        if before==j:continue
        if not (before['kind']=='spherical' and j['kind']=='shared_ball' and j['nodes']==[before['nodes'][-1]]):
            raise ValueError('Unexpected joint topology change: '+name)
        if before['parent']!=j['parent'] or before['child']!=j['child']:raise ValueError('Joint owner changed')
        center=j['nodes'][0];parent=j['parent'];child=j['child']
        if center not in b['mass_allocations'][parent] or center not in b['mass_allocations'][child]:raise ValueError('Shared ownership missing')
        if a['nodes'][center]['position']!=b['nodes'][center]['position']:raise ValueError('Joint center moved')
        if child not in b['template_definition'].get('halfshafts',{}) or center!=child+'_outer':raise ValueError('Only outer halfshaft centers may be shared')
        parents.add(parent);changed.append(dict(joint=name,node=center,parent=parent,child=child))
    expected=len(b['template_definition'].get('halfshafts',{}))
    if not changed or len(changed)!=expected:raise ValueError('Not all declared halfshaft centers changed')
    removed=set(a['nodes'])-set(b['nodes']);added=set(b['nodes'])-set(a['nodes'])
    sparse=b['template_definition'].get('parameters',{}).get('upright_representation')=='hardpoint_lumped'
    if added or any(not sparse or not any(n.startswith(o+'_mass_') and n in a['mass_allocations'][o] for o in parents) for n in removed):
        raise ValueError('Non-quadrature node identity changed')
    moved=[]
    for n,v in b['nodes'].items():
        if v['position']==a['nodes'][n]['position']:continue
        if not any(n.startswith(o+'_mass_') and n in b['mass_allocations'][o] for o in parents):raise ValueError('Non-quadrature node moved: '+n)
        moved.append(n)
    for corner in a['wheels']:
        for key in ('spring_n_m','damper_ns_m','spring_preload_n','coilover_spring','brake_torque_nm','tire_contract','cad_wheel_mass_kg'):
            if a['wheels'][corner].get(key)!=b['wheels'][corner].get(key):raise ValueError('Physical setting changed: '+corner+' '+key)
    assets=[];physical=[];parts=[]
    for folder,m in ((baseline,a),(candidate,b)):
        r=read(folder/'static_frame_build.json')
        for name,digest in r['component_files'].items():
            if sha(folder/name)!=digest:raise ValueError('Changed packaged file: '+name)
        names=[n for n in r['component_files'] if n.endswith('.jbeam')]
        if len(names)!=1:raise ValueError('One assembled JBeam required')
        part=next(iter(read(folder/names[0]).values()))
        parts.append(part)
        assets.append({n:h for n,h in r['component_files'].items() if not n.endswith('.jbeam')})
        physical.append({key:part.get(key) for key in ('pressureWheels','mainEngine','clutch','gearbox','powertrain')})
    if assets[0].keys()!=assets[1].keys():raise ValueError('Non-JBeam asset identities changed')
    rebased=[]
    for name,digest in assets[0].items():
        if digest==assets[1][name]:continue
        if not sparse or Path(name).suffix!='.dae' or Path(name).stem not in parents:raise ValueError('Non-carrier asset changed')
        x,structure_a=rest_mesh(baseline/name,parts[0],a);y,structure_b=rest_mesh(candidate/name,parts[1],b)
        if structure_a!=structure_b or x.keys()!=y.keys():raise ValueError('Mesh topology or appearance changed')
        if any(x[k].shape!=y[k].shape or not np.allclose(x[k],y[k],atol=2e-8,rtol=0) for k in x):raise ValueError('Rest mesh geometry changed')
        rebased.append(name)
    reaction_changes=[]
    wa,wb=physical[0]['pressureWheels'],physical[1]['pressureWheels']
    if wa!=wb:
        if not sparse or wa[0]!=wb[0] or len(wa)!=len(wb):raise ValueError('Pressure wheel structure changed')
        for left,right in zip(wa[1:],wb[1:]):
            if left==right:continue
            if left[:6]+left[7:]!=right[:6]+right[7:]:raise ValueError('Pressure wheel setting changed')
            corner=left[0];old_arm=left[6];new_arm=right[6]
            owner=next((o for o,r in b['component_roles'].items() if r==corner.lower()+'_upright'),None)
            if old_arm not in removed or owner not in parents or new_arm not in b['mass_allocations'][owner]:
                raise ValueError('Brake reaction left its rigid owner')
            if new_arm!=b['wheels'][corner]['brake_reaction_node'] or new_arm not in b['numerical_mass']['nodes']:
                raise ValueError('Untracked loaded brake reaction')
            x,y,p=[np.array(b['nodes'][n]['position']) for n in (right[3],right[4],new_arm)]
            lever=float(np.linalg.norm(np.cross(y-x,p-x))/np.linalg.norm(y-x))
            if not np.isfinite(lever) or lever<1e-6:raise ValueError('Degenerate brake reaction lever')
            reaction_changes.append(dict(corner=corner,owner=owner,before=old_arm,after=new_arm,lever_m=lever,
                scope='Rigid-body brake reaction remapped; torque setting retained. Compliant load path requires native verification.'))
    for key in ('mainEngine','gearbox','powertrain','clutch'):
        if physical[0][key]!=physical[1][key]:raise ValueError('Exported drivetrain/tire law changed: '+key)
    minimum=min(b['nodes'][n]['mass_kg'] for n in b['numerical_mass']['nodes'])
    if minimum<2-1e-8:raise ValueError('Loaded node below 2 kg')
    return dict(status='passed',scope=__doc__,baseline=str(baseline),candidate=str(candidate),
        manifest_sha256={str(p):sha(p/'manifest.json') for p in (baseline,candidate)},
        shared_joints=changed,relocated_quadrature_nodes=moved,removed_quadrature_nodes=sorted(removed),
        authored_geometry_and_hardware_unchanged=True,non_jbeam_assets_unchanged=not rebased,
        rebased_rigid_meshes=rebased,rest_meshes_and_appearances_unchanged=True,
        brake_reaction_changes=reaction_changes,
        loaded_nodes_before=len(a['numerical_mass']['nodes']),loaded_nodes_after=len(b['numerical_mass']['nodes']),
        minimum_loaded_node_kg=minimum,mass_before_kg=a['expected_dry_mass_kg'],mass_after_kg=b['expected_dry_mass_kg'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Use a fresh output path')
    r=audit(a.baseline,a.candidate);a.output.write_text(json.dumps(r,indent=2)+'\n');print('Controlled shared centers:',len(r['shared_joints']))
