"""Reconstruct owned CAD recipes, then review actual native mate/point evidence.

Recipe coordinates are construction targets. Production bindings are populated
only from MountAnchors and NativeMateScanner output, checked against those targets.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from joint_authoring import requests,proposals,definition

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def tube(a,b,r,w):
    return dict(kind='tube',center=None,size=None,a=list(a),b=list(b),radius=r,wall=w,
                analytic_volume_m3=math.pi*(r*r-(r-w)**2)*float(np.linalg.norm(np.array(b)-a)))
def component(owner,shapes,role=None):
    return dict(id=owner,role=role or owner,primitives=shapes,material='AISI 4130 Steel, annealed at 865C',
                surface_mass_mode='thickness',thickness=.002,analytic_volume_m3=sum(s['analytic_volume_m3'] for s in shapes))

def prepare(baseline,output,radius):
    output.mkdir(parents=True,exist_ok=False)
    old=read(baseline/'project.snapshot.json');spec=read(old['TemplateDefinitionPath'])
    parts={};sources={}
    for c in old['Components']:
        folder=Path(c['GeometryDirectory']).parent.parent
        recipe=read(folder/'recipe.json')
        parts[c['Id']]=copy.deepcopy(next(p for p in recipe['components'] if p['id']==c['Id']))
        sources[c['Id']]=dict(recipe=str(folder/'recipe.json'),sha256=hashlib.sha256((folder/'recipe.json').read_bytes()).hexdigest())
    if radius:
        module=importlib.util.spec_from_file_location('rear_recipe',ROOT/'tools/prepare-radius-toe-fixture.py')
        helper=importlib.util.module_from_spec(module);module.loader.exec_module(helper)
        helper.make_recipe(output/'rear-recipe.json');rear=read(output/'rear-recipe.json')
        for c in rear['components']:parts[c['id']]=c
        for corner in ('RL','RR'):spec['hardpoints'][corner]=rear['hardpoints'][corner]
        spec['templates']['rear_suspension']='trailing_radius_toe'
    # Positive physical housing, rack and coilover bodies; no artificial node ballast.
    hp=spec['hardpoints'];a=np.array(hp['FR']['tie_inner']);b=np.array(hp['FL']['tie_inner']);u=(b-a)/np.linalg.norm(b-a)
    parts['steering_rack']=component('steering_rack',[tube(a+u*.03,b-u*.03,.028,.007),tube(a-u*.025,b+u*.025,.018,.006)])
    members={'steering_rack':dict(housing=[0],rack=[1])}
    for corner,p in hp.items():
        owner=corner.lower()+'_spring_damper';a=np.array(p['shock_top']);b=np.array(p['shock_bottom']);d=b-a
        parts[owner]=component(owner,[tube(a,a+d*.58,.021,.003),tube(a+d*.40,b,.010,.004),tube(a+d*.12,a+d*.86,.029,.0012)])
        members[owner]=dict(housing=[0,2],shaft=[1])
    # A second physical panel exercises explicit linked release separately.
    roof=copy.deepcopy(parts['panel_floor']);roof.update(id='panel_roof',role='panel')
    roof['primitives'][0]['center'][2]=.77;parts['panel_roof']=roof
    spec['fixed_mounts']['panel_roof']=[[p[0],p[1],.77] for p in spec['fixed_mounts']['panel_floor']]
    if radius:
        shaft=spec['shafts'].pop('front_propshaft');parts.pop('front_propshaft')
        middle=[.065,.93,.365];ends=[shaft['outer'],middle,shaft['inner']]
        for i in range(2):parts['front_propshaft_'+str(i+1)]=component('front_propshaft_'+str(i+1),[tube(ends[i],ends[i+1],.019,.003)],'front_propshaft')
        size=[.10,.09,.08]
        parts['shaft_carrier']=component('shaft_carrier',[dict(kind='box',center=middle,size=size,a=None,b=None,radius=None,wall=None,analytic_volume_m3=float(np.prod(size)))],'shaft_carrier')
        spec['fixed_mounts']['shaft_carrier']=[[middle[0]+x,middle[1]+y,middle[2]] for x,y in [(-.04,-.03),(.04,-.03),(0,.03)]]
    plan=dict(datums=[],mates=[],bindings=[],members=members,connections=[],parameters=spec['parameters'],sources=sources,
              baseline=str(baseline),templates=spec['templates'])
    plan['parameters']['rack_half_travel_m']=.035
    def datum(owner,label,p,member=None):
        key=owner+'__'+label
        found=next((d for d in plan['datums'] if d['id']==key),None)
        if found:
            if not np.allclose(found['position'],p,atol=1e-9):raise ValueError('Duplicate construction datum '+key)
        else:plan['datums'].append(dict(id=key,owner=owner,member=member,position=list(p)))
        return key
    def mate(label,owner,other,p,member=None,other_member=None,expected='spherical'):
        a=datum(owner,label,p,member);b=datum(other,label,p,other_member)
        plan['mates'].append(dict(name=label,a=a,b=b,type='point',expected=expected))
        return a,b
    def bind(key,owner,point_id,mate_name=None):plan['bindings'].append(dict(request=key,owner=owner,datum=point_id,mate=mate_name))
    for corner,p in hp.items():
        low=corner.lower();rear=corner.startswith('R');upright=low+'_upright';wheel=low+'_wheel'
        wishbone=not rear or not radius
        def joint(key,owner,other,member=None,other_member=None,expected='spherical',bindings=True):
            label=corner+'_'+key;a,b=mate(label,owner,other,p[key],member,other_member,expected)
            if bindings:bind(corner+'.'+key,owner,a,label)
        if wishbone:
            for arm in ('upper','lower'):
                for end in ('front','rear'):joint(arm+'_inner_'+end,low+'_'+arm+'_wishbone','frame',expected='revolute')
                joint(arm+'_ball',low+'_'+arm+'_wishbone',upright)
            shock_owner=low+'_lower_wishbone'
        else:
            for end in ('inner','outer'):joint('hinge_'+end,low+'_trailing_arm','frame',expected='revolute')
            joint('carrier_ball',low+'_trailing_arm',upright)
            for radius_key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod')]:
                for end,other in [('inner','frame'),('outer',upright)]:joint(radius_key+'_'+end,low+'_'+suffix,other)
            shock_owner=low+'_trailing_arm'
        tie=low+('_toe_link' if rear else '_tie_rod')
        joint('tie_inner',tie,'frame' if rear else 'steering_rack',other_member=None if rear else 'rack')
        joint('tie_outer',tie,upright)
        joint('hub',wheel,upright,expected='revolute')
        joint('hub_axis',wheel,upright,expected='revolute')
        joint('shock_top',low+'_spring_damper','frame',member='housing')
        joint('shock_bottom',low+'_spring_damper',shock_owner,member='shaft')
        plan['mates'].append(dict(name=low+'_slide',type='concentric',owner=low+'_spring_damper',member_a='housing',member_b='shaft',expected='cylindrical'))
    plan['mates'].append(dict(name='rack_slide',type='concentric',owner='steering_rack',member_a='housing',member_b='rack',expected='prismatic'))
    for owner,shaft in spec['halfshafts'].items():
        corner=shaft['corner'];diff=('front_diff' if corner.startswith('F') else 'rear_final_drive' if radius else 'rear_diff')
        for end,other in [('inner',diff),('outer',corner.lower()+'_wheel')]:
            label=owner+'_'+end;a,b=mate(label,owner,other,shaft[end]);bind(owner+'.'+end+'_joint',owner,a,label)
        plan['parameters']['shaft.'+owner+'.plunge_m']=shaft.get('plunge_m',.06)
    for owner,shaft in spec['shafts'].items():
        for end,suffix,other in [('inner','input_joint',shaft['inner_role']),('outer','output_joint',shaft['outer_role'])]:
            label=owner+'_'+suffix;a,b=mate(label,owner,other,shaft[end]);bind(owner+'.'+suffix,owner,a,label)
        plan['parameters']['shaft.'+owner+'.plunge_m']=shaft.get('plunge_m',.03)
    if radius:
        for i in range(2):
            owner='front_propshaft_'+str(i+1)
            for j,suffix in enumerate(('input_joint','output_joint')):
                other=['rear_final_drive','shaft_carrier','front_diff'][i+j];label=owner+'_'+suffix
                a,b=mate(label,owner,other,ends[i+j]);bind(owner+'.'+suffix,owner,a,label)
            plan['parameters']['shaft.'+owner+'.plunge_m']=.03
    # Native rigid placements use three orthogonal geometric plane mates.
    # Failure is declared independently through actual captured fastener sites.
    for owner,points in spec['fixed_mounts'].items():
        member='housing' if owner=='steering_rack' else None
        plan['mates'].append(dict(name=owner+'_placement',type='planes',owner=owner,member=member,expected='rigid'))
        for i,p in enumerate(points):
            label=owner+'_mount_'+str(i)
            a=datum('frame',label,p);b=datum(owner,label,p,member)
            plan['connections'].append(dict(id=label,a=a,b=b,kind='breakable_fastener' if owner.startswith('panel_') else 'fixed',
                                            release_set='roof' if owner=='panel_roof' else '',strength=4000))
    # Ownership comes from the actual configuration catalog, never list order.
    project=dict(Components=[dict(Id=c['id'],MvpRole=c['role']) for c in parts.values()],MvpTemplates=[dict(Category=k,Template=v) for k,v in spec['templates'].items()])
    for r in requests(project):
        found=next(b for b in plan['bindings'] if b['request']==r['id'])
        if found['owner']!=r['role']:
            m=next(m for m in plan['mates'] if m['name']==found['mate'])
            found['datum']=next(d for d in (m['a'],m['b']) if next(v for v in plan['datums'] if v['id']==d)['owner']==r['role'])
            found['owner']=r['role']
    recipe=dict(kind='synthetic_native_vehicle',version=4,variant='authored_radius_toe' if radius else 'authored_wishbones',
                source='Owned reconstruction of independently generated CAD revisions',components=list(parts.values()),templates=spec['templates'],hardpoints=hp)
    recipe['recipe_sha256']=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    write(output/'recipe.json',recipe);write(output/'authoring.json',plan)

def review(project_path,plan_path,output):
    project=read(project_path);plan=read(plan_path);w=project['JointWorkspace'];joints=proposals(w)
    first=Path(plan_path).parent/'native-snapshot.json'
    if first.exists():
        prior=proposals(read(first)['JointWorkspace'])
        if {j['Id']:j['SourceHash'] for j in prior}!={j['Id']:j['SourceHash'] for j in joints}:
            raise ValueError('Native mate identity/geometry changed across reopen')
    for j in joints:
        names={m['Name'] for m in w['Mates'] if m['Id'] in j['MateIds']}
        expected={m['expected'] for m in plan['mates'] if any(n==m['name'] or n.startswith(m['name']+'_plane') for n in names)}
        if len(expected)!=1 or j['Kind'] not in expected or j.get('Issue'):
            raise ValueError('Native joint differs from independent construction: '+str(j))
        j['Status']='approved'
    w['Joints']=joints;w['Mode']='authored';w['Parameters']=[dict(Key=k,Value=v) for k,v in plan['parameters'].items()]
    for b in w['Bindings']:
        planned=next(v for v in plan['bindings'] if v['request']==b['Request'])
        expected=next(v for v in plan['datums'] if v['id']==planned['datum'])
        anchor=next(v for v in project['Anchors'] if v['Id']==b['AnchorId'])
        if anchor['Status']!='resolved' or not np.allclose(anchor['Position'],expected['position'],rtol=0,atol=1e-7):raise ValueError('Native point differs: '+b['Request'])
        if planned['mate']:
            ids={m['Id'] for m in w['Mates'] if m['Name']==planned['mate']}
            selected=[j for j in joints if ids.intersection(j['MateIds'])]
            if len(selected)!=1:raise ValueError('Native binding missing or ambiguous: '+b['Request'])
            b.update(JointId=selected[0]['Id'],Point='anchor')
    from full_vehicle_worker import definition_for_project
    generated=definition_for_project(project)
    write(project_path,project);write(output,dict(status='passed',native_mates=len(w['Mates']),reviewed_joints=len(joints),bindings=len(w['Bindings']),definition=generated))

def audit(project_path,recipe_path,output):
    import components as c
    project=read(project_path);shapes={p['id']:p for p in read(recipe_path)['components']};rows=[]
    for group in project['Components']:
        shape=shapes[group['Id']];snapshot=read(Path(group['GeometryDirectory'])/'material-snapshot.json')
        densities={float(b['density_kg_m3']) for b in snapshot['bodies']}
        if len(densities)!=1:raise ValueError('Independent primitive audit requires one material per group')
        volume=sum(s['analytic_volume_m3'] if s['kind']!='sheet' else
                   s['size'][0]*s['size'][1]*shape['thickness'] if shape['surface_mass_mode']=='thickness' else 0
                   for s in shape['primitives'])
        expected=volume*densities.pop();mass,center,inertia=c.read_geometry(group)[1]
        if abs(mass-expected)>max(1e-6,expected*1e-5):raise ValueError('Native mass differs from primitive volume: '+group['Id'])
        row=dict(component=group['Id'],cad_mass_kg=mass,analytic_mass_kg=expected)
        members=[m for m in project.get('JointWorkspace',{}).get('Members',[]) if m['ComponentId']==group['Id']]
        if members:
            moments=[c.read_geometry(group|dict(Id=m['Id'],GeometryDirectory=m['GeometryDirectory']))[1] for m in members]
            member_mass=sum(v[0] for v in moments);member_center=sum(m*p for m,p,i in moments)/member_mass
            member_inertia=sum(i+m*(np.eye(3)*((p-member_center)@(p-member_center))-np.outer(p-member_center,p-member_center)) for m,p,i in moments)
            if abs(member_mass-mass)>1e-6 or np.linalg.norm(member_center-center)>1e-7 or np.linalg.norm(member_inertia-inertia)>max(1e-7,np.linalg.norm(inertia)*1e-5):
                raise ValueError('Moving members do not partition the logical CAD mass/COM/inertia: '+group['Id'])
            row['member_partition']='mass, COM and inertia passed'
        rows.append(row)
    write(output,dict(status='passed',components=rows,total_mass_kg=sum(r['cad_mass_kg'] for r in rows)))

if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    a=s.add_parser('prepare');a.add_argument('baseline',type=Path);a.add_argument('output',type=Path);a.add_argument('--radius-toe',action='store_true')
    a=s.add_parser('review');a.add_argument('project',type=Path);a.add_argument('plan',type=Path);a.add_argument('output',type=Path)
    a=s.add_parser('audit');a.add_argument('project',type=Path);a.add_argument('recipe',type=Path);a.add_argument('output',type=Path)
    a=p.parse_args()
    if a.action=='prepare':prepare(a.baseline,a.output,a.radius_toe)
    elif a.action=='review':review(a.project,a.plan,a.output)
    else:audit(a.project,a.recipe,a.output)
